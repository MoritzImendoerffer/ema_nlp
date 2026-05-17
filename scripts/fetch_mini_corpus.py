"""
Fetch a small set of EMA Q&A pages directly from ema.europa.eu and write
corpus/mini_corpus.jsonl without needing a MongoDB connection.

This is a development fixture for offline work.  It is NOT a substitute for
the full corpus produced by TASK-008 (which needs MongoDB).

Usage:
    python3 scripts/fetch_mini_corpus.py [--output PATH]

The script is idempotent — re-running overwrites mini_corpus.jsonl.
HTTP errors on individual pages are logged and skipped (not fatal).
A 1-second polite delay is inserted between requests.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import httpx

from corpus.build_corpus import build_corpus
from corpus.extractors.html_extractor import extract_from_html

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
INVENTORY_CSV = REPO_ROOT / "scripts" / "phase0_inventory.csv"
DEFAULT_OUTPUT = REPO_ROOT / "corpus" / "mini_corpus.jsonl"

# 10 curated HTML URLs spanning at least 3 distinct topic_path prefixes.
# Selected to give broad coverage: safety/quality, post-authorisation, herbal,
# medical devices, referral procedures.
CURATED_URLS = [
    # Herbal medicines
    "https://www.ema.europa.eu/en/human-regulatory-overview/herbal-medicinal-products/"
    "herbal-medicinal-products-questions-answers",
    # Medical devices
    "https://www.ema.europa.eu/en/human-regulatory-overview/medical-devices/"
    "consultation-procedure-ancillary-medicinal-substances-medical-devices",
    # Variations — post-authorisation
    "https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/"
    "variations-including-extensions-marketing-authorisations/"
    "variations-regulation-regulatory-procedural-guidance/type-ia-variations-questions-answers",
    "https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/"
    "variations-including-extensions-marketing-authorisations/worksharing-questions-answers",
    "https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/"
    "variations-including-extensions-marketing-authorisations/"
    "extensions-marketing-authorisations-questions-answers",
    # Referral procedures
    "https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/"
    "referral-procedures-human-medicines/questions-answers-article-31-non-pharmacovigilance-referrals",
    "https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/"
    "referral-procedures-human-medicines/questions-answers-article-30-referral-procedures",
    # Pharmacovigilance
    "https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/"
    "referral-procedures-human-medicines/questions-answers-article-31-pharmacovigilance-referrals",
    # Orphan medicines
    "https://www.ema.europa.eu/en/human-regulatory-overview/orphan-designation/"
    "orphan-designation-questions-answers",
    # Biosimilar / scientific advice  (broad coverage)
    "https://www.ema.europa.eu/en/human-regulatory-overview/research-development/"
    "scientific-advice-protocol-assistance/scientific-advice-questions-answers",
]

HEADERS = {
    "User-Agent": (
        "ema-nlp-research-bot/0.1 "
        "(academic NLP project; contact moritz.imend@gmail.com)"
    )
}


def fetch_url(client: httpx.Client, url: str) -> str | None:
    try:
        resp = client.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as e:
        log.warning("HTTP %s for %s — skipping", e.response.status_code, url)
    except httpx.RequestError as e:
        log.warning("Request error for %s: %s — skipping", url, e)
    return None


def main(output: Path = DEFAULT_OUTPUT) -> None:
    all_records = []

    with httpx.Client(headers=HEADERS) as client:
        for i, url in enumerate(CURATED_URLS):
            log.info("[%d/%d] Fetching %s", i + 1, len(CURATED_URLS), url)
            html = fetch_url(client, url)
            if html is None:
                continue

            records = extract_from_html(html, url)
            log.info("  → %d Q&A records extracted", len(records))
            all_records.extend(records)

            if i < len(CURATED_URLS) - 1:
                time.sleep(1.0)

    if not all_records:
        log.error("No records fetched — check network connectivity.")
        raise SystemExit(1)

    stats = build_corpus(
        all_records,
        output,
        dedup_log_path=output.with_name(output.stem + "_dedup_log.jsonl"),
        filter_log_path=output.with_name(output.stem + "_filter_log.jsonl"),
    )

    log.info(
        "\nMini-corpus written: %d records across %d topic paths → %s",
        stats.total_output,
        len(stats.by_topic_path),
        output,
    )
    log.info("By source type:  %s", stats.by_source_type)
    log.info("By topic path:")
    for path, count in sorted(stats.by_topic_path.items()):
        log.info("  %-60s %d", path, count)

    if stats.total_output < 80:
        log.warning(
            "Mini-corpus has only %d records (target ≥80). "
            "Some URLs may have failed or returned few Q&As.",
            stats.total_output,
        )
    if len(stats.by_topic_path) < 3:
        log.warning(
            "Mini-corpus covers only %d topic paths (target ≥3).",
            len(stats.by_topic_path),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSONL path (default: corpus/mini_corpus.jsonl)",
    )
    args = parser.parse_args()
    main(args.output)
