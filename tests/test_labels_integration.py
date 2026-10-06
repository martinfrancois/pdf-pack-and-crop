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


# With the default A4 page, 5 mm margin and 1 mm spacing, none of labels 2, 3, 4 and 6 fits on a
# sheet next to another label from 1 to 6 or 8, and only two of labels 1, 5 and 8 fit on one sheet.
# A set that holds labels 1 to 6 and 8 therefore needs at least 6 sheets.
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
    cmd = [sys.executable, str(repo_root / 'pack_and_crop.py'), *map(str, input_paths), '-o', str(output_pdf)]
    subprocess.run(cmd, check=True, cwd=repo_root)

    # Verify total pages in generated PDF
    doc = fitz.open(output_pdf)
    assert doc.page_count == expected_pages, (
        f"For inputs {label_nums}, expected {expected_pages} pages, got {doc.page_count}"
    )

    # Generate expected cropped image hashes
    with tempfile.TemporaryDirectory() as td:
        items = cp.crop_pages(input_paths, td, 300, 250)
        
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
    margin_pt, spacing_pt, tolerance_pt = cp.mm_to_pt(5), cp.mm_to_pt(1), 0.5
    cropped_sizes = sorted(sorted((round(w, 1), round(h, 1))) for _, w, h in items)
    placed_sizes = []
    for page in doc:
        boxes = [fitz.Rect(info['bbox']) for info in page.get_image_info()]
        placed_sizes.extend(sorted((round(box.width, 1), round(box.height, 1))) for box in boxes)
        for box in boxes:
            assert box.x0 >= margin_pt - tolerance_pt and box.y0 >= margin_pt - tolerance_pt
            assert box.x1 <= page.rect.width - margin_pt + tolerance_pt
            assert box.y1 <= page.rect.height - margin_pt + tolerance_pt
        for i, first in enumerate(boxes):
            for second in boxes[i + 1:]:
                gap = max(second.x0 - first.x1, first.x0 - second.x1,
                          second.y0 - first.y1, first.y0 - second.y1)
                assert gap >= spacing_pt - tolerance_pt
    assert sorted(placed_sizes) == cropped_sizes, "A label was scaled on the sheet"

    # Verify each input file is represented in the cropped output
    represented = {Path(p).stem.split('_', 1)[0] for p, _, _ in items}
    expected_labels = {f"label{n}" for n in label_nums}
    assert represented >= expected_labels, (
        f"Missing labels in output: {expected_labels - represented}"
    )
