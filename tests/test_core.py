import types
import pytest

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
    with pytest.raises(RuntimeError, match="Packing failed"):
        cp.find_minimal_packing(items, 50, 50, 0)
