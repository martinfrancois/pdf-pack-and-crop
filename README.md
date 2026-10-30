# PDF Pack‑and‑Crop - the paper‑saver for your PDFs

**Pack‑and‑Crop** squeezes many “small” PDF pages (package/letter labels, tickets, receipts, …) onto the fewest possible sheets.

* Auto‑crops white margins
* Packs as many snippets as fit on one page (optionally rotates them)
* Works with **any page size** (default A4)
* Independently configurable **outer page margin** and **spacing between snippets**
* Accepts **folders** (processes every `*.pdf` inside)

---

## ✨ Features

| Feature                                  | Default             | CLI Flag                              |
|------------------------------------------|---------------------|---------------------------------------|
| Page size (any)                          | A4 (210 × 297 mm)   | `--pagesize WxHmm`, `A4`, `Letter`, … |
| **Outer margin** (page border)           | 5 mm                | `--page-margin MM`                    |
| **Inner spacing** (gap between snippets) | 1 mm                | `--spacing MM`                        |
| Rasterisation                            | 300 DPI             | `--dpi N`                             |
| Auto‑rotation                            | Enabled when useful | *(automatic)*                         |
| Folder input                             | Yes                 | pass folder path                      |

---

## 📦 Requirements

Python 3.10 or newer. From a clone of this repository:

```bash
python -m pip install -r requirements.txt
```

This installs the runtime and test dependencies. Run the script with `python pack_and_crop.py`.

---

## 🔧 Usage

```bash
# 1. Quick start (defaults)
python pack_and_crop.py my1.pdf my2.pdf my3.pdf

# 2. Pack every PDF in a folder
python pack_and_crop.py labels/

# 3. Custom: Letter paper, 3 mm sheet margin, 8 mm spacing, 400 DPI
python pack_and_crop.py docs/ --pagesize Letter --page-margin 3 --spacing 8 --dpi 400 -o packed.pdf
```

| Flag                                                                                                    | Purpose                              |
|---------------------------------------------------------------------------------------------------------|--------------------------------------|
| <code>--pagesize WxHmm</code><br><code>--pagesize A4</code><br><code>--pagesize Letter</code>  | Target sheet size (mm or preset)     |
| <code>--page-margin MM</code>                                                                        | Empty border around sheet            |
| <code>--spacing MM</code>                                                                            | Gap between snippets                 |
| <code>--dpi N</code>                                                                                 | Rasterisation resolution             |
| <code>--threshold N</code>                                                                           | Greyscale value (>N = white) |
| <code>-o FILE</code>                                                                                 | Output filename                      |

Output → **`final_output.pdf`** (or the name you supply).

---

## Example

`examples/labels` holds six single‑page A4 PDFs. Each has one 100 × 60 mm sample label in the top left corner and white space everywhere else. The text on the labels is invented, and `examples/make_labels.py` generated them.

```bash
python pack_and_crop.py examples/labels -o packed.pdf
```

`packed.pdf` is one A4 sheet with four labels upright in a left column and the other two rotated by 90° beside them.

---

## How It Works

1. Each page is rasterised (`--dpi`, default 300).
2. Greyscale threshold (`--threshold`, default 250) finds the tight bounding‑box.
3. All rectangles (+spacing) feed **MaxRects**.

    * Script tries 1 sheet, 2 sheets, … until everything fits.
    * Tests layout **without** rotation, then **with** rotation.
4. Rotated snippets are drawn upright in the final PDF.

---


## Running Tests

Install the dependencies and run `pytest`:

```bash
python -m pip install -r requirements.txt
python -m pytest --cov=pack_and_crop --cov-report=term-missing --cov-report=json:coverage.json
```

The tests crop and pack the example labels. `requirements.txt` also has `reportlab`, which `examples/make_labels.py` needs to regenerate them.

The coverage report measures `pack_and_crop.py`. CI checks that the JSON report
contains executed lines for that module; a successful test count alone is not
enough to pass the coverage check.

`test/label1.pdf` through `test/label11.pdf` are redacted shipping labels supplied
by the repository owner and approved for public use. The CLI tests use these
realistic inputs alongside the generated examples to check label preservation,
packing, margins, spacing, and scale. See [`test/README.md`](test/README.md) for
fixture provenance.

## Contributing

1. Follow the existing code style and run the checks in [Running Tests](#running-tests).
2. Include before/after PDFs or screenshots in PRs.

## License

AGPL‑3.0, see [`LICENSE.md`](LICENSE.md).

Enjoy saving paper ♻️
