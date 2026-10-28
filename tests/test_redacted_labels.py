"""Exercise the CLI with the owner's redacted shipping-label fixtures."""

from collections import Counter
import hashlib
from pathlib import Path
import subprocess
import sys

import pymupdf
import pytest

import pack_and_crop as cp

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "test"
DPI = 300
MARGIN_MM = 5
SPACING_MM = 1
TOLERANCE_PT = 0.5


@pytest.mark.parametrize("numbers, expected_pages", [
    ([1, 5], 1),
    ([1, 2, 3, 4, 5, 6, 8], 6),
    (list(range(1, 12)), None),
])
def test_cli_preserves_redacted_labels(tmp_path, numbers, expected_pages):
    inputs = [LABELS / f"label{number}.pdf" for number in numbers]
    assert all(path.is_file() for path in inputs)
    output = tmp_path / "packed.pdf"
    subprocess.run([
        sys.executable, str(ROOT / "pack_and_crop.py"), *map(str, inputs),
        "--pagesize", "A4", "--page-margin", str(MARGIN_MM),
        "--spacing", str(SPACING_MM), "--dpi", str(DPI),
        "--threshold", "250", "-o", str(output),
    ], check=True, cwd=ROOT)

    # Compare the rendered labels with the crop-stage images to catch dropped,
    # duplicated or altered labels without depending on their placement order.
    crops = tmp_path / "crops"
    crops.mkdir()
    expected_pixels = Counter()
    for path, _, _ in cp.crop_pages(inputs, crops, DPI, 250):
        pix = pymupdf.Pixmap(path)
        expected_pixels[hashlib.sha256(pix.samples).digest()] += 1

    margin = cp.mm_to_pt(MARGIN_MM)
    spacing = cp.mm_to_pt(SPACING_MM)
    actual_pixels = Counter()
    with pymupdf.open(output) as doc:
        if expected_pages is not None:
            assert doc.page_count == expected_pages
        for page in doc:
            assert (page.rect.width, page.rect.height) == pytest.approx(cp.parse_pagesize("A4"), abs=1)
            boxes = []
            for info in page.get_image_info(xrefs=True):
                pix = pymupdf.Pixmap(doc, info["xref"])
                actual_pixels[hashlib.sha256(pix.samples).digest()] += 1
                box = pymupdf.Rect(info["bbox"])
                boxes.append(box)
                assert sorted((box.width, box.height)) == pytest.approx(
                    sorted((pix.width * 72 / DPI, pix.height * 72 / DPI)), abs=TOLERANCE_PT
                )
                assert box.x0 >= margin - TOLERANCE_PT
                assert box.y0 >= margin - TOLERANCE_PT
                assert box.x1 <= page.rect.width - margin + TOLERANCE_PT
                assert box.y1 <= page.rect.height - margin + TOLERANCE_PT
            for index, first in enumerate(boxes):
                for second in boxes[index + 1:]:
                    gap = max(second.x0 - first.x1, first.x0 - second.x1,
                              second.y0 - first.y1, first.y0 - second.y1)
                    assert gap >= spacing - TOLERANCE_PT
    assert sum(actual_pixels.values()) == len(inputs)
    assert actual_pixels == expected_pixels
