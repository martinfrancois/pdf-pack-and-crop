from pathlib import Path
import subprocess
import sys
import tempfile
import hashlib
import io
import pytest


def test_pack_and_crop_labels(tmp_path):
    import importlib

    if 'fitz' in sys.modules and getattr(sys.modules['fitz'], '__is_stub__', False):
        del sys.modules['fitz']
    if 'PIL' in sys.modules:
        sys.modules.pop('PIL', None)
        sys.modules.pop('PIL.Image', None)

    fitz = pytest.importorskip('fitz')
    if getattr(fitz, '__is_stub__', False):
        pytest.skip('fitz stubbed', allow_module_level=True)

    from PIL import Image
    import pack_and_crop as cp
    cp = importlib.reload(cp)

    repo_root = Path(__file__).resolve().parent.parent
    output = tmp_path / 'out.pdf'
    inputs = [repo_root / 'test' / f'label{i}.pdf' for i in range(1, 7)]

    cmd = [sys.executable, str(repo_root / 'pack_and_crop.py'), *map(str, inputs), '-o', str(output)]
    subprocess.run(cmd, check=True, cwd=repo_root)

    doc = fitz.open(output)
    assert doc.page_count == 6

    with tempfile.TemporaryDirectory() as td:
        items = cp.crop_pages(inputs, td, 300, 250)
        expected = {hashlib.md5(Image.open(p).convert('RGB').tobytes()).hexdigest() for p, _, _ in items}

    actual = set()
    for page in doc:
        xref = page.get_images()[0][0]
        img_bytes = doc.extract_image(xref)['image']
        im = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        actual.add(hashlib.md5(im.tobytes()).hexdigest())

    assert actual == expected
