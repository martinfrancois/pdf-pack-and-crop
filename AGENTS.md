# Developer Notes

Run tests with:

```bash
pytest -vv --cov=crop_and_pack.py --cov-report=term-missing
```

Integration tests require `pymupdf`, `Pillow`, and `rectpack` to be installed.
