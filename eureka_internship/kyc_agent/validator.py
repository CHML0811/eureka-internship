"""Conservative, lexical Cypher validation for read-only KYC queries."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from kyc_agent.models import ValidatedCypher


class CypherValidationError(ValueError):
    """Raised when a query cannot safely enter the executor."""


ExplainHook = Callable[[str, dict[str, Any]], None]

_FORBIDDEN = {
    "CREATE",
    "DELETE",
    "DETACH",
    "MERGE",
    "SET",
    "REMOVE",
    "DROP",
    "ALTER",
    "RENAME",
    "GRANT",
    "DENY",
    "REVOKE",
    "TERMINATE",
    "START",
    "STOP",
    "LOAD",
    "FOREACH",
    "SHOW",
    "USE",
    "PROFILE",
    "EXPLAIN",
    "UNION",
}


def _mask_non_code(query: str) -> str:
    """Replace comments and quoted contents with spaces, preserving offsets."""
    chars = list(query)
    i = 0
    state = "code"
    quote = ""
    while i < len(chars):
        if state == "line":
            if chars[i] == "\n":
                state = "code"
            else:
                chars[i] = " "
            i += 1
            continue
        if state == "block":
            if query[i : i + 2] == "*/":
                chars[i : i + 2] = [" ", " "]
                i += 2
                state = "code"
            else:
                chars[i] = " "
                i += 1
            continue
        if state == "quote":
            current = chars[i]
            chars[i] = " "
            if current == "\\":
                if i + 1 < len(chars):
                    chars[i + 1] = " "
                    i += 2
                else:
                    i += 1
            elif current == quote:
                if i + 1 < len(chars) and chars[i + 1] == quote:
                    chars[i + 1] = " "
                    i += 2
                else:
                    state = "code"
                    i += 1
            else:
                i += 1
            continue

        pair = query[i : i + 2]
        if pair == "//":
            chars[i : i + 2] = [" ", " "]
            i += 2
            state = "line"
        elif pair == "/*":
            chars[i : i + 2] = [" ", " "]
            i += 2
            state = "block"
        elif chars[i] in {"'", '"', "`"}:
            quote = chars[i]
            chars[i] = " "
            i += 1
            state = "quote"
        else:
            i += 1
    if state in {"block", "quote"}:
        raise CypherValidationError("Unterminated comment or string")
    return "".join(chars)


class CypherValidator:
    """Reject mutating/admin Cypher and enforce bounded result/traversal sizes."""

    def __init__(
        self,
        *,
        max_limit: int = 200,
        max_path_hops: int = 5,
        allowed_procedures: tuple[str, ...] = (
            "db.labels",
            "db.relationshipTypes",
            "db.schema.visualization",
        ),
        explain_hook: ExplainHook | None = None,
    ) -> None:
        self.max_limit = max_limit
        self.max_path_hops = max_path_hops
        self.allowed_procedures = frozenset(p.lower() for p in allowed_procedures)
        self.explain_hook = explain_hook

    def validate(
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> ValidatedCypher:
        if not query.strip():
            raise CypherValidationError("Cypher query is empty")
        params = dict(parameters or {})
        masked = _mask_non_code(query)
        semicolons = [index for index, char in enumerate(masked) if char == ";"]
        if semicolons:
            last = semicolons[-1]
            if len(semicolons) > 1 or masked[last + 1 :].strip():
                raise CypherValidationError("Multiple Cypher statements are forbidden")
            query = query[:last].rstrip()
            masked = masked[:last].rstrip()
        words = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", masked)
        upper = [word.upper() for word in words]
        forbidden = next((word for word in upper if word in _FORBIDDEN), None)
        if forbidden:
            raise CypherValidationError(f"Forbidden Cypher clause: {forbidden}")

        self._validate_calls(masked)
        self._validate_paths(masked)
        bounded = self._bound_limit(query, masked, params)
        warnings: list[str] = []
        uses_parameters = bool(re.search(r"\$[A-Za-z_][A-Za-z0-9_]*", masked))
        if re.search(r"\bWHERE\b|\{", masked, re.IGNORECASE) and not uses_parameters:
            warnings.append("Prefer parameters over interpolated literals")
        result = ValidatedCypher(
            query=bounded,
            parameters=params,
            uses_parameters=uses_parameters,
            warnings=tuple(warnings),
        )
        if self.explain_hook:
            try:
                self.explain_hook("EXPLAIN " + result.query, params)
            except CypherValidationError:
                raise
            except Exception as exc:
                raise CypherValidationError(
                    f"EXPLAIN rejected query: {exc}"
                ) from exc
        return result

    def _validate_calls(self, masked: str) -> None:
        for match in re.finditer(
            r"\bCALL\s+([A-Za-z_][A-Za-z0-9_.]*)", masked, re.IGNORECASE
        ):
            procedure = match.group(1).lower()
            if procedure not in self.allowed_procedures:
                raise CypherValidationError(
                    f"Procedure is not allowlisted: {match.group(1)}"
                )

    def _validate_paths(self, masked: str) -> None:
        for match in re.finditer(r"\[\s*\*(?P<range>[^\]]*)\]", masked):
            path_range = match.group("range").strip()
            if not path_range:
                raise CypherValidationError("Unbounded variable path is forbidden")
            bounds = [int(value) for value in re.findall(r"\d+", path_range)]
            if not bounds or max(bounds) > self.max_path_hops:
                raise CypherValidationError(
                    f"Variable path exceeds maximum of {self.max_path_hops}"
                )
            if ".." in path_range and path_range.rstrip().endswith(".."):
                raise CypherValidationError("Unbounded variable path is forbidden")

    def _bound_limit(
        self, query: str, masked: str, params: dict[str, Any]
    ) -> str:
        limit_clause = re.search(r"\bLIMIT\b", masked, re.IGNORECASE)
        matches = list(re.finditer(r"\bLIMIT\s+(\d+)\b", masked, re.IGNORECASE))
        parameter_matches = list(
            re.finditer(
                r"\bLIMIT\s+\$([A-Za-z_][A-Za-z0-9_]*)\b",
                masked,
                re.IGNORECASE,
            )
        )
        result = query
        if parameter_matches:
            for match in parameter_matches:
                name = match.group(1)
                amount = params.get(name, self.max_limit)
                if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                    raise CypherValidationError(
                        f"LIMIT parameter ${name} must be a non-negative integer"
                    )
                params[name] = min(amount, self.max_limit)
        if not matches and not parameter_matches:
            if limit_clause:
                raise CypherValidationError(
                    "LIMIT must use an integer literal or parameter"
                )
            return query.rstrip().rstrip(";") + f" LIMIT {self.max_limit}"
        for match in reversed(matches):
            amount = int(match.group(1))
            if amount > self.max_limit:
                start, end = match.span(1)
                result = result[:start] + str(self.max_limit) + result[end:]
        return result
