from collections import namedtuple
from pathlib import Path
import tempfile

import pymupdf as fitz

import pack_and_crop as cp

MARGIN_MM = 5
SPACING_MM = 5
DPI = 72
WHITE_THRESHOLD = 250

Packed = namedtuple('Packed', 'items packer rotated doc')


def make_pdf(path: Path, width=100, height=100):
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    doc.save(path)


def make_pdfs(tmp_path, count, width=100, height=100):
    paths = [tmp_path / f'in{i}.pdf' for i in range(count)]
    for path in paths:
        make_pdf(path, width=width, height=height)
    return paths


def pack_and_render(pdfs, pagesize, output):
    """Crop, pack and render in the same order as main(), with this module's margin and spacing."""
    page_w, page_h = cp.parse_pagesize(pagesize)
    margin_pt = cp.mm_to_pt(MARGIN_MM)
    spacing_pt = cp.mm_to_pt(SPACING_MM)
    eff_w = page_w - 2 * margin_pt
    eff_h = page_h - 2 * margin_pt

    with tempfile.TemporaryDirectory() as td:
        items = cp.crop_pages(pdfs, td, DPI, WHITE_THRESHOLD)
        pk, rot = cp.find_minimal_packing(items, eff_w, eff_h, spacing_pt)
        cp.render_pdf(pk, items, page_w, page_h, margin_pt, spacing_pt, rot, str(output))

    return Packed(items, pk, rot, fitz.open(output))


def test_full_flow(tmp_path):
    packed = pack_and_render(make_pdfs(tmp_path, 2), 'A4', tmp_path / 'out.pdf')

    assert packed.doc.page_count >= 1


def test_rotation_needed_flow(tmp_path):
    pagesize = '60x120'
    # As wide as the usable sheet, so with spacing added a snippet only fits rotated.
    width = cp.parse_pagesize(pagesize)[0] - 2 * cp.mm_to_pt(MARGIN_MM)
    pdfs = make_pdfs(tmp_path, 2, width=width, height=50)

    packed = pack_and_render(pdfs, pagesize, tmp_path / 'out.pdf')

    assert packed.rotated is True
    assert len(packed.packer.rect_list()) == len(pdfs)
    assert packed.doc.page_count == 1


def test_many_small_pdfs(tmp_path):
    pdfs = make_pdfs(tmp_path, 8, width=50, height=50)

    packed = pack_and_render(pdfs, 'A4', tmp_path / 'out.pdf')

    assert len(packed.items) == len(pdfs)
    assert len(packed.packer.rect_list()) == len(pdfs)
    assert packed.doc.page_count == 1
