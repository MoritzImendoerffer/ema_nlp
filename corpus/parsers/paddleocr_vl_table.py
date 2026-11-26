"""PaddleOCR-VL-1.6 as Docling's table-structure stage (backlog row 17).

Docling finds a table stage through its table-structure factory. This module registers the
stage in code (:func:`register`), so no package entry point is needed; Docling 2.153.0 accepts
it with ``allow_external_plugins=True`` on the pipeline options.

For each table (and table of contents) that the layout model found on a page, the stage crops
the region at 200 DPI and asks the model for the table in OTSL, Docling's table markup. The
model reads cells from the picture, so a cell has no box of its own. Some cell text comes back
as LaTeX (``\\(\\pm\\)``, ``\\(^{a}\\)``); post-processing turns it into text
(``corpus/parsers/docling_post.py``).

Imported only in the parse environment (``make parse-env``): it imports Docling and torch.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import Cluster, Page, Table, TableStructurePrediction
from docling.datamodel.pipeline_options import BaseTableStructureOptions
from docling.models.base_table_model import BaseTableStructureModel
from docling.models.factories import get_table_structure_factory
from docling.models.utils.hf_model_download import download_hf_model
from docling.utils.accelerator_utils import decide_device
from docling.utils.otsl import parse_otsl_output
from docling.utils.profiling import TimeRecorder
from docling_core.types.doc import DocItemLabel

if TYPE_CHECKING:
    from docling.datamodel.document import ConversionResult
    from PIL.Image import Image

_log = logging.getLogger(__name__)

KIND = "ema_paddleocr_vl"
MODEL_REPO = "PaddlePaddle/PaddleOCR-VL-1.6"
MODEL_REVISION = "c5630abae1d940eafe0697512a0325494b02ab42"
DPI = 200
PROMPT = "Table Recognition:"
MAX_NEW_TOKENS = 8192
LONGEST_EDGE = 1280 * 28 * 28  # the model card's pixel budget
TABLE_LABELS = (DocItemLabel.TABLE, DocItemLabel.DOCUMENT_INDEX)


class PaddleOcrVlTableOptions(BaseTableStructureOptions):
    """Selects this stage in Docling's table-structure factory. It has no setting of its own."""

    kind: ClassVar[str] = KIND


class PaddleOcrVlTableModel(BaseTableStructureModel):
    """Reads each table region with PaddleOCR-VL-1.6: bf16 on CUDA, float32 on the CPU."""

    def __init__(
        self,
        enabled: bool,
        artifacts_path: Path | None,
        options: PaddleOcrVlTableOptions,
        accelerator_options: AcceleratorOptions,
        enable_remote_services: bool = False,
    ) -> None:
        self.enabled = enabled
        self.options = options
        if enabled:
            self.device = decide_device(
                accelerator_options.device,
                supported_devices=[AcceleratorDevice.CPU, AcceleratorDevice.CUDA],
            )
            self._load(Path(download_hf_model(repo_id=MODEL_REPO, revision=MODEL_REVISION)))

    @classmethod
    def get_options_type(cls) -> type[PaddleOcrVlTableOptions]:
        return PaddleOcrVlTableOptions

    def _load(self, folder: Path) -> None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        dtype = torch.bfloat16 if self.device.startswith("cuda") else torch.float32
        self._processor = AutoProcessor.from_pretrained(folder)
        self._model = AutoModelForImageTextToText.from_pretrained(folder, dtype=dtype).to(self.device).eval()
        shortest = self._processor.image_processor.size.shortest_edge
        self._size = {"shortest_edge": shortest, "longest_edge": LONGEST_EDGE}

    def predict_tables(
        self, conv_res: ConversionResult, pages: Sequence[Page]
    ) -> Sequence[TableStructurePrediction]:
        predictions = []
        for page in pages:
            if page._backend is None or not page._backend.is_valid() or page.predictions.layout is None:
                prediction = page.predictions.tablestructure or TableStructurePrediction()
                page.predictions.tablestructure = prediction
                predictions.append(prediction)
                continue
            with TimeRecorder(conv_res, "table_structure"):
                prediction = TableStructurePrediction()
                page.predictions.tablestructure = prediction
                for cluster in page.predictions.layout.clusters:
                    if cluster.label in TABLE_LABELS and (table := self._table(page, cluster)):
                        prediction.table_map[cluster.id] = table
            predictions.append(prediction)
        return predictions

    def _table(self, page: Page, cluster: Cluster) -> Table | None:
        """The table read from ``cluster``'s crop; None if the page has no image.

        An answer without OTSL tokens gives a table without cells; the run record counts it.
        """
        image = page.get_image(scale=DPI / 72, cropbox=cluster.bbox)
        if image is None:
            return None
        otsl, cells, rows, cols = parse_otsl_output(self.read(image.convert("RGB")))
        return Table(otsl_seq=otsl, table_cells=cells, num_rows=rows, num_cols=cols, id=cluster.id,
                     page_no=page.page_no, cluster=cluster, label=cluster.label)

    def read(self, image: Image) -> str:
        """The model's answer for one table image."""
        messages = [{"role": "user", "content": [{"type": "image", "image": image},
                                                 {"type": "text", "text": PROMPT}]}]
        inputs = self._processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt",
            processor_kwargs={"images_kwargs": {"size": self._size}},
        ).to(self._model.device)
        # The model repository's configuration turns the generation cache off. Without it every
        # new token recomputes the whole sequence, which made one table 7 to 20 times slower.
        output = self._model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, use_cache=True)
        return self._processor.decode(output[0][inputs["input_ids"].shape[-1] : -1])  # last token ends the turn


def register() -> None:
    """Make the stage known to Docling's table-structure factory (idempotent)."""
    factory = get_table_structure_factory(allow_external_plugins=True)
    if KIND not in getattr(factory, "registered_kind", []):
        try:
            factory.register(PaddleOcrVlTableModel, "ema_nlp", __name__)
        except ValueError as exc:  # already registered under this kind
            _log.debug("table stage already registered: %s", exc)
