"""Five-question offline demonstration of the complete pipeline."""

from __future__ import annotations

import asyncio
import argparse
import json

from kyc_agent.agent import KYCGraphAgent, MockCypherGenerator
from kyc_agent.executor import InMemoryExecutor

QUESTIONS = [
    "Who is the CEO of Company X?",
    "What companies does Person A directly own?",
    "Who is the ultimate beneficial owner of Company X?",
    "Does Company X have any connection within 3 hops to a sanctioned entity?",
    "Summarize the risk profile of Company X.",
]


async def main(*, verbose: bool = False) -> None:
    agent = KYCGraphAgent(
        generator=MockCypherGenerator(),
        executor=InMemoryExecutor.default(),
    )
    for number, question in enumerate(QUESTIONS, 1):
        result = await agent.ask(question)
        print(f"\n{number}. {question}")
        print(result.summary)
        print("Cypher:", result.request.query)
        print(
            "Visualization:",
            result.chart_handoff.get("tool_name", "summary only"),
        )
        if verbose:
            print("Parameters:", json.dumps(result.request.parameters, sort_keys=True))
            print("Rows:", json.dumps(result.rows, sort_keys=True))
            print("Chart handoff:", json.dumps(result.chart_handoff, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show query parameters, result rows, and full chart payloads.",
    )
    asyncio.run(main(verbose=parser.parse_args().verbose))
