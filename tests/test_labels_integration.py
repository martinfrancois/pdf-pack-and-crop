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


@pytest.mark.parametrize("label_nums, expected_pages", [
    ([1], 1),
    ([1, 5], 1),
    ([1, 2, 5], 2),
    ([1, 2, 5, 10], 2),
    ([1, 2, 3, 4, 5, 6], 5),
    ([1, 2, 3, 4, 5, 6, 8], 5),
    ([1, 2, 3, 4, 5, 6, 8, 10], 5),
    ([1, 2, 3, 4, 5, 6, 8, 10, 11], 5),
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

    # Verify each input file is represented in the cropped output
    represented = {Path(p).stem.split('_', 1)[0] for p, _, _ in items}
    expected_labels = {f"label{n}" for n in label_nums}
    assert represented >= expected_labels, (
        f"Missing labels in output: {expected_labels - represented}"
    )
