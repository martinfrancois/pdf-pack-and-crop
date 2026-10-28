# Redacted shipping-label fixtures

These eleven PDFs came from the owner's shipping labels. The owner confirmed
that their personal details were already redacted and approved their public use
as regression fixtures on 2026-10-28. Their bytes match `test/label1.pdf` through
`test/label11.pdf` in historical revision
`1160b75ce25e5fcafc2b68ff55b0bfc75571edd0`.

Keep these files unchanged so they remain stable regression inputs. Add only
redacted, owner-approved documents to this fixture set. The generated examples
in `examples/labels` remain useful for checks with controlled label dimensions.

Run the realistic-label CLI checks with:

```sh
python -m pytest tests/test_redacted_labels.py
```

At 300 DPI on A4 with a 5 mm margin and 1 mm spacing, labels 1 and 5 fit on one
sheet. Labels 1 through 6 plus label 8 require six sheets: labels 2, 3, 4 and 6
each need a sheet of their own, and only two of labels 1, 5 and 8 fit together.
These expected counts come from the original integration cases. The full set
also checks that every cropped image survives packing unchanged, without
scaling, overlap or margin violations.
