"""
Sync GitHub issues with the current implementation plan (state.json).

Actions performed:
  - CLOSE issues for completed tasks (TASK-001–006)
  - CREATE new issues that don't exist yet (TASK-007A, TASK-007B, TASK-016.5, TASK-027.5–027.9, INFRA)
  - UPDATE title + body of all open issues → lightweight format (link to plan, no duplicated spec)

Usage:
    GITHUB_TOKEN=ghp_xxx python3 scripts/sync_github_issues.py [--dry-run]

Get a token at: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
Required permissions: Issues (read/write), Metadata (read)
"""

from __future__ import annotations

import os
import sys
import time

try:
    from github import Github, GithubException
except ImportError:
    print("PyGithub not installed. Run: pip install PyGithub")
    sys.exit(1)

# Re-use canonical issue definitions from create_github_issues.py
sys.path.insert(0, os.path.dirname(__file__))
from create_github_issues import ISSUES, LABELS  # noqa: E402

REPO_NAME = "MoritzImendoerffer/ema_nlp"
DRY_RUN = "--dry-run" in sys.argv

# ---------------------------------------------------------------------------
# Tasks to CLOSE (completed)
# ---------------------------------------------------------------------------

COMPLETED_TITLES = {
    "[TASK-001] MongoDB Q&A inventory query",
    "[TASK-002] Topic stratification + cross-ref chain completeness",
    "[TASK-003] Go/no-go decision notebook",
    "[TASK-004] Project setup — pyproject.toml, directory structure, schema docs",
    "[TASK-005] HTML accordion extractor",
    "[TASK-006] PDF Q&A extractor",
}

# ---------------------------------------------------------------------------
# Title renames  {old_title: new_title}
# Applied before the body-update pass so lookups use the new title.
# ---------------------------------------------------------------------------

RENAMES = {
    "[TASK-007] Deduplication + landing page filter + corpus writer":
        "[TASK-007] MongoDB adaptor — feeds build_corpus from ema_scraper.web_items",
}

# ---------------------------------------------------------------------------
# Build lookup maps from canonical ISSUES list
# ---------------------------------------------------------------------------

# title → (labels, body)  for everything in the canonical list
_CANONICAL: dict[str, tuple[list, str]] = {title: (lbls, body) for title, lbls, body in ISSUES}

# Titles that are new (don't exist on GitHub yet)
# Everything not in the original 35 issues (TASK-001..035) is treated as new.
_ORIGINAL_TITLES = {
    "[INFRA] Create ~/.myenvs/ema_nlp.env with all required credentials",
    "[TASK-007A] build_corpus.py — pure dedup/filter/write logic (no MongoDB)",
    "[TASK-007B] Mini-corpus HTTP fetcher — ~100 real Q&As without MongoDB",
    "[TASK-016.5] IDMP ontology concept tagging — node metadata",
    "[TASK-027.5] Query cache — FAISS index over past query embeddings",
    "[TASK-027.6] Semantic cache CLI — similarity lookup + user confirmation",
    "[TASK-027.7] Runtime few-shot injection — top-k rated trajectories in agent prompt",
    "[TASK-027.8] CLI rating UI + Phoenix annotation posting",
    "[TASK-027.9] JSONL export from Phoenix rated traces",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    prefix = "[DRY-RUN] " if DRY_RUN else ""
    print(prefix + msg)


def ensure_labels(repo) -> None:
    existing = {lbl.name for lbl in repo.get_labels()}
    for name, color, description in LABELS:
        if name not in existing:
            log(f"  Creating label: {name}")
            if not DRY_RUN:
                repo.create_label(name=name, color=color, description=description)


def get_label_obj(repo, name: str):
    try:
        return repo.get_label(name)
    except GithubException:
        return None


def sync(repo) -> None:
    ensure_labels(repo)

    # Load all issues (open + closed) keyed by current title
    all_issues: dict[str, object] = {i.title: i for i in repo.get_issues(state="all")}

    # ── 1. Close completed issues ──────────────────────────────────────────
    print("\n=== Closing completed issues ===")
    for title in sorted(COMPLETED_TITLES):
        issue = all_issues.get(title)
        if issue is None:
            log(f"  NOT FOUND (skip close): {title}")
            continue
        if issue.state == "closed":
            print(f"  Already closed: #{issue.number} {title}")
            continue
        log(f"  Closing #{issue.number}: {title}")
        if not DRY_RUN:
            issue.edit(state="closed")
            time.sleep(0.3)

    # ── 2. Apply title renames ─────────────────────────────────────────────
    print("\n=== Renaming issues ===")
    for old_title, new_title in RENAMES.items():
        issue = all_issues.get(old_title)
        if issue is None:
            # Maybe already renamed
            if new_title in all_issues:
                print(f"  Already renamed: {new_title}")
            else:
                log(f"  NOT FOUND (skip rename): {old_title}")
            continue
        log(f"  Renaming #{issue.number}: {old_title!r} → {new_title!r}")
        if not DRY_RUN:
            issue.edit(title=new_title)
            # Update our lookup map so subsequent passes use the new title
            all_issues[new_title] = issue
            del all_issues[old_title]
            time.sleep(0.3)

    # ── 3. Create new issues ───────────────────────────────────────────────
    print("\n=== Creating new issues ===")
    for title in _ORIGINAL_TITLES:
        if title in all_issues:
            print(f"  Already exists: {title}")
            continue
        label_names, body = _CANONICAL[title]
        labels = [lbl for name in label_names if (lbl := get_label_obj(repo, name))]
        log(f"  Creating: {title}")
        if not DRY_RUN:
            issue = repo.create_issue(title=title, body=body, labels=labels)
            print(f"    → #{issue.number}")
            time.sleep(0.5)

    # ── 4. Update bodies of all open issues to lightweight format ──────────
    print("\n=== Updating issue bodies to lightweight format ===")
    for title, (_, new_body) in _CANONICAL.items():
        if title in COMPLETED_TITLES:
            continue  # closed, skip
        issue = all_issues.get(title)
        if issue is None:
            # Might be a new issue just created (we don't have its object yet)
            # or a rename target. Either way, skip the body update — it was
            # created/renamed with the correct body already.
            continue
        if issue.state == "closed":
            continue
        current_body = (issue.body or "").strip()
        if current_body == new_body.strip():
            print(f"  Body unchanged: #{issue.number} {title}")
            continue
        log(f"  Updating body: #{issue.number} {title}")
        if not DRY_RUN:
            issue.edit(body=new_body)
            time.sleep(0.3)

    print("\nSync complete.")
    print(f"View issues at: https://github.com/{REPO_NAME}/issues")


def main() -> None:
    if DRY_RUN:
        print("=== DRY RUN — no changes will be made ===\n")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable not set.")
        print()
        print("Run: GITHUB_TOKEN=ghp_xxx python3 scripts/sync_github_issues.py")
        sys.exit(1)

    from github import Auth
    g = Github(auth=Auth.Token(token))
    try:
        repo = g.get_repo(REPO_NAME)
        print(f"Connected to: {repo.full_name}")
    except GithubException as e:
        print(f"Error accessing repo: {e}")
        sys.exit(1)

    sync(repo)


if __name__ == "__main__":
    main()
