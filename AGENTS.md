# Developer notes

Before submitting a change, run the installation and coverage commands in
[Running Tests](README.md#running-tests). Check that the report includes executed
lines for `pack_and_crop.py`. Follow the existing style; no formatter is required.

The tests run the tool on the synthetic labels in `examples/labels`. Those
PDFs come from `examples/make_labels.py`; run it again after changing it and
commit the result.
