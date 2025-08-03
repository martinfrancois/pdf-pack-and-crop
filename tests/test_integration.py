from pathlib import Path
import tempfile
import pytest

fitz = pytest.importorskip('fitz')
if getattr(fitz, '__is_stub__', False):
    pytest.skip('fitz stubbed', allow_module_level=True)

import pack_and_crop as cp


def make_pdf(path: Path):
    doc = fitz.open()
    doc.new_page(width=100, height=100)
    doc.save(path)


def test_full_flow(tmp_path):
    pdf1 = tmp_path / 'a.pdf'
    pdf2 = tmp_path / 'b.pdf'
    make_pdf(pdf1)
    make_pdf(pdf2)

    output = tmp_path / 'out.pdf'
    page_w, page_h = cp.parse_pagesize('A4')
    margin_pt = cp.mm_to_pt(5)
    spacing_pt = cp.mm_to_pt(5)
    eff_w = page_w - 2 * margin_pt
    eff_h = page_h - 2 * margin_pt

    with tempfile.TemporaryDirectory() as td:
        items = cp.crop_pages([pdf1, pdf2], td, 72, 250)
        pk, rot = cp.find_minimal_packing(items, eff_w, eff_h, spacing_pt)
        cp.render_pdf(pk, items, page_w, page_h, margin_pt, spacing_pt, rot, str(output))

    out = fitz.open(output)
    assert out.page_count >= 1

