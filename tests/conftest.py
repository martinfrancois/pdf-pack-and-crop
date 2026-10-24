import importlib
import sys
import types

import pytest


class StubRect:
    def __init__(self, x, y, width, height, rid):
        self.x, self.y, self.width, self.height, self.rid = x, y, width, height, rid


class StubBin:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.used = 0
        self.rects = []

    def place(self, width, height, rid):
        if width > self.width or self.used + height > self.height:
            return False
        self.rects.append(StubRect(0, self.used, width, height, rid))
        self.used += height
        return True


class StubPacker:
    """Stacks rects in one column per bin; offers the part of rectpack's packer that pack_and_crop uses."""

    def __init__(self, rotation=False, pack_algo=None, sort_algo=None):
        self.rotation = rotation
        self.rects = []
        self.bins = []

    def add_rect(self, width, height, rid=None):
        self.rects.append((width, height, rid))

    def add_bin(self, width, height):
        self.bins.append(StubBin(width, height))

    def pack(self):
        for width, height, rid in self.rects:
            for b in self.bins:
                if b.place(width, height, rid) or (self.rotation and b.place(height, width, rid)):
                    break

    def _used_bins(self):
        # rectpack only reports bins that received at least one rect
        return [b.rects for b in self.bins if b.rects]

    def rect_list(self):
        return [rect for rects in self._used_bins() for rect in rects]

    def __iter__(self):
        return iter(self._used_bins())

    def __len__(self):
        return len(self._used_bins())


def _stub_if_missing(name, **attrs):
    try:
        importlib.import_module(name)
    except ImportError:
        module = types.ModuleType(name)
        module.__is_stub__ = True
        module.__dict__.update(attrs)
        sys.modules[name] = module


# Runs before any test module imports pack_and_crop, so the unit tests work without the optional libraries.
_stub_if_missing("fitz")
_stub_if_missing(
    "rectpack",
    newPacker=lambda **kwargs: StubPacker(**kwargs),
    MaxRectsBssf=object(),
    SORT_AREA=object(),
)


@pytest.fixture
def stub_packers(monkeypatch):
    """Route pack_and_crop through StubPacker and return every packer it creates, in creation order."""
    import pack_and_crop

    created = []

    def new_packer(**kwargs):
        packer = StubPacker(**kwargs)
        created.append(packer)
        return packer

    monkeypatch.setattr(pack_and_crop, "newPacker", new_packer)
    return created
