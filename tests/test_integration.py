from pathlib import Path
import tempfile
import pytest

fitz = pytest.importorskip('fitz')
if getattr(fitz, '__is_stub__', False):
    pytest.skip('fitz stubbed', allow_module_level=True)

import pack_and_crop as cp


def make_pdf(path: Path, width=100, height=100):
    doc = fitz.open()
    doc.new_page(width=width, height=height)
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


def test_rotation_needed_flow(tmp_path):
    pdf1 = tmp_path / 'a.pdf'
    pdf2 = tmp_path / 'b.pdf'
    make_pdf(pdf1, width=90, height=50)
    make_pdf(pdf2, width=90, height=50)

    output = tmp_path / 'out.pdf'
    page_w, page_h = cp.parse_pagesize('60x120')
    margin_pt = cp.mm_to_pt(5)
    spacing_pt = cp.mm_to_pt(5)
    eff_w = page_w - 2 * margin_pt
    eff_h = page_h - 2 * margin_pt

    with tempfile.TemporaryDirectory() as td:
        items = cp.crop_pages([pdf1, pdf2], td, 72, 250)
        pk, rot = cp.find_minimal_packing(items, eff_w, eff_h, spacing_pt)
        assert rot is True
        cp.render_pdf(pk, items, page_w, page_h, margin_pt, spacing_pt, rot, str(output))

    out = fitz.open(output)
    assert out.page_count >= 1


def test_many_small_pdfs(tmp_path):
    pdfs = []
    for i in range(8):
        p = tmp_path / f'small{i}.pdf'
        make_pdf(p, width=50, height=50)
        pdfs.append(p)

    output = tmp_path / 'out.pdf'
    page_w, page_h = cp.parse_pagesize('A4')
    margin_pt = cp.mm_to_pt(5)
    spacing_pt = cp.mm_to_pt(5)
    eff_w = page_w - 2 * margin_pt
    eff_h = page_h - 2 * margin_pt

    with tempfile.TemporaryDirectory() as td:
        items = cp.crop_pages(pdfs, td, 72, 250)
        assert len(items) == 8
        pk, rot = cp.find_minimal_packing(items, eff_w, eff_h, spacing_pt)
        cp.render_pdf(pk, items, page_w, page_h, margin_pt, spacing_pt, rot, str(output))

    out = fitz.open(output)
    assert out.page_count >= 1

