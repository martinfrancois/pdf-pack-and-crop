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
| **Inner spacing** (gap between snippets) | 5 mm                | `--spacing MM`                        |
| Rasterisation                            | 300 DPI             | `--dpi N`                             |
| Auto‑rotation                            | Enabled when useful | *(automatic)*                         |
| Folder input                             | Yes                 | pass folder path                      |

---

## 📦 Requirements

```bash
python -m pip install pymupdf pillow rectpack
````

---

## 🔧 Usage

```bash
# 1. Quick start (defaults)
./pack_and_crop.py my1.pdf my2.pdf my3.pdf

# 2. Pack every PDF in a folder
./pack_and_crop.py labels/

# 3. Custom: Letter paper, 3 mm sheet margin, 8 mm spacing, 400 DPI
./pack_and_crop.py docs/ --pagesize Letter --page-margin 3 --spacing 8 --dpi 400 -o packed.pdf
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

## How It Works

1. Each page is rasterised (`--dpi`, default 300).
2. Greyscale threshold (`--threshold`, default 250) finds the tight bounding‑box.
3. All rectangles (+spacing) feed **MaxRects**.

    * Script tries 1 sheet, 2 sheets, … until everything fits.
    * Tests layout **without** rotation, then **with** rotation.
4. Rotated snippets are drawn upright in the final PDF.

---


## Running Tests

Install test dependencies and run `pytest` with coverage:

```bash
python -m pip install -r requirements.txt
pytest -vv --cov=crop_and_pack.py --cov-report=term-missing
```

Integration tests need `pymupdf`, `Pillow` and `rectpack`.

## Contributing

1. Fork, hack, run `black *.py`.
2. Include before/after PDFs or screenshots in PRs.

Enjoy saving paper ♻️