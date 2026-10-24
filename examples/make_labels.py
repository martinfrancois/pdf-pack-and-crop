#!/usr/bin/env python3
"""Generate the synthetic label PDFs under examples/labels.

Each PDF is one A4 page with a single boxed label near the top left corner
and white space everywhere else. The text on the labels is invented. Run the
script again after changing it:

    python examples/make_labels.py

Pass a folder to write somewhere else. --count, --width and --height change
how many labels are made and their size in millimetres.
"""

import argparse
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

DEFAULT_DIR = Path(__file__).resolve().parent / "labels"
DEFAULT_COUNT = 6
DEFAULT_WIDTH_MM = 100
DEFAULT_HEIGHT_MM = 60
LEFT_MM = 25
TOP_MM = 20
# Knuth's multiplicative hash constant, spreads consecutive label numbers
# over very different bar patterns.
KNUTH_HASH = 2654435761


def draw_label(c, x, y, width, height, number):
    """Draw one label with its lower left corner at (x, y), all in points."""
    c.rect(x, y, width, height)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x + 5 * mm, y + height - 10 * mm, f"Sample label {number}")
    c.setFont("Helvetica", 9)
    lines = [
        "Ship to: Example Recipient",
        "1 Sample Street",
        "0000 Sampletown",
        f"Ref: SAMPLE-{number:04d}",
    ]
    for i, line in enumerate(lines):
        c.drawString(x + 5 * mm, y + height - (17 + 4.5 * i) * mm, line)
    # A bar pattern that looks like a barcode. The bit pattern depends on
    # the label number so every label is different.
    bits = f"{(number * KNUTH_HASH) % (1 << 40):040b}"
    bar_x = x + width - 37 * mm
    for i, bit in enumerate(bits):
        if bit == "1":
            c.rect(bar_x + i * 0.8 * mm, y + 5 * mm, 0.6 * mm, 12 * mm, stroke=0, fill=1)


def make_labels(out_dir, count=DEFAULT_COUNT, width_mm=DEFAULT_WIDTH_MM, height_mm=DEFAULT_HEIGHT_MM):
    """Write count label PDFs into out_dir and return their paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    page_w, page_h = A4
    paths = []
    for number in range(1, count + 1):
        path = out_dir / f"label{number}.pdf"
        c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
        c.setTitle(f"Sample label {number}")
        width, height = width_mm * mm, height_mm * mm
        draw_label(c, LEFT_MM * mm, page_h - TOP_MM * mm - height, width, height, number)
        c.showPage()
        c.save()
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", nargs="?", default=DEFAULT_DIR, type=Path)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--width", type=float, default=DEFAULT_WIDTH_MM, metavar="MM")
    parser.add_argument("--height", type=float, default=DEFAULT_HEIGHT_MM, metavar="MM")
    args = parser.parse_args()
    for path in make_labels(args.out_dir, args.count, args.width, args.height):
        print(path)


if __name__ == "__main__":
    main()
