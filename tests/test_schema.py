"""Smoke tests: schema files exist and example records are valid JSON."""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_corpus_schema_exists() -> None:
    assert (ROOT / "corpus" / "SCHEMA.md").exists()


def test_benchmark_schema_exists() -> None:
    assert (ROOT / "benchmark" / "SCHEMA.md").exists()


def test_corpus_example_record_is_valid_json() -> None:
    schema = (ROOT / "corpus" / "SCHEMA.md").read_text()
    # Extract the JSON block from the schema
    start = schema.index("```json\n") + len("```json\n")
    end = schema.index("\n```", start)
    record = json.loads(schema[start:end])
    required = {"qa_id", "question", "answer", "source_url", "source_type",
                "source_title", "topic_path", "cross_refs", "extraction_confidence"}
    assert required <= set(record.keys())


def test_benchmark_example_record_is_valid_json() -> None:
    schema = (ROOT / "benchmark" / "SCHEMA.md").read_text()
    start = schema.index("```json\n") + len("```json\n")
    end = schema.index("\n```", start)
    record = json.loads(schema[start:end])
    required = {"bench_id", "question", "paraphrases", "type", "gold_answer",
                "gold_qa_ids", "gold_sources", "topic_path"}
    assert required <= set(record.keys())
    assert isinstance(record["paraphrases"], list)
    assert record["type"] in {"T1", "T2", "T3", "T4"}
