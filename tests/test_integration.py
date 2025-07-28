import sys
from pathlib import Path
import sys as _sys
from types import SimpleNamespace
import pytest

_sys.modules.setdefault('PIL', SimpleNamespace(Image=SimpleNamespace()))
_sys.modules.setdefault('rectpack', SimpleNamespace(newPacker=None, MaxRectsBssf=None, SORT_AREA=None))

try:
    import fitz  # type: ignore
    if not hasattr(fitz, 'open'):
        raise ImportError
except Exception:
    pytest.skip('fitz not installed', allow_module_level=True)

import crop_and_pack as cap


def create_pdf(path: Path, text: str):
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.insert_text((20,50), text, fontsize=20)
    doc.save(path)
    doc.close()


def test_cli_integration(tmp_path, monkeypatch):
    pdf1 = tmp_path / 'one.pdf'
    pdf2 = tmp_path / 'two.pdf'
    create_pdf(pdf1, 'One')
    create_pdf(pdf2, 'Two')
    out = tmp_path / 'out.pdf'

    argv = [
        'prog', str(pdf1), str(pdf2), '--pagesize', '60x60', '--page-margin', '0', '--spacing', '0', '-o', str(out)
    ]
    monkeypatch.setattr(sys, 'argv', argv)
    cap.main()
    doc = fitz.open(out)
    assert doc.page_count == 2
    w = doc[0].rect.width
    h = doc[0].rect.height
    assert w == pytest.approx(cap.mm_to_pt(60))
    assert h == pytest.approx(cap.mm_to_pt(60))
    doc.close()
