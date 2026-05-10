"""
Generate scripts/phase0_scope_decision.ipynb for TASK-003.
Run once — after that, open the notebook, run all cells, fill the Decision cell.
"""
import json
from pathlib import Path

NOTEBOOK_PATH = Path(__file__).parent / "phase0_scope_decision.ipynb"

# Each cell is (cell_type, source_lines, metadata)
CELLS = [
    # ── title ──
    ("markdown", [
        "# Phase 0 Scope Decision\n",
        "\n",
        "**Purpose:** Visualise the inventory + stratification data from TASK-001/002 "
        "and record the Go / No-Go decision.\n",
        "\n",
        "**Instructions:**\n",
        "1. Run all cells (Kernel → Restart & Run All)\n",
        "2. Scroll to the **Decision** cell at the bottom\n",
        "3. Replace the placeholder text with your decision and rationale\n",
        "4. Save the notebook and commit it (`git add scripts/phase0_scope_decision.ipynb && git commit -m 'TASK-003: Go/no-go decision'`)\n",
    ], {}),

    # ── imports ──
    ("code", [
        "import csv, sys\n",
        "from pathlib import Path\n",
        "from collections import defaultdict\n",
        "\n",
        "import matplotlib.pyplot as plt\n",
        "import matplotlib.patches as mpatches\n",
        "\n",
        "ROOT = Path('..') if Path('../scripts').exists() else Path('.')\n",
        "INV_CSV = ROOT / 'scripts' / 'phase0_inventory.csv'\n",
        "\n",
        "rows = list(csv.DictReader(INV_CSV.open()))\n",
        "html_rows = [r for r in rows if r['type'] == 'html']\n",
        "pdf_rows  = [r for r in rows if r['type'] == 'pdf']\n",
        "print(f'Loaded {len(rows)} rows ({len(html_rows)} HTML, {len(pdf_rows)} PDF)')\n",
    ], {}),

    # ── fig 1: source counts ──
    ("markdown", ["## Figure 1 — Source counts\n"], {}),
    ("code", [
        "fig, ax = plt.subplots(figsize=(6, 3))\n",
        "labels = ['HTML accordion\\nQ&A pages', 'Q&A PDFs', 'Total']\n",
        "values = [len(html_rows), len(pdf_rows), len(rows)]\n",
        "colors = ['#4c72b0', '#dd8452', '#55a868']\n",
        "bars = ax.bar(labels, values, color=colors, edgecolor='white')\n",
        "for bar, val in zip(bars, values):\n",
        "    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, str(val),\n",
        "            ha='center', va='bottom', fontsize=12, fontweight='bold')\n",
        "ax.set_ylabel('Count')\n",
        "ax.set_title('Phase 0 Source Counts')\n",
        "ax.axhline(20, color='green', linestyle='--', alpha=0.6, label='Min threshold (20)')\n",
        "ax.legend()\n",
        "ax.set_ylim(0, max(values) * 1.15)\n",
        "plt.tight_layout()\n",
        "plt.savefig(str(ROOT / 'scripts' / 'fig1_source_counts.png'), dpi=120)\n",
        "plt.show()\n",
    ], {}),

    # ── fig 2: topic cluster split ──
    ("markdown", ["## Figure 2 — Topic cluster distribution\n"], {}),
    ("code", [
        "CLUSTERS = [\n",
        "    ('COVID-19 & Public Health', ['covid','coronavirus','public-health-threat']),\n",
        "    ('Post-auth: Variations & Extensions', ['variations-including-extensions','worksharing','extensions-marketing','type-ia-variations','type-ib-variations','type-ii-variations','grouping-variations']),\n",
        "    ('Post-auth: Referral Procedures', ['referral-procedures','article-31','article-30','article-13','article-20','article-29','article-107']),\n",
        "    ('Post-auth: Pharmacovigilance & Safety', ['pharmacovigilance','risk-management-plan','post-authorisation-efficacy','post-authorisation-safety']),\n",
        "    ('Post-auth: Other', ['post-authorisation','medicine-shortage','parallel-distribution','transfer-marketing','transparency','renewal','paediatric','orphan']),\n",
        "    ('Research & Dev / Pre-auth', ['research-development','research-and-development','clinical-trial','compliance-research','scientific-guideline']),\n",
        "    ('Safety & Excipients (PDF)', ['nitrosamine','excipient','impurit','genotox','toxic','angiotensin','benzoic','benzyl','sodium-laurilsulfate','nsaid','viral']),\n",
        "    ('Regulatory & Procedural (PDF)', ['regulatory-procedural','ich-','common-technical-document','ctd','eudravigilance','psusa']),\n",
        "    ('Herbal & Traditional Medicines', ['herbal','traditional-herbal']),\n",
        "    ('Medical Devices', ['medical-device','ancillary-medicinal']),\n",
        "]\n",
        "\n",
        "def assign_cluster(url):\n",
        "    u = url.lower()\n",
        "    for name, kws in CLUSTERS:\n",
        "        if any(k in u for k in kws):\n",
        "            return name\n",
        "    return 'Other / Uncategorised'\n",
        "\n",
        "cluster_html = defaultdict(list)\n",
        "cluster_pdf  = defaultdict(list)\n",
        "for r in html_rows: cluster_html[assign_cluster(r['url'])].append(r)\n",
        "for r in pdf_rows:  cluster_pdf[assign_cluster(r['url'])].append(r)\n",
        "all_clusters = sorted(set(cluster_html) | set(cluster_pdf))\n",
        "\n",
        "html_counts = [len(cluster_html.get(c, [])) for c in all_clusters]\n",
        "pdf_counts  = [len(cluster_pdf.get(c, []))  for c in all_clusters]\n",
        "qa_counts   = [sum(int(r['q_count_estimate']) for r in cluster_html.get(c,[]) if r['q_count_estimate']) for c in all_clusters]\n",
        "\n",
        "fig, axes = plt.subplots(1, 2, figsize=(14, 5))\n",
        "\n",
        "# Left: page counts by cluster\n",
        "ax = axes[0]\n",
        "y = range(len(all_clusters))\n",
        "ax.barh(y, html_counts, label='HTML pages', color='#4c72b0')\n",
        "ax.barh(y, pdf_counts, left=html_counts, label='PDF docs', color='#dd8452')\n",
        "ax.set_yticks(list(y))\n",
        "ax.set_yticklabels([c[:35] for c in all_clusters], fontsize=8)\n",
        "ax.set_xlabel('Source count')\n",
        "ax.set_title('Sources per topic cluster')\n",
        "ax.legend()\n",
        "\n",
        "# Right: estimated Q&A pairs per cluster (HTML only)\n",
        "ax = axes[1]\n",
        "colors = ['#c44e52' if q < 5 else '#55a868' for q in qa_counts]\n",
        "ax.barh(list(y), qa_counts, color=colors)\n",
        "ax.set_yticks(list(y))\n",
        "ax.set_yticklabels([c[:35] for c in all_clusters], fontsize=8)\n",
        "ax.set_xlabel('Estimated Q&A pairs')\n",
        "ax.set_title('Estimated Q&A pairs per cluster (HTML)')\n",
        "thin = mpatches.Patch(color='#c44e52', label='Thin (<5 Q&A pairs)')\n",
        "ok   = mpatches.Patch(color='#55a868', label='Viable (≥5 Q&A pairs)')\n",
        "ax.legend(handles=[ok, thin])\n",
        "\n",
        "plt.tight_layout()\n",
        "plt.savefig(str(ROOT / 'scripts' / 'fig2_topic_clusters.png'), dpi=120)\n",
        "plt.show()\n",
    ], {}),

    # ── fig 3: chain completeness ──
    ("markdown", ["## Figure 3 — Cross-reference chain completeness\n"], {}),
    ("code", [
        "# Hardcoded from phase0_topic_report.py output\n",
        "xref_data = {\n",
        "    'Pages with cross-refs': 25,\n",
        "    'Pages without cross-refs': 64 - 25,\n",
        "    'Total link xrefs': 39,\n",
        "    'In-corpus link xrefs': 17,\n",
        "    'Out-of-corpus link xrefs': 39 - 17,\n",
        "}\n",
        "\n",
        "fig, axes = plt.subplots(1, 2, figsize=(10, 4))\n",
        "\n",
        "ax = axes[0]\n",
        "ax.pie(\n",
        "    [xref_data['Pages with cross-refs'], xref_data['Pages without cross-refs']],\n",
        "    labels=['Has cross-refs\\n(25)', 'No cross-refs\\n(39)'],\n",
        "    colors=['#4c72b0', '#cccccc'],\n",
        "    autopct='%1.0f%%', startangle=90\n",
        ")\n",
        "ax.set_title('HTML pages with cross-references')\n",
        "\n",
        "ax = axes[1]\n",
        "completeness = xref_data['In-corpus link xrefs'] / xref_data['Total link xrefs'] * 100\n",
        "ax.bar(['In-corpus', 'Out-of-corpus'],\n",
        "       [xref_data['In-corpus link xrefs'], xref_data['Out-of-corpus link xrefs']],\n",
        "       color=['#55a868', '#c44e52'])\n",
        "ax.set_ylabel('Hyperlink cross-references')\n",
        "ax.set_title(f'Chain completeness: {completeness:.1f}%')\n",
        "for i, v in enumerate([xref_data['In-corpus link xrefs'], xref_data['Out-of-corpus link xrefs']]):\n",
        "    ax.text(i, v + 0.3, str(v), ha='center', fontweight='bold')\n",
        "\n",
        "plt.tight_layout()\n",
        "plt.savefig(str(ROOT / 'scripts' / 'fig3_chain_completeness.png'), dpi=120)\n",
        "plt.show()\n",
        "print(f'Chain completeness: {completeness:.1f}% ({xref_data[\"In-corpus link xrefs\"]}/{xref_data[\"Total link xrefs\"]} links target in-corpus pages)')\n",
    ], {}),

    # ── go/no-go criteria summary ──
    ("markdown", ["## Phase 0 acceptance criteria\n"], {}),
    ("code", [
        "total_qa = sum(int(r['q_count_estimate']) for r in html_rows if r['q_count_estimate'])\n",
        "n_clusters = 11  # from phase0_topic_report.py\n",
        "chain_pct  = 43.6\n",
        "\n",
        "criteria = [\n",
        "    ('Total sources ≥ 20', len(rows) >= 20, f'{len(rows)} sources'),\n",
        "    ('Estimated Q&A pairs ≥ 100', total_qa >= 100, f'{total_qa:,} pairs'),\n",
        "    ('Distinct topic clusters ≥ 3', n_clusters >= 3, f'{n_clusters} clusters'),\n",
        "    ('Chain completeness documented', True, f'{chain_pct}%'),\n",
        "]\n",
        "\n",
        "print('Phase 0 acceptance criteria')\n",
        "print('-' * 60)\n",
        "all_pass = True\n",
        "for desc, passed, detail in criteria:\n",
        "    icon = '✅' if passed else '❌'\n",
        "    print(f'  {icon}  {desc:<45} {detail}')\n",
        "    if not passed: all_pass = False\n",
        "print('-' * 60)\n",
        "print(f'  All criteria met: {\"✅ YES\" if all_pass else \"❌ NO\"}')\n",
    ], {}),

    # ── Decision cell ──
    ("markdown", [
        "---\n",
        "\n",
        "## ✏️ DECISION  ← Fill this in\n",
        "\n",
        "> **Owner: SME (you)**  \n",
        "> Replace the placeholder below with your decision and rationale, then commit.\n",
        "\n",
        "**Decision: `GO` / `NO-GO`** ← replace with one of these\n",
        "\n",
        "**Rationale:**\n",
        "```\n",
        "[Write 2–5 sentences here:\n",
        " - Are the source counts sufficient?\n",
        " - Are the topic clusters representative of EMA human-regulatory Q&A?\n",
        " - Is the chain completeness acceptable?\n",
        " - Any scope changes before Phase 1?]\n",
        "```\n",
        "\n",
        "**Date:**  \n",
        "\n",
        "---\n",
        "\n",
        "*After filling in this cell, run:*\n",
        "```bash\n",
        "git add scripts/phase0_scope_decision.ipynb\n",
        "git commit -m 'TASK-003: Phase 0 go/no-go decision — GO'\n",
        "```\n",
        "*(Nothing in Phase 1 starts until this commit exists with a GO decision.)*\n",
    ], {}),
]


def make_cell(cell_type: str, source: list[str], metadata: dict) -> dict:
    base = {
        "cell_type": cell_type,
        "metadata": metadata,
        "source": source,
    }
    if cell_type == "code":
        base["execution_count"] = None
        base["outputs"] = []
    return base


def build_notebook() -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.11.0",
            },
        },
        "cells": [make_cell(*args) for args in CELLS],
    }


if __name__ == "__main__":
    nb = build_notebook()
    NOTEBOOK_PATH.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Notebook written to: {NOTEBOOK_PATH}")
    print("Open it in JupyterLab/VSCode, run all cells, then fill the Decision cell.")
