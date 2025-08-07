#!/usr/bin/env python3
"""
Pack-and-Crop
-------------

• Crops white margins from every page of the input PDFs (or PDFs in a folder)
• Packs the cropped snippets onto as few sheets as possible
• Independently configurable:
    – Target page size (default A4)
    – **Page margin** around the sheet (default 5 mm)
    – **Spacing** between snippets (default 5 mm)
    – Rasterisation DPI (default 300)
"""

import sys, io, argparse, tempfile
import fitz                               # PyMuPDF
from pathlib import Path
from PIL import Image as PILImage
from rectpack import newPacker, MaxRectsBssf, SORT_AREA

# Ensure any leftover stub alias 'Image' (from earlier tests) exposes PIL API
if 'Image' in sys.modules and not hasattr(sys.modules['Image'], 'open'):
    sys.modules['Image'].__dict__.update({
        'open': PILImage.open,
        'frombytes': PILImage.frombytes,
        'Image': PILImage,
    })

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def mm_to_pt(mm: float) -> float:
    return mm * 72 / 25.4                 # 1 in = 25.4 mm, 1 in = 72 pt


def parse_pagesize(arg: str) -> tuple[float, float]:
    """
    Accept 'WxH' in mm (e.g. '210x297') or preset name ('A4', 'Letter').
    Returns (width_pt, height_pt).
    """
    PRESET = {
        "A4"    : (210, 297),
        "Letter": (215.9, 279.4),         # 8.5 in × 11 in
    }
    a = arg.lower()
    if a in (k.lower() for k in PRESET):
        w_mm, h_mm = PRESET[[k for k in PRESET if k.lower() == a][0]]
    elif "x" in arg:
        try:
            w_mm, h_mm = map(float, arg.lower().split("x"))
        except ValueError:
            raise argparse.ArgumentTypeError("Page size must be like 210x297 or A4")
    else:
        raise argparse.ArgumentTypeError("Unknown page size")
    return mm_to_pt(w_mm), mm_to_pt(h_mm)


def gather_pdfs(paths: list[str]) -> list[Path]:
    pdfs: list[Path] = []
    for p in paths:
        p_path = Path(p)
        if p_path.is_dir():
            pdfs.extend(sorted(p_path.glob("*.pdf")))
        else:
            pdfs.append(p_path)
    if not pdfs:
        raise SystemExit("❌ No PDF files found.")
    return pdfs


# --------------------------------------------------------------------------- #
# Core functions
# --------------------------------------------------------------------------- #

def crop_pages(pdf_paths, tmpdir, dpi, white_thresh):
    """Rasterise each page, crop near-white margins, save as PPM to be PIL-readable everywhere."""
    items = []
    for pdf in pdf_paths:
        doc = fitz.open(pdf)
        for i in range(doc.page_count):
            page  = doc.load_page(i)
            pix   = page.get_pixmap(dpi=dpi, alpha=False)
            mode  = "RGB" if pix.n >= 3 else "L"
            img   = PILImage.frombytes(mode, (pix.width, pix.height), pix.samples)
            bw    = img.convert("L").point(lambda x: 0 if x > white_thresh else 255, "1")
            bbox  = bw.getbbox()
            if bbox:
                img = img.crop(bbox)
            if img.mode != "RGB":
                img = img.convert("RGB")
            w_px, h_px = img.size
            w_pt, h_pt = w_px * 72 / dpi, h_px * 72 / dpi

            # Manually write PPM (P6) file to avoid relying on Pillow encoders
            out_img = Path(tmpdir) / f"{Path(pdf).stem}_p{i}.ppm"
            pixel_bytes = img.tobytes()
            header = f"P6\n{w_px} {h_px}\n255\n".encode("ascii")
            with open(out_img, "wb") as f:
                f.write(header)
                f.write(pixel_bytes)

            items.append((str(out_img), w_pt, h_pt))
    return items


def find_minimal_packing(items, eff_w, eff_h, spacing_pt):
    """Return (packer, rotate_used) that fits everything in as few sheets as possible."""
    for bins in range(1, len(items) + 1):
        for rotate in (True, False):  # prefer rotation where beneficial
            pk = newPacker(rotation=rotate, pack_algo=MaxRectsBssf, sort_algo=SORT_AREA)
            for idx, (_, w, h) in enumerate(items):
                pk.add_rect(w + spacing_pt, h + spacing_pt, rid=idx)
            for _ in range(bins):
                pk.add_bin(eff_w + spacing_pt, eff_h + spacing_pt)
            pk.pack()
            if len(pk.rect_list()) == len(items):
                return pk, rotate
    raise RuntimeError("Packing failed – snippets larger than page minus margins.")


def rect_rotated(rect, w0, h0, spacing_pt):
    w_r = rect.width  - spacing_pt
    h_r = rect.height - spacing_pt
    return abs(w_r - h0) < 0.1 and abs(h_r - w0) < 0.1


def _read_ppm(path: str) -> tuple[int, int, bytes]:
    """Parse a binary PPM (P6) file and return (width, height, rgb_bytes)."""
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"P6"):
        raise ValueError("Not a P6 PPM file")
    # Split header parts ignoring comments
    i = 2
    # skip whitespace
    while i < len(data) and data[i] in b" \t\r\n":
        i += 1
    parts = []
    while len(parts) < 3:
        # skip comments
        if i < len(data) and data[i] == ord('#'):
            while i < len(data) and data[i] not in b"\r\n":
                i += 1
            while i < len(data) and data[i] in b" \t\r\n":
                i += 1
            continue
        # read token
        start = i
        while i < len(data) and data[i] not in b" \t\r\n":
            i += 1
        parts.append(data[start:i])
        while i < len(data) and data[i] in b" \t\r\n":
            i += 1
    w = int(parts[0])
    h = int(parts[1])
    maxval = int(parts[2])
    if maxval != 255:
        raise ValueError("Unsupported PPM maxval")
    pixel_data = data[i:]
    expected = w * h * 3
    if len(pixel_data) != expected:
        raise ValueError("PPM size mismatch")
    return w, h, pixel_data


def render_pdf(packer, items, page_w, page_h, margin_pt, spacing_pt, rotate_used, output):
    out = fitz.open()
    for _ in packer:
        out.new_page(width=page_w, height=page_h)

    for bin_idx, abin in enumerate(packer):
        for rect in abin:
            x, y, _, _, rid = rect.x, rect.y, rect.width, rect.height, rect.rid
            img_path, w_orig, h_orig = items[rid]
            rotated = rotate_used and rect_rotated(rect, w_orig, h_orig, spacing_pt)
            cw, ch = (h_orig, w_orig) if rotated else (w_orig, h_orig)

            x0 = margin_pt + x
            y0 = page_h - (margin_pt + y + ch)
            rect_dest = fitz.Rect(x0, y0, x0 + cw, y0 + ch)

            # Read PPM and embed as PNG stream for universal PDF compatibility
            w_px, h_px, rgb = _read_ppm(img_path)
            pix = fitz.Pixmap(fitz.csRGB, w_px, h_px, rgb)
            out[bin_idx].insert_image(rect_dest, stream=pix.tobytes("png"), rotate=90 if rotated else 0)

    out.save(output)
    print(f"✅  {output} created – {len(packer)} sheet(s)")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(
        description="Crop & tightly pack PDFs onto the fewest pages."
    )
    parser.add_argument("paths", nargs="+", help="PDF file(s) OR folder(s) of PDFs")
    parser.add_argument("--pagesize", default="A4", type=parse_pagesize,
                        metavar="WxHmm|A4|Letter",
                        help="Target page size (default A4)")
    parser.add_argument("--page-margin", type=float, default=5, metavar="MM",
                        help="Margin around page edges in mm (default 5)")
    parser.add_argument("--spacing", type=float, default=1, metavar="MM",
                        help="Spacing between snippets in mm (default 5)")
    parser.add_argument("--dpi", type=int, default=300,
                        help="Rasterisation DPI (default 300)")
    parser.add_argument("--threshold", type=int, default=250, metavar="0-255",
                        help="Greyscale threshold >value treated as white (default 250)")
    parser.add_argument("-o", "--output", default="final_output.pdf",
                        help="Output PDF filename (default final_output.pdf)")
    args = parser.parse_args()

    page_w, page_h   = args.pagesize
    margin_pt        = mm_to_pt(args.page_margin)
    spacing_pt       = mm_to_pt(args.spacing)

    eff_w = page_w - 2 * margin_pt
    eff_h = page_h - 2 * margin_pt
    if eff_w <= 0 or eff_h <= 0:
        sys.exit("❌ Page margins too large for chosen page size.")

    pdf_files = gather_pdfs(args.paths)

    with tempfile.TemporaryDirectory() as tmpdir:
        items = crop_pages(pdf_files, tmpdir, args.dpi, args.threshold)
        if not items:
            sys.exit("⚠️  No content found.")
        packer, rotate_used = find_minimal_packing(items, eff_w, eff_h, spacing_pt)
        render_pdf(packer, items, page_w, page_h, margin_pt, spacing_pt,
                   rotate_used, args.output)

if __name__ == "__main__":
    main()
