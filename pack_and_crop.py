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
import rectpack as _rectpack_mod

# Attempt to import additional algorithms if available
try:
    from rectpack import (
        MaxRectsBlsf, MaxRectsBaf,
        SkylineBlWm, SkylineMwFl,
        GuillotineBssfSas, GuillotineBafSas,
    )
except Exception:  # pragma: no cover - optional
    MaxRectsBlsf = MaxRectsBaf = None
    SkylineBlWm = SkylineMwFl = None
    GuillotineBssfSas = GuillotineBafSas = None

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
                # Crop the pixmap using PyMuPDF
                # PyMuPDF crops by getting a sub-pixmap from a rectangle
                # PIL's getbbox returns (left, top, right, bottom) where right and bottom are exclusive
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


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def find_minimal_packing(items, eff_w, eff_h, spacing_pt):
    """Return (packer, rotate_used) that fits everything in as few sheets as possible.

    Improvements:
    - Try multiple item insertion orders to improve packing quality
    - Try multiple packing algorithms, falling back gracefully when unavailable
    - Try multiple sort algorithms provided by rectpack to influence placement
    - Allow a trailing-edge spacing to "hang" outside the effective area by
      expanding the bin by `spacing_pt` on width and height. This preserves
      spacing between items without wasting space at the page borders.
    - Try both portrait and landscape bin orientations and pick the first that
      fits with the fewest sheets. Also allow mixing orientations across bins.
    - Apply a tiny epsilon shrink to rects during packing to mitigate FP fringes.
    - Explore slight global downscaling of contents (render-time only) to reduce
      sheet count while preserving original image data embedded in the PDF.
    """
    # Precompute various item orders (indices) to try
    indices = list(range(len(items)))
    by_area_desc = sorted(indices, key=lambda i: items[i][1] * items[i][2], reverse=True)
    by_area_asc = list(reversed(by_area_desc))
    by_max_side_desc = sorted(indices, key=lambda i: max(items[i][1], items[i][2]), reverse=True)
    by_min_side_desc = sorted(indices, key=lambda i: min(items[i][1], items[i][2]), reverse=True)
    by_height_desc = sorted(indices, key=lambda i: items[i][2], reverse=True)
    by_width_desc = sorted(indices, key=lambda i: items[i][1], reverse=True)

    # Interleave large-small to reduce early fragmentation
    interleave_area = []
    lo, hi = 0, len(by_area_desc) - 1
    toggle = True
    while lo <= hi:
        interleave_area.append(by_area_desc[hi] if toggle else by_area_desc[lo])
        if toggle:
            hi -= 1
        else:
            lo += 1
        toggle = not toggle

    orders_to_try = [
        by_area_desc,
        interleave_area,
        by_max_side_desc,
        by_min_side_desc,
        by_height_desc,
        by_width_desc,
        by_area_asc,
        indices,  # original order as a last resort
    ]

    # Algorithms to try (filter out Nones)
    algos = [
        MaxRectsBssf,
        MaxRectsBlsf,
        MaxRectsBaf,
        SkylineMwFl,
        SkylineBlWm,
        GuillotineBssfSas,
        GuillotineBafSas,
    ]
    algos = [a for a in algos if a is not None]

    # Sort algorithms available in rectpack
    sort_algos = []
    for name in dir(_rectpack_mod):
        if name.startswith("SORT_"):
            sort_algos.append(getattr(_rectpack_mod, name))
    # Ensure deterministic preference
    if SORT_AREA in sort_algos:
        sort_algos.remove(SORT_AREA)
        sort_algos.insert(0, SORT_AREA)

    # Bin sizes to try: expanded first, then exact plus one-sided expansions
    expanded_w = eff_w + (spacing_pt if spacing_pt > 0 else 0)
    expanded_h = eff_h + (spacing_pt if spacing_pt > 0 else 0)

    portrait = (eff_w, eff_h)
    portrait_x = (expanded_w, eff_h)
    portrait_y = (eff_w, expanded_h)
    portrait_xy = (expanded_w, expanded_h)

    landscape = (eff_h, eff_w)
    landscape_x = (expanded_h, eff_w)
    landscape_y = (eff_h, expanded_w)
    landscape_xy = (expanded_h, expanded_w)

    def bin_patterns_for(bins_count: int):
        # Generate a small set of candidate per-bin orientation patterns
        base = []
        # All portrait variants
        base.append([portrait_xy] * bins_count)
        base.append([portrait] * bins_count)
        base.append([portrait_x] * bins_count)
        base.append([portrait_y] * bins_count)
        # All landscape variants
        base.append([landscape_xy] * bins_count)
        base.append([landscape] * bins_count)
        base.append([landscape_x] * bins_count)
        base.append([landscape_y] * bins_count)
        # Mixed patterns
        mix1 = []
        for i in range(bins_count):
            mix1.append(portrait_xy if i % 2 == 0 else landscape_xy)
        base.append(mix1)
        if bins_count >= 2:
            base.append([portrait_xy] + [landscape_xy] * (bins_count - 1))
            base.append([landscape_xy] + [portrait_xy] * (bins_count - 1))
        return base

    # Shrink epsilon to avoid failed fits due to floating point rounding
    EPS = min(0.25, spacing_pt * 0.1)  # up to 0.25pt, 10% of spacing

    # Explore slight global downscales; keep 1.0 first (no scale)
    scales_to_try = [1.0, 0.995, 0.99, 0.985, 0.98, 0.975, 0.97]

    for bins in range(1, len(items) + 1):
        # Prefer allowing rotation when minimizing the number of sheets
        for rotate in (True, False):
            for pack_algo in algos:
                for sort_algo in sort_algos:
                    for scale in scales_to_try:
                        for bin_list in bin_patterns_for(bins):
                            pk = newPacker(rotation=rotate, pack_algo=pack_algo, sort_algo=sort_algo)
                            for idx in range(len(items)):
                                _, w, h = items[idx]
                                # Pad only trailing edges (right and bottom), and shrink slightly
                                pk.add_rect(max(0.0, w * scale + spacing_pt - EPS),
                                            max(0.0, h * scale + spacing_pt - EPS), rid=idx)
                            for bw, bh in bin_list:
                                pk.add_bin(bw, bh)
                            pk.pack()
                            if len(pk.rect_list()) == len(items):
                                # Annotate packer with orientation and scale used for rendering
                                orientation_swapped = any(
                                    (_float_equal(bw, eff_h) and _float_equal(bh, eff_w)) or
                                    (_float_equal(bw, expanded_h) and _float_equal(bh, expanded_w)) or
                                    (_float_equal(bw, expanded_h) and _float_equal(bh, eff_w)) or
                                    (_float_equal(bw, eff_h) and _float_equal(bh, expanded_w))
                                    for bw, bh in bin_list
                                )
                                setattr(pk, "__bin_orientation_swapped__", orientation_swapped)
                                setattr(pk, "__global_scale__", scale)
                                return pk, rotate
    raise RuntimeError("Packing failed – snippets larger than page minus margins.")


def rect_rotated(rect, w0, h0, spacing_pt, scale: float = 1.0):
    w_r = rect.width  - spacing_pt
    h_r = rect.height - spacing_pt
    return (abs(w_r - h0 * scale) < 0.1 and abs(h_r - w0 * scale) < 0.1)


def render_pdf(packer, items, page_w, page_h, margin_pt, spacing_pt, rotate_used, output):
    # If packing was done with landscape-oriented bins, prefer to emit landscape pages
    use_landscape = bool(getattr(packer, "__bin_orientation_swapped__", False))
    if use_landscape and page_h > page_w:
        page_w, page_h = page_h, page_w

    scale = float(getattr(packer, "__global_scale__", 1.0))

    out = fitz.open()
    for _ in packer:
        out.new_page(width=page_w, height=page_h)

    for bin_idx, abin in enumerate(packer):
        for rect in abin:
            x, y, _, _, rid = rect.x, rect.y, rect.width, rect.height, rect.rid
            img_path, w_orig, h_orig = items[rid]
            rotated = rotate_used and rect_rotated(rect, w_orig, h_orig, spacing_pt, scale)
            cw0, ch0 = (h_orig, w_orig) if rotated else (w_orig, h_orig)
            cw, ch = cw0 * scale, ch0 * scale

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
