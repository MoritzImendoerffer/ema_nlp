"""Demo: end-to-end agentic RAG session.

Run on a host with Neo4j up (``scripts/start_services.sh``) and model credentials
in ``~/.myenvs/ema_nlp.env``::

    python scripts/run_agent_demo.py "What is the Acceptable Intake for NDMA?"

Records an MLflow run (local ``./mlruns`` by default) with the resolved retrieval
config + answer metrics.
"""

import logging
import sys


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from harness.agents.session import build_session

    query = sys.argv[1] if len(sys.argv) > 1 else "What is the Acceptable Intake for NDMA?"
    session = build_session(enable_tracing=True, experiment="ema_nlp")
    answer = session.run(query, record=True, run_name="demo")

    print("\n=== ANSWER ===\n" + answer.answer)
    if answer.caveats:
        print("\n=== CAVEATS ===")
        for caveat in answer.caveats:
            print(f" - {caveat}")
    print("\n=== CITATIONS ===")
    for citation in answer.citations:
        print(f" - {citation.source_url}")


if __name__ == "__main__":
    main()
