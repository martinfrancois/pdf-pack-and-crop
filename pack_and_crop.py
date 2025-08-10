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
from rectpack import newPacker, MaxRectsBssf, SORT_AREA
import rectpack as rp
from math import inf

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
    """Rasterise each page, crop near-white margins, save as PNG."""
    items = []
    for pdf in pdf_paths:
        doc = fitz.open(pdf)
        pdf_stem = Path(pdf).stem  # Get filename without extension
        for i in range(doc.page_count):
            page  = doc.load_page(i)
            pix   = page.get_pixmap(dpi=dpi, alpha=False)
            
            # Convert to grayscale for finding crop bounds
            # PyMuPDF can do this without PIL
            gray_pix = fitz.Pixmap(fitz.csGRAY, pix)
            
            # Find the bounding box of non-white pixels
            # We'll scan the image data to find bounds
            width, height = gray_pix.width, gray_pix.height
            samples = gray_pix.samples  # Raw pixel data
            
            # Find bounds - match PIL's behavior by treating pixels > white_thresh as white
            min_x, min_y = width, height
            max_x, max_y = -1, -1
            found_content = False
            
            for y in range(height):
                for x in range(width):
                    # Get pixel value (0-255)
                    pixel_value = samples[y * width + x]
                    if pixel_value <= white_thresh:  # Non-white pixel
                        found_content = True
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
                        max_x = max(max_x, x)
                        max_y = max(max_y, y)
            
            if found_content and min_x <= max_x and min_y <= max_y:
                # Slightly tighten crop by trimming a small border on all sides
                # This helps packing by shaving off near-white edges that survive thresholding
                trim_pts_per_side = 10  # points
                trim_px = max(0, int(round(trim_pts_per_side * dpi / 72)))
                if trim_px > 0:
                    min_x = min(max(min_x + trim_px, 0), width - 1)
                    min_y = min(max(min_y + trim_px, 0), height - 1)
                    max_x = max(min(max_x - trim_px, width - 1), 0)
                    max_y = max(min(max_y - trim_px, height - 1), 0)
                if min_x > max_x or min_y > max_y:
                    # Fallback to original bounds if over-trimmed
                    min_x, min_y = 0, 0
                    max_x, max_y = width - 1, height - 1

                # Crop the pixmap using PyMuPDF
                crop_rect = fitz.IRect(min_x, min_y, max_x + 1, max_y + 1)
                # Get the cropped pixmap by creating a new one from the cropped area
                cropped_pix = fitz.Pixmap(fitz.csRGB, crop_rect, False)
                cropped_pix.copy(pix, crop_rect)
                
                w_px, h_px = cropped_pix.width, cropped_pix.height
                w_pt, h_pt = w_px * 72 / dpi, h_px * 72 / dpi
                out_png = Path(tmpdir) / f"{pdf_stem}_{len(items)}.png"
                cropped_pix.save(str(out_png))
                cropped_pix = None  # Free memory
            else:
                # No crop needed or empty page, save original
                w_px, h_px = pix.width, pix.height
                w_pt, h_pt = w_px * 72 / dpi, h_px * 72 / dpi
                out_png = Path(tmpdir) / f"{pdf_stem}_{len(items)}.png"
                pix.save(str(out_png))
            
            items.append((str(out_png), w_pt, h_pt))
            
            # Clean up
            gray_pix = None
            pix = None
                
    return items


def _candidate_orders(items):
    # items: list[(path, w, h)]
    enriched = []
    for idx, (_, w, h) in enumerate(items):
        area = w * h
        max_side = max(w, h)
        min_side = min(w, h)
        peri = 2 * (w + h)
        ratio = (w / h) if h else inf
        enriched.append((idx, w, h, area, max_side, min_side, peri, ratio))

    original = [i for i, *_ in enriched]
    # Various heuristics
    by_area_desc = [i for i, *_ in sorted(enriched, key=lambda t: t[3], reverse=True)]
    by_area_asc  = [i for i, *_ in sorted(enriched, key=lambda t: t[3])]
    by_height_desc = [i for i, *_ in sorted(enriched, key=lambda t: t[2], reverse=True)]
    by_width_desc  = [i for i, *_ in sorted(enriched, key=lambda t: t[1], reverse=True)]
    by_maxside_desc = [i for i, *_ in sorted(enriched, key=lambda t: t[4], reverse=True)]
    by_minside_desc = [i for i, *_ in sorted(enriched, key=lambda t: t[5], reverse=True)]
    by_peri_desc    = [i for i, *_ in sorted(enriched, key=lambda t: t[6], reverse=True)]
    by_ratio_desc   = [i for i, *_ in sorted(enriched, key=lambda t: t[7], reverse=True)]
    by_ratio_asc    = [i for i, *_ in sorted(enriched, key=lambda t: t[7])]

    # Interleave large-small by area
    area_sorted = sorted(enriched, key=lambda t: t[3], reverse=True)
    interleave = []
    lo, hi = 0, len(area_sorted) - 1
    while lo <= hi:
        interleave.append(area_sorted[lo][0])
        lo += 1
        if lo <= hi:
            interleave.append(area_sorted[hi][0])
            hi -= 1

    return [
        original,
        by_area_desc,
        by_area_asc,
        by_height_desc,
        by_width_desc,
        by_maxside_desc,
        by_minside_desc,
        by_peri_desc,
        by_ratio_desc,
        by_ratio_asc,
        interleave,
    ]


def find_minimal_packing(items, eff_w, eff_h, spacing_pt):
    """Return (packer, rotate_used) that fits everything in as few sheets as possible.

    Tries multiple rectpack strategies because different heuristics can yield
    substantially better packings for the same set of rectangles.
    """
    # Build available algorithms dynamically to remain compatible with tests that
    # stub rectpack with a minimal surface.
    pack_algo_names = [
        "MaxRectsBssf",  # Best short side fit
        "MaxRectsBlsf",  # Best long side fit
        "MaxRectsBaf",   # Best area fit
        "MaxRectsBl",
        "SkylineBl",
        "SkylineBlWm",
        "SkylineMwf",
        "SkylineMwfWm",
        "SkylineMwfl",
        "SkylineMwflWm",
        "GuillotineBssfSas",
        "GuillotineBlsfSlas",
        "GuillotineBafMaxas",
    ]
    sort_algo_names = [
        "SORT_AREA",
        "SORT_PERI",
        "SORT_DIFF",
        "SORT_SSIDE",
        "SORT_LSIDE",
        "SORT_RATIO",
        "SORT_NONE",
    ]

    available_pack_algos = [getattr(rp, name) for name in pack_algo_names if hasattr(rp, name)]
    if not available_pack_algos:
        # Fallback to the one we know is imported
        available_pack_algos = [MaxRectsBssf]

    available_sort_algos = [getattr(rp, name) for name in sort_algo_names if hasattr(rp, name)]
    if not available_sort_algos:
        available_sort_algos = [SORT_AREA]

    orders = _candidate_orders(items)

    # Try increasing number of bins and a range of strategies for each
    for bins in range(1, len(items) + 1):
        for rotate in (False, True):
            for pack_algo in available_pack_algos:
                for sort_algo in available_sort_algos:
                    for order in orders:
                        pk = newPacker(rotation=rotate, pack_algo=pack_algo, sort_algo=sort_algo)
                        for orig_idx in order:
                            _, w, h = items[orig_idx]
                            pk.add_rect(w + spacing_pt, h + spacing_pt, rid=orig_idx)
                        # Expand bin by spacing so trailing-edge padding does not waste outer edges
                        bin_w = eff_w + spacing_pt
                        bin_h = eff_h + spacing_pt
                        for _ in range(bins):
                            pk.add_bin(bin_w, bin_h)
                        pk.pack()
                        try:
                            placed = len(pk.rect_list())
                        except Exception:
                            placed = sum(len(list(abin)) for abin in pk)
                        if placed == len(items):
                            return pk, rotate
    raise RuntimeError("Packing failed – snippets larger than page minus margins.")


def rect_rotated(rect, w0, h0, spacing_pt):
    w_r = rect.width  - spacing_pt
    h_r = rect.height - spacing_pt
    return abs(w_r - h0) < 0.1 and abs(h_r - w0) < 0.1


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

            # Only use packer padding: no extra spacing at edges
            x0 = margin_pt + x
            y0 = page_h - (margin_pt + y + ch)

            rect_dest = fitz.Rect(x0, y0, x0 + cw, y0 + ch)
            out[bin_idx].insert_image(rect_dest, filename=img_path, rotate=90 if rotated else 0)

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
