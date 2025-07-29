import sys
import types
from pathlib import Path
import pytest

# Create stubs for optional libraries when absent
if 'fitz' not in sys.modules:
    sys.modules['fitz'] = types.ModuleType('fitz')
    sys.modules['fitz'].__is_stub__ = True
if 'PIL' not in sys.modules:
    pil = types.ModuleType('PIL')
    image_mod = types.ModuleType('Image')
    pil.Image = image_mod
    sys.modules['PIL'] = pil
    sys.modules['PIL.Image'] = image_mod
if 'rectpack' not in sys.modules:
    rectpack = types.ModuleType('rectpack')
    rectpack.__is_stub__ = True
    class DummyRect:
        def __init__(self, x=0, y=0, width=0, height=0, rid=0):
            self.x, self.y, self.width, self.height, self.rid = x, y, width, height, rid
    class DummyPacker:
        def __init__(self, rotation=False, pack_algo=None, sort_algo=None):
            self.rotation = rotation
            self.rects = []
            self.bins = []
        def add_rect(self, w, h, rid=None):
            self.rects.append((w, h, rid))
        def add_bin(self, w, h):
            self.bins.append({'w': w, 'h': h, 'used': 0, 'rects': []})
        def pack(self):
            bin = self.bins[0]
            for w, h, rid in self.rects:
                placed = False
                if w <= bin['w'] and bin['used'] + h <= bin['h']:
                    bin['rects'].append(DummyRect(0, bin['used'], w, h, rid))
                    bin['used'] += h
                    placed = True
                elif self.rotation and h <= bin['w'] and bin['used'] + w <= bin['h']:
                    bin['rects'].append(DummyRect(0, bin['used'], h, w, rid))
                    bin['used'] += w
                    placed = True
                if not placed:
                    bin['rects'] = []
                    break
            self._rects = bin['rects']
        def rect_list(self):
            return self._rects
        def __iter__(self):
            yield self._rects
    rectpack.newPacker = lambda **kw: DummyPacker(**kw)
    rectpack.MaxRectsBssf = object()
    rectpack.SORT_AREA = object()
    sys.modules['rectpack'] = rectpack

import pack_and_crop as cp


def test_mm_to_pt():
    assert cp.mm_to_pt(25.4) == pytest.approx(72)


def test_parse_pagesize_custom_and_presets():
    assert cp.parse_pagesize('210x297') == (
        cp.mm_to_pt(210),
        cp.mm_to_pt(297),
    )
    assert cp.parse_pagesize('A4')[0] > 0
    assert cp.parse_pagesize('Letter')[0] > 0


@pytest.mark.parametrize('arg', ['bad', '10x', '10'])
def test_parse_pagesize_invalid(arg):
    with pytest.raises(Exception):
        cp.parse_pagesize(arg)


def test_gather_pdfs(tmp_path):
    (tmp_path / 'a.pdf').write_bytes(b'PDF')
    (tmp_path / 'b.pdf').write_bytes(b'PDF')
    files = cp.gather_pdfs([str(tmp_path)])
    assert [f.name for f in files] == ['a.pdf', 'b.pdf']

    files = cp.gather_pdfs([str(tmp_path / 'a.pdf')])
    assert [f.name for f in files] == ['a.pdf']

    empty = tmp_path / 'empty'
    empty.mkdir()
    with pytest.raises(SystemExit):
        cp.gather_pdfs([str(empty)])


def test_find_minimal_packing_rotation_needed():
    items = [('img1', 60, 40), ('img2', 60, 40)]
    eff_w, eff_h = 40, 120
    pk, rotate = cp.find_minimal_packing(items, eff_w, eff_h, 0)
    assert rotate is True
    assert len(list(pk)) == 1


def test_rect_rotated():
    rect = types.SimpleNamespace(width=61, height=41)
    assert cp.rect_rotated(rect, 40, 60, 1)
    rect2 = types.SimpleNamespace(width=42, height=52)
    assert not cp.rect_rotated(rect2, 40, 60, 1)


def test_find_minimal_packing_many_small():
    items = [(f"img{i}", 10, 10) for i in range(10)]
    eff_w, eff_h = 40, 120
    pk, rotate = cp.find_minimal_packing(items, eff_w, eff_h, 0)
    assert rotate is False
    assert len(list(pk)) == 1
    assert len(pk.rect_list()) == 10


def test_find_minimal_packing_too_big():
    items = [("big", 100, 100)]
    with pytest.raises(RuntimeError):
        cp.find_minimal_packing(items, 50, 50, 0)

