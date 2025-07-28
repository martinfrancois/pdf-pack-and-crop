from types import SimpleNamespace
from pathlib import Path
import sys
import importlib
import pytest

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


def make_image_stub(size=(100, 100)):
    class ImageStub:
        def __init__(self, size):
            self.size = size
        def convert(self, mode):
            return self
        def point(self, func, mode):
            return self
        def getbbox(self):
            return (10, 10, self.size[0]-10, self.size[1]-10)
        def crop(self, bbox):
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            return make_image_stub((w, h))
        def save(self, path, fmt):
            Path(path).write_text('img')
    return ImageStub(size)

class DummyPixmap:
    def tobytes(self, fmt):
        return b''

class DummyPage:
    def __init__(self):
        self.pix = DummyPixmap()
    def get_pixmap(self, dpi=None, alpha=None):
        return self.pix

class DummyDoc:
    def __init__(self, pages=1):
        self.page_count = pages
    def load_page(self, i):
        return DummyPage()

class DummyFitz:
    def __init__(self, pages=1):
        self.pages = pages
    def open(self, path):
        return DummyDoc(self.pages)
    def Rect(self, x0, y0, x1, y1):
        return (x0, y0, x1, y1)

class DummyDocOut:
    def __init__(self):
        self.pages = []
    def new_page(self, width=None, height=None):
        self.pages.append([])
    def __getitem__(self, idx):
        class Page:
            def __init__(self, lst):
                self.lst = lst
            def insert_image(self, rect, filename=None, rotate=0):
                self.lst.append((rect, filename, rotate))
        return Page(self.pages[idx])
    def save(self, filename):
        Path(filename).write_text('pdf')

class DummyPacker(list):
    def __init__(self, rect):
        super().__init__([ [rect] ])

class DummyRect(SimpleNamespace):
    pass


def test_crop_pages(monkeypatch, tmp_path):
    dummy_fitz = DummyFitz()
    monkeypatch.setattr(cap, 'fitz', dummy_fitz)
    monkeypatch.setattr(cap, 'Image', SimpleNamespace(open=lambda _: make_image_stub()))
    pdf = tmp_path / 'a.pdf'
    pdf.write_text('pdf')
    items = cap.crop_pages([pdf], tmp_path, dpi=72, white_thresh=250)
    assert len(items) == 1
    img_path, w_pt, h_pt = items[0]
    assert Path(img_path).exists()
    assert w_pt == h_pt == pytest.approx(80)


def test_find_minimal_packing(monkeypatch):
    class StubPacker:
        def __init__(self, rotation=False, pack_algo=None, sort_algo=None):
            self.rotation = rotation
            self.rects = []
            self.bins = []
        def add_rect(self, w, h, rid=None):
            self.rects.append((w, h, rid))
        def add_bin(self, w, h):
            self.bins.append((w, h))
        def pack(self):
            pass
        def rect_list(self):
            return [DummyRect()] if self.rotation else []
    monkeypatch.setattr(cap, 'newPacker', StubPacker)
    pk, rot = cap.find_minimal_packing([('a',1,1)], 10,10,0)
    assert rot is True


def test_render_pdf(monkeypatch, tmp_path):
    dummy_doc = DummyDocOut()
    dummy_fitz = SimpleNamespace(open=lambda: dummy_doc, Rect=lambda x0,y0,x1,y1: (x0,y0,x1,y1))
    monkeypatch.setattr(cap, 'fitz', dummy_fitz)
    packer = DummyPacker(DummyRect(x=0,y=0,width=12,height=12,rid=0))
    img = tmp_path/'img.png'
    img.write_text('i')
    cap.render_pdf(packer, [(str(img),10,10)], 20,20,0,1,False, tmp_path/'out.pdf')
    assert (tmp_path/'out.pdf').exists()
    assert dummy_doc.pages
