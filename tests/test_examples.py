"""Run crop and pack on the synthetic labels from examples/make_labels.py."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

import pack_and_crop as cp

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples" / "labels"
A4_W, A4_H = cp.parse_pagesize("A4")


def load_generator():
    spec = importlib.util.spec_from_file_location("make_labels", ROOT / "examples" / "make_labels.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = load_generator()


def run_cli(inputs, output, *extra):
    cmd = [sys.executable, str(ROOT / "pack_and_crop.py"), *map(str, inputs), "-o", str(output), *extra]
    subprocess.run(cmd, check=True, cwd=ROOT)
    return pymupdf.open(output)


def image_count(doc):
    return sum(len(page.get_images()) for page in doc)


def assert_page_size(page, width_pt, height_pt):
    assert page.rect.width == pytest.approx(width_pt, abs=1)
    assert page.rect.height == pytest.approx(height_pt, abs=1)


def test_committed_examples_are_single_a4_pages():
    paths = sorted(EXAMPLES.glob("*.pdf"))
    assert len(paths) == GEN.DEFAULT_COUNT
    for path in paths:
        doc = pymupdf.open(path)
        assert doc.page_count == 1
        assert_page_size(doc[0], A4_W, A4_H)


def test_crop_finds_the_label_box(tmp_path):
    items = cp.crop_pages(sorted(EXAMPLES.glob("*.pdf")), tmp_path, 100, 250)
    assert len(items) == GEN.DEFAULT_COUNT
    for _, w_pt, h_pt in items:
        assert w_pt < A4_W / 2 and h_pt < A4_H / 4
        # the crop is the drawn box plus its stroke width
        assert w_pt == pytest.approx(cp.mm_to_pt(GEN.DEFAULT_WIDTH_MM), abs=cp.mm_to_pt(1))
        assert h_pt == pytest.approx(cp.mm_to_pt(GEN.DEFAULT_HEIGHT_MM), abs=cp.mm_to_pt(1))


def test_example_labels_fit_on_one_sheet(tmp_path):
    doc = run_cli([EXAMPLES], tmp_path / "packed.pdf")
    assert doc.page_count == 1
    assert image_count(doc) == GEN.DEFAULT_COUNT


def test_wide_labels_spread_over_two_sheets(tmp_path):
    labels = GEN.make_labels(tmp_path / "wide", count=3, width_mm=150, height_mm=100)
    doc = run_cli(labels, tmp_path / "packed.pdf")
    assert doc.page_count == 2
    assert image_count(doc) == 3


def test_letter_page_size(tmp_path):
    doc = run_cli([EXAMPLES], tmp_path / "packed.pdf", "--pagesize", "Letter")
    assert_page_size(doc[0], *cp.parse_pagesize("Letter"))
    assert image_count(doc) == GEN.DEFAULT_COUNT
