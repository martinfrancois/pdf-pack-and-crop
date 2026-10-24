import sys

import pytest

import pack_and_crop as cp

SHEET_PT = 100


@pytest.fixture
def real_rectpack(monkeypatch):
    # test_core.py can leave a one-column rectpack stub in sys.modules, and these layouts need the real packer
    if getattr(sys.modules.get('rectpack'), '__is_stub__', False):
        monkeypatch.delitem(sys.modules, 'rectpack')
    rectpack = pytest.importorskip('rectpack')
    for name in ('newPacker', 'MaxRectsBssf', 'SORT_AREA'):
        monkeypatch.setattr(cp, name, getattr(rectpack, name))


def test_find_minimal_packing_puts_many_small_snippets_on_one_sheet(real_rectpack):
    side = SHEET_PT / 5
    snippets = [(f'small{i}', side, side) for i in range(12)]

    packer, rotated = cp.find_minimal_packing(snippets, SHEET_PT, SHEET_PT, 0)

    assert rotated is False
    assert len(list(packer)) == 1
    assert len(packer.rect_list()) == len(snippets)


def test_find_minimal_packing_adds_sheets_until_everything_fits(real_rectpack):
    side = SHEET_PT * 0.6
    snippets = [(f'large{i}', side, side) for i in range(3)]

    packer, rotated = cp.find_minimal_packing(snippets, SHEET_PT, SHEET_PT, 0)

    assert rotated is False
    assert len(list(packer)) == len(snippets)
    assert len(packer.rect_list()) == len(snippets)


@pytest.mark.parametrize('spacing_pt, expected_sheets', [(0, 1), (1, 2)])
def test_find_minimal_packing_pads_snippets_by_the_spacing(real_rectpack, spacing_pt, expected_sheets):
    side = SHEET_PT / 2
    snippets = [('left', side, side), ('right', side, side)]

    packer, rotated = cp.find_minimal_packing(snippets, SHEET_PT, SHEET_PT, spacing_pt)

    assert rotated is False
    assert len(list(packer)) == expected_sheets
    assert all(
        (rect.width, rect.height) == (side + spacing_pt, side + spacing_pt)
        for sheet in packer
        for rect in sheet
    )


def test_find_minimal_packing_raises_when_a_snippet_is_larger_than_the_sheet():
    snippets = [('fits', SHEET_PT / 2, SHEET_PT / 2), ('too_big', SHEET_PT * 1.5, SHEET_PT * 1.5)]

    with pytest.raises(RuntimeError, match='Packing failed'):
        cp.find_minimal_packing(snippets, SHEET_PT, SHEET_PT, 0)


def test_find_minimal_packing_rotates_a_snippet_that_only_fits_sideways():
    snippets = [('wide', 120, 80)]

    packer, rotated = cp.find_minimal_packing(snippets, 80, 120, 0)

    assert rotated is True
    assert len(list(packer)) == 1
