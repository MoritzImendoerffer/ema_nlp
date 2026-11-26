#!/usr/bin/env bash
# Build the parse environment of backlog row 17: Docling, PaddleOCR-VL and RapidOCR.
#
# It lives at config.DOCLING_ENV (default ~/.local/share/ema_nlp/envs/docling), never in
# .venv: Docling 2.153.0 pulls torch 2.15.0, and .venv holds torch 2.10.0 under the
# embedding model (exploration of work unit 28, section 7).
#
# Steps: a Python 3.12 environment with uv; the frozen package set of
# requirements/parse-docling.lock.txt; this repository with --no-deps (the parser code,
# config.py); then the three models, at pinned revisions, with their SHA-256 printed:
#   - Heron layout          docling-project/docling-layout-heron @ 8f39ad3c0b4c58e9c2d2c84a38465abf757272d8
#   - PaddleOCR-VL-1.6      PaddlePaddle/PaddleOCR-VL-1.6        @ c5630abae1d940eafe0697512a0325494b02ab42
#   - the OCR models: the PP-OCRv6 files ship in the rapidocr wheel. A recognition model that
#     is not in the wheel (RapidOCR fetches it from modelscope.cn) is fetched by the parser's
#     prefetch (corpus/parsers/docling_pdf.py), which builds the converter once with the
#     batch's options, so a batch never downloads
# Re-running it is safe: uv reinstalls nothing that is already at the pinned version.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_DIR="$("$REPO/.venv/bin/python" -c 'import sys; sys.path.insert(0, "'"$REPO"'"); import config; print(config.DOCLING_ENV)')"

if [ "$(cd "$ENV_DIR" 2>/dev/null && pwd)" = "$REPO/.venv" ]; then
  echo "refusing: config.DOCLING_ENV points at .venv" >&2
  exit 1
fi

echo "parse environment: $ENV_DIR"
mkdir -p "$(dirname "$ENV_DIR")"
[ -x "$ENV_DIR/bin/python" ] || uv venv -q -p 3.12 "$ENV_DIR"
uv pip install -q -p "$ENV_DIR/bin/python" -r "$REPO/requirements/parse-docling.lock.txt"
uv pip install -q -p "$ENV_DIR/bin/python" --no-deps -e "$REPO"
uv pip install -q -p "$ENV_DIR/bin/python" pytest mongomock  # for make test-parse

"$ENV_DIR/bin/python" - <<'EOF'
import hashlib
from pathlib import Path

from huggingface_hub import snapshot_download

PINS = {
    "docling-project/docling-layout-heron": "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8",
    "PaddlePaddle/PaddleOCR-VL-1.6": "c5630abae1d940eafe0697512a0325494b02ab42",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


for repo, rev in PINS.items():
    folder = Path(snapshot_download(repo, revision=rev))
    weights = sorted(p for p in folder.rglob("*") if p.suffix in (".safetensors", ".bin", ".pt"))
    for w in weights:
        print(f"{repo}@{rev[:12]} {w.name} sha256={sha256(w)[:16]}")

models = Path(__import__("rapidocr").__file__).parent / "models"
for f in sorted(models.glob("*.onnx")):
    print(f"rapidocr {f.name} sha256={sha256(f)[:16]}")
EOF

echo "check: .venv keeps its own torch and has no docling"
"$REPO/.venv/bin/python" -c 'import torch; print(".venv torch", torch.__version__)'
if "$REPO/.venv/bin/python" -c 'import docling' 2>/dev/null; then
  echo "ERROR: docling is importable in .venv" >&2
  exit 1
fi
"$ENV_DIR/bin/python" -c 'import docling, torch; from importlib.metadata import version; print("parse env docling", version("docling"), "torch", torch.__version__, "cuda", torch.cuda.is_available())'
