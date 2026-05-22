"""
Human-in-the-loop (HITL) annotation utilities.

This package provides tooling for exporting Phoenix span annotations to the
shared Nextcloud JSONL store and loading them back as few-shot examples.

Key constraints:
- Annotation data is NEVER stored in this repository.
  All output is written to ~/Nextcloud/Datasets/ema_nlp/annotations/.
- Scripts in this package communicate with the Phoenix REST API.
  Phoenix must be running (locally or via Tailscale) before any export.

Modules:
  export_annotations  — query Phoenix, write per-date JSONL to Nextcloud
"""
