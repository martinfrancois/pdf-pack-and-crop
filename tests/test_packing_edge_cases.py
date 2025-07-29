import sys
import types
import pytest

import crop_and_pack as cp


class DummyRect:
    def __init__(self, x=0, y=0, width=0, height=0, rid=0):
        self.x, self.y, self.width, self.height, self.rid = x, y, width, height, rid


class MultiBinPacker:
    def __init__(self, rotation=False, pack_algo=None, sort_algo=None):
        self.rotation = rotation
        self.rects = []
        self.bins = []

    def add_rect(self, w, h, rid=None):
        self.rects.append((w, h, rid))

    def add_bin(self, w, h):
        self.bins.append({'w': w, 'h': h, 'used': 0, 'rects': []})

    def pack(self):
        for w, h, rid in self.rects:
            placed = False
            for bin in self.bins:
                if w <= bin['w'] and bin['used'] + h <= bin['h']:
                    bin['rects'].append(DummyRect(0, bin['used'], w, h, rid))
                    bin['used'] += h
                    placed = True
                    break
                if self.rotation and h <= bin['w'] and bin['used'] + w <= bin['h']:
                    bin['rects'].append(DummyRect(0, bin['used'], h, w, rid))
                    bin['used'] += w
                    placed = True
                    break
            if not placed:
                for b in self.bins:
                    b['rects'] = []
                break
        self._rects = [r for b in self.bins for r in b['rects']]

    def rect_list(self):
        return self._rects

    def __iter__(self):
        for b in self.bins:
            yield b['rects']


@pytest.fixture(autouse=True)
def patch_packer(monkeypatch):
    monkeypatch.setattr(cp, 'newPacker', lambda **kw: MultiBinPacker(**kw))


def test_find_minimal_packing_many_small_pdfs():
    items = [(f'im{i}', 20, 20) for i in range(12)]
    pk, rot = cp.find_minimal_packing(items, 100, 100, 0)
    assert rot is False
    assert len(list(pk)) == 3


def test_find_minimal_packing_only_big_pdfs():
    items = [('big1', 150, 150), ('big2', 120, 120)]
    with pytest.raises(RuntimeError):
        cp.find_minimal_packing(items, 100, 100, 0)


def test_find_minimal_packing_requires_rotation():
    items = [('rot', 120, 80)]
    pk, rot = cp.find_minimal_packing(items, 80, 120, 0)
    assert rot is True
    assert len(list(pk)) == 1
