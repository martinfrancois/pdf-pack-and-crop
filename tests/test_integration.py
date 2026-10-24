from pathlib import Path
import tempfile
import pytest

fitz = pytest.importorskip('fitz')
if getattr(fitz, '__is_stub__', False):
    pytest.skip('fitz stubbed', allow_module_level=True)

import pack_and_crop as cp

MARGIN_MM = 5
SPACING_MM = 5
DPI = 72
WHITE_THRESHOLD = 250


def make_pdf(path: Path, width=100, height=100):
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    doc.save(path)


def pack_and_render(pdfs, pagesize, output):
    """Run crop, pack and render like the CLI does; return (items, packer, rotated, output doc)."""
    page_w, page_h = cp.parse_pagesize(pagesize)
    margin_pt = cp.mm_to_pt(MARGIN_MM)
    spacing_pt = cp.mm_to_pt(SPACING_MM)
    eff_w = page_w - 2 * margin_pt
    eff_h = page_h - 2 * margin_pt

    with tempfile.TemporaryDirectory() as td:
        items = cp.crop_pages(pdfs, td, DPI, WHITE_THRESHOLD)
        pk, rot = cp.find_minimal_packing(items, eff_w, eff_h, spacing_pt)
        cp.render_pdf(pk, items, page_w, page_h, margin_pt, spacing_pt, rot, str(output))

    return items, pk, rot, fitz.open(output)


def test_full_flow(tmp_path):
    pdf1 = tmp_path / 'a.pdf'
    pdf2 = tmp_path / 'b.pdf'
    make_pdf(pdf1)
    make_pdf(pdf2)

    _, _, _, out = pack_and_render([pdf1, pdf2], 'A4', tmp_path / 'out.pdf')

    assert out.page_count >= 1


def test_rotation_needed_flow(tmp_path):
    pagesize = '60x120'
    # As wide as the usable sheet, so with spacing added a snippet only fits rotated.
    width = cp.parse_pagesize(pagesize)[0] - 2 * cp.mm_to_pt(MARGIN_MM)
    pdf1 = tmp_path / 'a.pdf'
    pdf2 = tmp_path / 'b.pdf'
    make_pdf(pdf1, width=width, height=50)
    make_pdf(pdf2, width=width, height=50)

    _, pk, rot, out = pack_and_render([pdf1, pdf2], pagesize, tmp_path / 'out.pdf')

    assert rot is True
    assert len(pk.rect_list()) == 2
    assert out.page_count == 1


def test_many_small_pdfs(tmp_path):
    pdfs = []
    for i in range(8):
        p = tmp_path / f'small{i}.pdf'
        make_pdf(p, width=50, height=50)
        pdfs.append(p)

    items, pk, _, out = pack_and_render(pdfs, 'A4', tmp_path / 'out.pdf')

    assert len(items) == len(pdfs)
    assert len(pk.rect_list()) == len(pdfs)
    assert out.page_count == 1
