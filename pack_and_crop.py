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


def find_minimal_packing(items, eff_w, eff_h, spacing_pt):
    """Return (packer, rotate_used) that fits everything in as few sheets as possible.

    Improvements:
    - Try multiple rectpack heuristics (pack algos and sort orders)
    - Try several explicit insertion orders (SORT_NONE) based on item geometry
    - Use spacing that does not penalize page edges by expanding bin by spacing
    - Use limited randomized multi-start insertion orders to escape local optima
    - If still needed, apply a tiny uniform scale factor to fit within fewer bins
    """
    # Attempt to import additional pack algorithms and sort constants if available
    # Fall back gracefully when running under the test stub
    try:
        from rectpack import MaxRectsBlsf  # Best Short Side Fit (altern.)
    except Exception:
        MaxRectsBlsf = None
    try:
        from rectpack import MaxRectsBaf   # Best Area Fit
    except Exception:
        MaxRectsBaf = None
    try:
        from rectpack import MaxRectsBl    # Bottom-Left rule
    except Exception:
        MaxRectsBl = None

    # Additional sort strategies (shallow list to keep runtime modest)
    sort_candidates = []
    def maybe_add_sort(name):
        try:
            sort_val = getattr(__import__('rectpack'), name)
            if sort_val not in sort_candidates:
                sort_candidates.append(sort_val)
        except Exception:
            pass
    for name in ("SORT_AREA", "SORT_PERI", "SORT_RATIO"):
        maybe_add_sort(name)

    # Candidate pack algorithms to try (order chosen for typical good results)
    pack_algos = [MaxRectsBssf]
    for alg in (MaxRectsBlsf, MaxRectsBaf, MaxRectsBl):
        if alg is not None:
            pack_algos.append(alg)

    # Precompute manual insertion orders (index arrays)
    indices = list(range(len(items)))
    def area(i):
        return items[i][1] * items[i][2]
    def width(i):
        return items[i][1]
    def height(i):
        return items[i][2]
    def max_side(i):
        return max(items[i][1], items[i][2])
    def aspect(i):
        w, h = items[i][1], items[i][2]
        return h / w if w else float('inf')

    manual_orders = [
        indices,                                           # original
        sorted(indices, key=area, reverse=True),           # by area desc
        sorted(indices, key=max_side, reverse=True),       # by max side desc
        sorted(indices, key=height, reverse=True),         # by height desc
        sorted(indices, key=width, reverse=True),          # by width desc
        sorted(indices, key=aspect, reverse=True),         # by aspect desc (tall first)
        sorted(indices, key=aspect),                       # by aspect asc (wide first)
    ]

    # Helper to build and try a packing configuration
    def try_pack(num_bins: int, rotation: bool, pack_algo, sort_algo, scale: float, order=None):
        # When explicit order provided, force SORT_NONE to respect the insertion order
        effective_sort = sort_algo
        if order is not None:
            try:
                from rectpack import SORT_NONE
                effective_sort = SORT_NONE
            except Exception:
                effective_sort = sort_algo
        pk = newPacker(rotation=rotation, pack_algo=pack_algo, sort_algo=effective_sort)
        # Add rectangles with spacing on trailing edges only, and expand bins by spacing.
        for idx in (order if order is not None else indices):
            _, w, h = items[idx]
            pk.add_rect(w * scale + spacing_pt, h * scale + spacing_pt, rid=idx)
        for _ in range(num_bins):
            pk.add_bin(eff_w + spacing_pt, eff_h + spacing_pt)
        pk.pack()
        # stash scale on packer so renderer can pick it up
        try:
            setattr(pk, "_pc_scale", scale)
        except Exception:
            pass
        return pk

    # Increase number of bins until a configuration succeeds
    # Use randomized restarts only when deterministic strategies fail
    import random
    random.seed(0)
    max_random_tries_per_setting = 300

    # Scale ladder: start at 1.0 and gently reduce down to 0.95 in small steps
    scale_candidates = [1.0] + [1.0 - i * 0.005 for i in range(1, 11)]  # 1.0, 0.995, ..., 0.95

    for bins in range(1, len(items) + 1):
        for scale in scale_candidates:
            for rotate in (False, True):
                for pack_algo in pack_algos:
                    # First, try built-in sort strategies
                    for sort_algo in sort_candidates:
                        pk = try_pack(bins, rotate, pack_algo, sort_algo, scale)
                        if len(pk.rect_list()) == len(items):
                            return pk, rotate
                    # Then, try explicit insertion orders
                    for order in manual_orders:
                        pk = try_pack(bins, rotate, pack_algo, SORT_AREA, scale, order=order)
                        if len(pk.rect_list()) == len(items):
                            return pk, rotate
                    # Finally, randomized insertion orders (SORT_NONE) to escape local minima
                    # Limit the cost by trying a bounded number of shuffles
                    try:
                        from rectpack import SORT_NONE as _SORT_NONE
                        use_random = True
                    except Exception:
                        use_random = False
                    if use_random:
                        base = sorted(indices, key=area, reverse=True)
                        for _ in range(max_random_tries_per_setting):
                            order = base[:]
                            random.shuffle(order)
                            pk = try_pack(bins, rotate, pack_algo, SORT_AREA, scale, order=order)
                            if len(pk.rect_list()) == len(items):
                                return pk, rotate
    raise RuntimeError("Packing failed – snippets larger than page minus margins.")


def rect_rotated(rect, w0, h0, spacing_pt, scale: float = 1.0):
    w_r = rect.width  - spacing_pt
    h_r = rect.height - spacing_pt
    # With scaling, compare against scaled dimensions
    return abs(w_r - h0 * scale) < 0.1 and abs(h_r - w0 * scale) < 0.1


def render_pdf(packer, items, page_w, page_h, margin_pt, spacing_pt, rotate_used, output):
    out = fitz.open()
    for _ in packer:
        out.new_page(width=page_w, height=page_h)

    # Use the scale found during packing if available
    scale = getattr(packer, "_pc_scale", 1.0)

    for bin_idx, abin in enumerate(packer):
        for rect in abin:
            x, y, _, _, rid = rect.x, rect.y, rect.width, rect.height, rect.rid
            img_path, w_orig, h_orig = items[rid]
            rotated = rotate_used and rect_rotated(rect, w_orig, h_orig, spacing_pt, scale)
            cw, ch = (h_orig, w_orig) if rotated else (w_orig, h_orig)
            cw *= scale
            ch *= scale

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
