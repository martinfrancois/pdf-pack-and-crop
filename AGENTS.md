# Developer notes

Install and test:

```bash
python -m pip install -r requirements.txt
python -m pytest
```

The tests run the tool on the synthetic labels in `examples/labels`. Those
PDFs come from `examples/make_labels.py`; run it again after changing it and
commit the result.
