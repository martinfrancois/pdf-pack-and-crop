import argparse
from pathlib import Path
from types import SimpleNamespace
import sys
import importlib
import pytest

# provide minimal stubs when optional libs are missing
def _spec(name):
    try:
        return importlib.util.find_spec(name)
    except Exception:
        return None

if _spec('fitz') is None:
    sys.modules['fitz'] = SimpleNamespace()
if _spec('PIL') is None:
    sys.modules['PIL'] = SimpleNamespace(Image=SimpleNamespace())
if _spec('rectpack') is None:
    sys.modules['rectpack'] = SimpleNamespace(newPacker=None, MaxRectsBssf=None, SORT_AREA=None)

import crop_and_pack as cap


def test_mm_to_pt():
    assert cap.mm_to_pt(25.4) == pytest.approx(72)


def test_parse_pagesize_presets():
    w, h = cap.parse_pagesize("A4")
    assert w == pytest.approx(cap.mm_to_pt(210))
    assert h == pytest.approx(cap.mm_to_pt(297))


def test_parse_pagesize_custom():
    w, h = cap.parse_pagesize("10x20")
    assert w == pytest.approx(cap.mm_to_pt(10))
    assert h == pytest.approx(cap.mm_to_pt(20))


def test_parse_pagesize_invalid():
    with pytest.raises(argparse.ArgumentTypeError):
        cap.parse_pagesize("foo")


def test_gather_pdfs(tmp_path):
    a = tmp_path / "b.pdf"
    b = tmp_path / "a.pdf"
    a.write_text("pdf")
    b.write_text("pdf")
    # directory input sorted
    res = cap.gather_pdfs([str(tmp_path)])
    assert res == [b, a]
    # explicit files
    res2 = cap.gather_pdfs([str(a), str(b)])
    assert res2 == [a, b]
    with pytest.raises(SystemExit):
        cap.gather_pdfs([])


def test_rect_rotated():
    rect = SimpleNamespace(width=110, height=210)
    assert cap.rect_rotated(rect, 200, 100, 5)
    rect2 = SimpleNamespace(width=100, height=200)
    assert not cap.rect_rotated(rect2, 100, 200, 0)
