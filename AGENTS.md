# Developer Notes

Run tests with:

```bash
pytest -vv --cov=pack_and_crop.py --cov-report=term-missing
```

Integration tests require `pymupdf`, `Pillow`, and `rectpack` to be installed.
