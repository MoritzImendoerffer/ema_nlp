"""Demo: end-to-end recipe-driven agentic RAG session.

Run on a host with Neo4j up (``scripts/start_services.sh``) and model credentials
in ``~/.myenvs/ema_nlp.env``::

    python scripts/run_agent_demo.py "What is the Acceptable Intake for NDMA?"
    python scripts/run_agent_demo.py --recipe crag_agentic "..."

Builds the named recipe via ``harness.recipes.build_recipe`` (the same path app.py uses)
and runs one turn. With tracing enabled each turn is one MLflow trace carrying the
resolved recipe config; ``--recipe`` defaults to the registry default. (The optional
inline judge layer runs in the live Chainlit turn, not this single ``invoke``.)
"""

import argparse
import logging


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Run one recipe-driven agent turn.")
    parser.add_argument(
        "query", nargs="?", default="What is the Acceptable Intake for NDMA?"
    )
    parser.add_argument("--recipe", default=None, help="recipe name (default: registry default)")
    args = parser.parse_args()

    from harness.indexing import load_index_profile, open_index
    from harness.obs import default_experiment, setup_tracing
    from harness.recipes import build_recipe, default_recipe_name, get_recipe

    # Same experiment resolver as the live app (EMA_MLFLOW_EXPERIMENT env) so demo
    # traces + assessments land next to the UI's (F15).
    setup_tracing(default_experiment())
    recipe = get_recipe(args.recipe or default_recipe_name())
    logging.info("recipe=%s index_profile=%s", recipe.name, recipe.index_profile)

    index = open_index(load_index_profile(recipe.index_profile))
    runner = build_recipe(recipe, index)
    result = runner.invoke({"question": args.query, "source": "demo"})
    answer = result["answer"]

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
