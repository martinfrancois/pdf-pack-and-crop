import subprocess
import sys
from pathlib import Path
import tempfile
import hashlib
import io
import pytest


def _reload_modules():
    # Ensure real fitz and PIL modules are loaded, not stubs
    if 'fitz' in sys.modules and getattr(sys.modules['fitz'], '__is_stub__', False):
        del sys.modules['fitz']
    sys.modules.pop('PIL', None)
    sys.modules.pop('PIL.Image', None)


# The expected page counts and the geometry checks depend on these, so the test passes them to the CLI
# instead of relying on its defaults.
PAGE_SIZE = "A4"
PAGE_MARGIN_MM = 5
SPACING_MM = 1
DPI = 300
WHITE_THRESHOLD = 250
# Placed positions go through float maths in rectpack and PyMuPDF, so allow a little noise.
TOLERANCE_PT = 0.5


def _orientation_free_size(width, height):
    # A label placed with a 90 degree turn swaps width and height.
    return tuple(sorted((width, height)))


def _size_difference(first, second):
    return max(abs(a - b) for a, b in zip(first, second))


def _pair_sizes(cropped_sizes, placed_sizes):
    # Labels can share a side (3 and 6 are both 500.16 pt wide), so float noise on that side can
    # reorder sorted sizes and pair one label with another's size. Taking the closest pairs first
    # keeps each label with its own size while different sizes differ by more than twice the noise.
    candidates = sorted((_size_difference(cropped, placed), c, p)
                        for c, cropped in enumerate(cropped_sizes)
                        for p, placed in enumerate(placed_sizes))
    used_cropped, used_placed, pairs = set(), set(), []
    for _, c, p in candidates:
        if c not in used_cropped and p not in used_placed:
            used_cropped.add(c)
            used_placed.add(p)
            pairs.append((cropped_sizes[c], placed_sizes[p]))
    return pairs


def test_pair_sizes_keeps_labels_apart_when_noise_reorders_a_shared_side():
    # PyMuPDF reports placed sizes as float32, so label 6 can come out a hair narrower than
    # label 3 and sort ahead of it.
    label3, label6 = (500.16, 640.8), (500.16, 743.28)
    placed3, placed6 = (500.16003227233887, 640.7999877929688), (500.15997314453125, 743.2799682617188)
    assert sorted(_pair_sizes([label3, label6], [placed3, placed6])) == [
        (label3, placed3), (label6, placed6)]


def _assert_labels_unscaled_inside_margin_and_spaced(doc, items, margin_pt, spacing_pt):
    import fitz  # the caller has already replaced any stub with the real module

    cropped_sizes = [_orientation_free_size(w, h) for _, w, h in items]
    placed_sizes = []
    for page in doc:
        boxes = [fitz.Rect(info['bbox']) for info in page.get_image_info()]
        placed_sizes.extend(_orientation_free_size(box.width, box.height) for box in boxes)
        for box in boxes:
            assert box.x0 >= margin_pt - TOLERANCE_PT and box.y0 >= margin_pt - TOLERANCE_PT, (
                f"A label on sheet {page.number + 1} starts inside the top or left margin: {box}"
            )
            assert box.x1 <= page.rect.width - margin_pt + TOLERANCE_PT, (
                f"A label on sheet {page.number + 1} ends inside the right margin: {box}"
            )
            assert box.y1 <= page.rect.height - margin_pt + TOLERANCE_PT, (
                f"A label on sheet {page.number + 1} ends inside the bottom margin: {box}"
            )
        for i, first in enumerate(boxes):
            for second in boxes[i + 1:]:
                gap = max(second.x0 - first.x1, first.x0 - second.x1,
                          second.y0 - first.y1, first.y0 - second.y1)
                assert gap >= spacing_pt - TOLERANCE_PT, (
                    f"Two labels on sheet {page.number + 1} have a gap of {gap:.2f} pt, "
                    f"below the {spacing_pt:.2f} pt spacing: {first} and {second}"
                )
    assert len(placed_sizes) == len(cropped_sizes), (
        f"Expected {len(cropped_sizes)} labels on the sheets, found {len(placed_sizes)}"
    )
    for cropped, placed in _pair_sizes(cropped_sizes, placed_sizes):
        assert _size_difference(cropped, placed) <= TOLERANCE_PT, (
            f"A label was scaled on the sheet: cropped {cropped}, placed {placed}"
        )


# With these settings, none of labels 2, 3, 4 and 6 fits on a sheet next to another label from
# 1 to 6 or 8, and only two of labels 1, 5 and 8 fit on one sheet. A set that holds labels 1 to 6
# and 8 therefore needs at least 6 sheets.
@pytest.mark.parametrize("label_nums, expected_pages", [
    ([1], 1),
    ([1, 5], 1),
    ([1, 2, 5], 2),
    ([1, 2, 5, 10], 2),
    ([1, 2, 3, 4, 5, 6], 5),
    ([1, 2, 3, 4, 5, 6, 8], 6),
    ([1, 2, 3, 4, 5, 6, 8, 10], 6),
    ([1, 2, 3, 4, 5, 6, 8, 10, 11], 6),
    ([1, 2, 3, 4, 5, 6, 8, 9, 10, 11], 6),
])
def test_pack_and_crop_labels_various(tmp_path, label_nums, expected_pages):
    import importlib
    import sys  # Add sys import here
    from PIL import Image

    # Reload modules to avoid stubs
    _reload_modules()
    fitz = pytest.importorskip('fitz')
    if getattr(fitz, '__is_stub__', False):
        pytest.skip('fitz stubbed', allow_module_level=True)
    
    # Re-import Image after _reload_modules to get a fresh, working module
    from PIL import Image

    # Reload the script under test
    import pack_and_crop as cp
    cp = importlib.reload(cp)

    repo_root = Path(__file__).resolve().parent.parent
    # Build input PDF paths dynamically
    input_paths = [repo_root / 'test' / f"label{n}.pdf" for n in label_nums]
    output_pdf = tmp_path / f"out_{'_'.join(map(str, label_nums))}.pdf"

    # Run the CLI pack_and_crop
    cmd = [sys.executable, str(repo_root / 'pack_and_crop.py'), *map(str, input_paths),
           '--pagesize', PAGE_SIZE, '--page-margin', str(PAGE_MARGIN_MM), '--spacing', str(SPACING_MM),
           '--dpi', str(DPI), '--threshold', str(WHITE_THRESHOLD), '-o', str(output_pdf)]
    subprocess.run(cmd, check=True, cwd=repo_root)

    # Verify total pages in generated PDF
    doc = fitz.open(output_pdf)
    assert doc.page_count == expected_pages, (
        f"For inputs {label_nums}, expected {expected_pages} pages, got {doc.page_count}"
    )

    # Generate expected cropped image hashes
    with tempfile.TemporaryDirectory() as td:
        items = cp.crop_pages(input_paths, td, DPI, WHITE_THRESHOLD)
        
        # Ensure we have a fresh Image module for opening the files
        # This is needed because module reloading can corrupt PIL's state
        for mod in list(sys.modules.keys()):
            if mod.startswith('PIL'):
                sys.modules.pop(mod, None)
        from PIL import Image
        
        expected_hashes = {
            hashlib.md5(Image.open(p).convert('RGB').tobytes()).hexdigest()
            for p, _, _ in items
        }

    # Extract actual image hashes from PDF pages
    actual_hashes = set()
    for page in doc:
        for img in page.get_images():
            xref = img[0]
            img_bytes = doc.extract_image(xref)['image']
            im = Image.open(io.BytesIO(img_bytes)).convert('RGB')
            actual_hashes.add(hashlib.md5(im.tobytes()).hexdigest())

    assert actual_hashes == expected_hashes, "Mismatch between cropped images and PDF contents"

    # A smaller page count must come from better packing, not from shrinking a label,
    # crossing the page margin or dropping the spacing between labels.
    _assert_labels_unscaled_inside_margin_and_spaced(
        doc, items, cp.mm_to_pt(PAGE_MARGIN_MM), cp.mm_to_pt(SPACING_MM))

    # Verify each input file is represented in the cropped output
    represented = {Path(p).stem.split('_', 1)[0] for p, _, _ in items}
    expected_labels = {f"label{n}" for n in label_nums}
    assert represented >= expected_labels, (
        f"Missing labels in output: {expected_labels - represented}"
    )
