"""AWS Textract adapter with a deterministic offline implementation."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal

from common.config import Settings
from doc_router.schema import RawExtraction

PdfUploader = Callable[[bytes, str], dict[str, Any]]


class TextractEngine:
    """Run synchronous images or asynchronous, S3-backed multi-page PDFs."""

    def __init__(
        self,
        *,
        provider: Literal["mock", "aws"] | None = None,
        client: Any | None = None,
        pdf_uploader: PdfUploader | None = None,
        allowed_pdf_bucket: str | None = None,
        poll_interval: float = 0.5,
        max_polls: int = 120,
    ) -> None:
        self.provider = provider or Settings.from_env().textract_provider
        self._client = client
        self.pdf_uploader = pdf_uploader
        self.allowed_pdf_bucket = allowed_pdf_bucket
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    @property
    def client(self) -> Any:
        if self._client is None:
            if self.provider != "aws":
                raise RuntimeError("Textract client is unavailable in mock mode")
            import boto3

            self._client = boto3.client("textract")
        return self._client

    def extract(self, document_bytes: bytes, *, filename: str | None = None) -> RawExtraction:
        if self.provider == "mock":
            return RawExtraction(
                engine_name="textract",
                raw_data={
                    "mode": "mock",
                    "Blocks": [],
                    "notice": "Synthetic result; no document data left this process.",
                },
                confidence=0.7,
            )
        if self.provider != "aws":
            raise ValueError(f"Unsupported Textract provider: {self.provider!r}")

        is_pdf = document_bytes.startswith(b"%PDF") or bool(
            filename and filename.lower().endswith(".pdf")
        )
        if is_pdf:
            return self._extract_pdf(document_bytes, filename or "document.pdf")
        response = self.client.analyze_document(
            Document={"Bytes": document_bytes},
            FeatureTypes=["FORMS", "TABLES"],
        )
        return RawExtraction(
            engine_name="textract",
            raw_data=dict(response),
            confidence=0.95,
        )

    def _extract_pdf(self, document_bytes: bytes, filename: str) -> RawExtraction:
        if self.pdf_uploader is None:
            raise ValueError(
                "Async PDF analysis requires a private S3 pdf_uploader callback"
            )
        location = self.pdf_uploader(document_bytes, filename)
        try:
            s3_object = location["S3Object"]
            bucket = s3_object["Bucket"]
            object_name = s3_object["Name"]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                "pdf_uploader must return "
                "{'S3Object': {'Bucket': ..., 'Name': ...}}"
            ) from exc
        if not isinstance(bucket, str) or not bucket or not isinstance(object_name, str):
            raise ValueError("S3Object Bucket and Name must be non-empty strings")
        if self.allowed_pdf_bucket is None:
            raise ValueError(
                "Async PDF analysis requires allowed_pdf_bucket to prevent "
                "uploading KYC documents to an unapproved bucket"
            )
        if bucket != self.allowed_pdf_bucket:
            raise ValueError(f"Unapproved Textract S3 bucket: {bucket!r}")
        started = self.client.start_document_analysis(
            DocumentLocation=location,
            FeatureTypes=["FORMS", "TABLES"],
        )
        job_id = started["JobId"]
        first: dict[str, Any] | None = None
        for _ in range(self.max_polls):
            response = self.client.get_document_analysis(JobId=job_id)
            status = response["JobStatus"]
            if status == "SUCCEEDED":
                first = response
                break
            if status in {"FAILED", "PARTIAL_SUCCESS"}:
                raise RuntimeError(f"Textract job {job_id} ended with {status}")
            time.sleep(self.poll_interval)
        if first is None:
            raise TimeoutError(f"Textract job {job_id} did not complete")

        blocks = list(first.get("Blocks", []))
        token = first.get("NextToken")
        while token:
            page = self.client.get_document_analysis(JobId=job_id, NextToken=token)
            if page.get("JobStatus") != "SUCCEEDED":
                raise RuntimeError(f"Textract pagination failed for job {job_id}")
            blocks.extend(page.get("Blocks", []))
            token = page.get("NextToken")
        payload = dict(first)
        payload["Blocks"] = blocks
        payload.pop("NextToken", None)
        payload["AsyncJobId"] = job_id
        return RawExtraction(
            engine_name="textract", raw_data=payload, confidence=0.95
        )


def extract(
    document_bytes: bytes, *, filename: str | None = None
) -> RawExtraction:
    """Use environment configuration for simple service integrations."""
    return TextractEngine().extract(document_bytes, filename=filename)
