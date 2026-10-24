import pytest

import pack_and_crop as cp

PAGE = 100
SPACING = 5


def _attempts(packers):
    return [(len(p.bins), p.rotation) for p in packers]


def _search_order(max_bins):
    """Every (bins, rotation) attempt find_minimal_packing may make, in the order it makes them."""
    return [(bins, rotate) for bins in range(1, max_bins + 1) for rotate in (False, True)]


def test_many_small_items_stop_at_the_first_bin_count_that_fits(stub_packers):
    items = [(f'i{i}', 20, 20) for i in range(30)]
    pk, rot = cp.find_minimal_packing(items, PAGE, PAGE, 0)

    attempts = _attempts(stub_packers)
    assert attempts == _search_order(len(items))[:len(attempts)]
    assert all(len(p.rect_list()) < len(items) for p in stub_packers[:-1])
    assert pk is stub_packers[-1]
    assert len(pk.rect_list()) == len(items)
    assert len(pk) > 1
    assert not rot


def test_single_page_sized_item_fits_on_first_attempt(stub_packers):
    pk, rot = cp.find_minimal_packing([('big', PAGE, PAGE)], PAGE, PAGE, 0)
    assert _attempts(stub_packers) == [(1, False)]
    assert len(pk) == 1
    assert not rot


def test_rotation_only_tried_after_unrotated_attempt_fails(stub_packers):
    pk, rot = cp.find_minimal_packing([('r', 80, 40)], 40, PAGE, 0)
    assert _attempts(stub_packers) == [(1, False), (1, True)]
    assert len(pk.rect_list()) == 1
    assert rot


def test_items_too_large_fail_after_every_bin_count(stub_packers):
    items = [('huge1', 2 * PAGE, 2 * PAGE), ('huge2', 2 * PAGE, 2 * PAGE)]
    with pytest.raises(RuntimeError):
        cp.find_minimal_packing(items, PAGE, PAGE, 0)
    assert _attempts(stub_packers) == _search_order(len(items))


def test_spacing_pads_trailing_edges_only(stub_packers):
    w, h = PAGE - SPACING, PAGE - 2 * SPACING
    cp.find_minimal_packing([('a', w, h)], PAGE, PAGE, SPACING)
    assert stub_packers[0].rects == [(w + SPACING, h + SPACING, 0)]


@pytest.mark.parametrize('side, fits', [(PAGE - SPACING, True), (PAGE - SPACING + 1, False)])
def test_spacing_counts_toward_page_fit(stub_packers, side, fits):
    items = [('a', side, side)]
    if fits:
        pk, _ = cp.find_minimal_packing(items, PAGE, PAGE, SPACING)
        assert len(pk) == 1
    else:
        with pytest.raises(RuntimeError):
            cp.find_minimal_packing(items, PAGE, PAGE, SPACING)


def test_many_small_items_share_sheets_with_real_packer():
    rectpack = pytest.importorskip('rectpack')
    if getattr(rectpack, '__is_stub__', False):
        pytest.skip('rectpack stubbed')
    side = 20
    per_sheet = (PAGE // side) ** 2
    items = [(f'i{i}', side, side) for i in range(per_sheet + 1)]
    pk, rot = cp.find_minimal_packing(items, PAGE, PAGE, 0)
    assert len(pk) == 2
    assert not rot
