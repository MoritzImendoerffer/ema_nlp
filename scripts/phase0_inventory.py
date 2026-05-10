"""
Phase 0 — Q&A content inventory.

Queries ema_scraper.web_items for:
  (a) HTML pages with accordion Q&A structure
  (b) PDF documents in Q&A-relevant document categories

Outputs:
  scripts/phase0_inventory.csv   — one row per source
  (counts also printed to stdout)

Human-regulatory only: veterinary and non-EMA URLs are excluded.
"""

import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from pymongo import MongoClient

# Allow running from scripts/ or project root
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
import config

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MONGO_URI = config.MONGO_URI
MONGO_DB = config.MONGO_DB
MONGO_COL = config.MONGO_COL

OUTPUT_CSV = Path(__file__).parent / "phase0_inventory.csv"

# URL segments that mark veterinary or non-human content
EXCLUDE_URL_SEGMENTS = [
    "veterinary",
    "vet-",
    "-vet-",
    "/vet/",
    "animal-health",
]

# URL segments that confirm human-regulatory relevance for HTML pages
HUMAN_REG_URL_SEGMENTS = [
    "/en/human-regulatory",
    "/en/research-development",
    "/en/post-authorisation",
    "/en/documents/scientific-guideline",
    "/en/documents/regulatory-procedural-guideline",
    "/en/documents/opinion-any-scientific-matter",
    "/en/documents/other",          # some cross-cutting Q&A docs live here
    "/en/documents/medicine-qa",    # included for reference count (largely product-specific)
]

# PDF URL categories to include as Q&A sources
PDF_QA_CATEGORIES = [
    "scientific-guideline",
    "regulatory-procedural-guideline",
    "opinion-any-scientific-matter",
]

# PDF URL must contain one of these to count as a Q&A document
PDF_QA_KEYWORDS = [
    "questions-and-answers",
    "questions-answers",
    "q-and-a",
    "question-and-answer",
    "question-answers",
    "qa-",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_url(doc) -> str:
    u = doc.get("url", "")
    return u[0] if isinstance(u, list) else u


def get_content_type(doc) -> str:
    ct = doc.get("content_type", "")
    return (ct[0] if isinstance(ct, list) else ct).lower()


def get_html(doc) -> str:
    h = doc.get("html_raw", "")
    return h[0] if isinstance(h, list) else h


def is_excluded(url: str) -> bool:
    url_l = url.lower()
    return any(seg in url_l for seg in EXCLUDE_URL_SEGMENTS)


def derive_topic_path(url: str) -> str:
    """Extract a human-readable topic breadcrumb from the URL."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p and p not in ("en",)]
    # Remove file extensions and long hashes at the end
    if parts and "." in parts[-1]:
        parts = parts[:-1]
    # Truncate to 4 segments max for readability
    return "/" + "/".join(parts[:5])


def extract_html_revision_date(soup: BeautifulSoup) -> str:
    """Try to find the most recent revision date from accordion text.

    EMA accordion items frequently include 'Rev. Mon YYYY' in the heading.
    """
    # Find all revision markers in the page
    rev_pattern = re.compile(r"Rev\.?\s+([A-Z][a-z]+\s+\d{4}|\w{3}[\s.]\d{4})", re.IGNORECASE)
    dates = rev_pattern.findall(soup.get_text())
    if not dates:
        return ""
    # Return the lexicographically last (most recent) date string
    return dates[-1].strip()


def count_html_accordions(soup: BeautifulSoup) -> int:
    """Count individual Q&A accordion items (EMA uses class='accordion-item')."""
    items = soup.find_all(class_="accordion-item")
    return len(items)


# ---------------------------------------------------------------------------
# Main inventory logic
# ---------------------------------------------------------------------------

def build_inventory() -> list[dict]:
    client = MongoClient(MONGO_URI)
    col = client[MONGO_DB][MONGO_COL]

    rows: list[dict] = []
    html_total = 0
    html_accordion_qa = 0
    pdf_total = 0
    pdf_qa = 0

    print("Scanning HTML pages for accordion Q&A...", flush=True)
    for doc in col.find({"content_type": "text/html", "html_raw": {"$exists": True}}):
        url = get_url(doc)
        if is_excluded(url):
            continue
        html_total += 1

        html = get_html(doc)
        if "accordion" not in html:
            continue

        soup = BeautifulSoup(html, "lxml")
        n_accordions = count_html_accordions(soup)
        if n_accordions == 0:
            continue

        # Only keep pages that look like Q&A guides (not generic navigation pages)
        page_text = soup.get_text().lower()
        has_qa_signal = (
            "questions" in url.lower()
            or "q-and-a" in url.lower()
            or "guidance" in url.lower()
            or n_accordions >= 5  # pages with ≥5 accordion items are likely Q&A
        )
        if not has_qa_signal:
            continue

        # Require human-regulatory URL scope
        is_human_reg = any(seg in url for seg in HUMAN_REG_URL_SEGMENTS)
        if not is_human_reg:
            continue

        html_accordion_qa += 1
        rev_date = extract_html_revision_date(soup)
        rows.append(
            {
                "url": url,
                "type": "html",
                "topic_path": derive_topic_path(url),
                "q_count_estimate": n_accordions,
                "last_updated": rev_date,
                "revision_number": "",  # only available in PDFs
                "notes": "",
            }
        )

    print(f"  HTML pages scanned: {html_total}")
    print(f"  HTML accordion Q&A pages found: {html_accordion_qa}")

    print("Scanning PDFs for Q&A documents...", flush=True)
    for doc in col.find({"content_type": "application/pdf"}):
        url = get_url(doc)
        if is_excluded(url):
            continue
        pdf_total += 1

        url_lower = url.lower()
        in_qa_category = any(cat in url_lower for cat in PDF_QA_CATEGORIES)
        has_qa_keyword = any(kw in url_lower for kw in PDF_QA_KEYWORDS)

        if not (in_qa_category and has_qa_keyword):
            continue

        # Broad human/scientific scope — not species-specific vet docs
        if "veterinary" in url_lower or "-vet-" in url_lower:
            continue

        pdf_qa += 1
        rows.append(
            {
                "url": url,
                "type": "pdf",
                "topic_path": derive_topic_path(url),
                "q_count_estimate": "",   # needs Phase 1 PDF extractor to count
                "last_updated": "",       # needs PDF parsing
                "revision_number": "",    # needs PDF parsing
                "notes": "PDF — q_count and dates require Phase 1 extractor",
            }
        )

    print(f"  PDFs scanned: {pdf_total}")
    print(f"  Q&A PDFs found: {pdf_qa}")

    client.close()
    return rows


def print_summary(rows: list[dict]) -> None:
    html_rows = [r for r in rows if r["type"] == "html"]
    pdf_rows  = [r for r in rows if r["type"] == "pdf"]
    total_est = sum(int(r["q_count_estimate"]) for r in html_rows if r["q_count_estimate"])

    print()
    print("=" * 60)
    print("INVENTORY SUMMARY")
    print("=" * 60)
    print(f"Total sources found:          {len(rows)}")
    print(f"  HTML accordion Q&A pages:   {len(html_rows)}")
    print(f"  Q&A PDFs:                   {len(pdf_rows)}")
    print()
    print(f"Estimated Q&A pairs from HTML: {total_est:,}")
    print(f"PDF Q&A count:                 TBD (Phase 1 extractor needed)")
    print()

    # Topic path distribution
    from collections import Counter
    topic_counts = Counter(r["topic_path"][:60] for r in rows)
    print("Topic path distribution (top 20):")
    for topic, count in topic_counts.most_common(20):
        print(f"  {count:3d}  {topic}")
    print()

    # Human-regulatory URL overlap check
    human_reg = [
        r for r in rows
        if "/en/human-regulatory" in r["url"] or "/en/research-development" in r["url"]
        or "/en/post-authorisation" in r["url"]
    ]
    print(f"Confirmed human-regulatory-tree URLs: {len(human_reg)}")
    print()

    # Go/no-go signal
    if len(rows) >= 20 and total_est >= 100:
        print("✅ GO SIGNAL: sufficient Q&A sources found for Phase 1.")
    else:
        print("⚠️  SCOPE RISK: too few sources — review before Phase 1.")
    print("=" * 60)


def write_csv(rows: list[dict], path: Path) -> None:
    fieldnames = ["url", "type", "topic_path", "q_count_estimate", "last_updated", "revision_number", "notes"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV written to: {path}")


if __name__ == "__main__":
    rows = build_inventory()
    print_summary(rows)
    write_csv(rows, OUTPUT_CSV)
