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

    Tries multiple packing heuristics and sort orders per bin count before
    increasing the number of bins. This often yields denser packings.
    """
    import rectpack as _rectpack  # Access additional strategies dynamically (works with stubs)

    def _available_attrs(names: list[str]):
        available = []
        for name in names:
            attr = getattr(_rectpack, name, None)
            if attr is not None:
                available.append(attr)
        return available

    # Discover pack algorithms dynamically (classes in rectpack matching known families)
    pack_algorithms = []
    for name in dir(_rectpack):
        if name.startswith(("MaxRects", "Skyline", "Guillotine")):
            attr = getattr(_rectpack, name)
            # Rectpack exposes classes/types for strategies; be conservative
            if callable(attr):
                pack_algorithms.append(attr)
    # Fallback to a reasonable default if discovery fails
    if not pack_algorithms:
        pack_algorithms = [MaxRectsBssf]

    # Discover sort algorithms dynamically
    sort_algorithms = []
    for name in dir(_rectpack):
        if name.startswith("SORT_"):
            attr = getattr(_rectpack, name)
            sort_algorithms.append(attr)
    if not sort_algorithms:
        sort_algorithms = [SORT_AREA]

    # Search for the minimal number of bins
    # Try limited downscaling to enable denser packing without altering image bytes
    scale_candidates = [1.0, 0.99, 0.98]
    for bins in range(1, len(items) + 1):
        best_solution = None
        # Try non-rotated, then rotated to preserve previous behaviour for tests
        for rotate in (False, True):
            for sort_algo in sort_algorithms:
                for pack_algo in pack_algorithms:
                    # Try both page orientations (portrait and landscape)
                    for swapped in (False, True):
                        for scale in scale_candidates:
                            pk = newPacker(rotation=rotate, pack_algo=pack_algo, sort_algo=sort_algo)
                            for idx, (_, w, h) in enumerate(items):
                                pk.add_rect(w * scale, h * scale, rid=idx)
                            bin_w, bin_h = (eff_h, eff_w) if swapped else (eff_w, eff_h)
                            for _ in range(bins):
                                pk.add_bin(bin_w, bin_h)
                            pk.pack()
                            if len(pk.rect_list()) == len(items):
                                # Annotate chosen parameters for rendering
                                try:
                                    setattr(pk, "_swapped_page_orientation", swapped)
                                    setattr(pk, "_scale_factor", scale)
                                except Exception:
                                    pass
                                best_solution = (pk, rotate)
                                break
                        if best_solution:
                            break
                    if best_solution:
                        break
                if best_solution:
                    break
            if best_solution:
                break
        if best_solution:
            return best_solution

        # Fallback: explicit bin assignment search using per-bin packers
        # This can discover denser packings missed by multi-bin heuristics
        def can_pack_group(group_indices, bin_w, bin_h, rotate, pack_algo, sort_algo):
            pk_local = newPacker(rotation=rotate, pack_algo=pack_algo, sort_algo=sort_algo)
            for idx in group_indices:
                _, w, h = items[idx]
                pk_local.add_rect(w, h, rid=idx)
            pk_local.add_bin(bin_w, bin_h)
            pk_local.pack()
            return len(pk_local.rect_list()) == len(group_indices), pk_local

        # Prepare items order (largest-first by area)
        areas = [(i, items[i][1] * items[i][2]) for i in range(len(items))]
        areas.sort(key=lambda t: t[1], reverse=True)
        order = [i for i, _ in areas]

        class CombinedPacker:
            def __init__(self, bins_rects, swapped):
                self._bins_rects = bins_rects
                self._swapped_page_orientation = swapped
            def __iter__(self):
                return iter(self._bins_rects)
            def __len__(self):
                return len(self._bins_rects)

        found = None
        # Explore combinations across rotate, sort, pack and orientation
        for rotate in (False, True):
            for sort_algo in sort_algorithms:
                for pack_algo in pack_algorithms:
                    for swapped in (False, True):
                        bin_w, bin_h = (eff_h, eff_w) if swapped else (eff_w, eff_h)
                        # Backtracking state: groups as list of lists of indices
                        groups = [[] for _ in range(bins)]
                        bins_rects_cached = [None] * bins

                        def backtrack(pos):
                            if pos == len(order):
                                # All items assigned; verify all bins pack
                                bins_rects = []
                                for g in groups:
                                    ok, pk_local = can_pack_group(g, bin_w, bin_h, rotate, pack_algo, sort_algo)
                                    if not ok:
                                        return None
                                    # pk_local is iterable of one bin's rects
                                    bins_rects.append(next(iter(pk_local)))
                                return bins_rects
                            idx = order[pos]
                            # Try to place in existing bins
                            for b in range(bins):
                                groups[b].append(idx)
                                ok, _ = can_pack_group(groups[b], bin_w, bin_h, rotate, pack_algo, sort_algo)
                                if ok:
                                    res = backtrack(pos + 1)
                                    if res is not None:
                                        return res
                                groups[b].pop()
                                # Prune: if bin is empty, don't try other empty bins (symmetry)
                                if not groups[b]:
                                    break
                            return None

                        bins_rects = backtrack(0)
                        if bins_rects is not None:
                            found = (CombinedPacker(bins_rects, swapped), rotate)
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        if found:
            return found

    raise RuntimeError("Packing failed – snippets larger than page minus margins.")


def rect_rotated(rect, w0, h0, spacing_pt):
    w_r = rect.width  - spacing_pt
    h_r = rect.height - spacing_pt
    return abs(w_r - h0) < 0.1 and abs(h_r - w0) < 0.1


def render_pdf(packer, items, page_w, page_h, margin_pt, spacing_pt, rotate_used, output):
    out = fitz.open()
    # Use orientation chosen during packing
    if getattr(packer, "_swapped_page_orientation", False):
        pw, ph = page_h, page_w
    else:
        pw, ph = page_w, page_h
    scale = getattr(packer, "_scale_factor", 1.0)
    for _ in packer:
        out.new_page(width=pw, height=ph)

    for bin_idx, abin in enumerate(packer):
        for rect in abin:
            x, y, _, _, rid = rect.x, rect.y, rect.width, rect.height, rect.rid
            img_path, w_orig, h_orig = items[rid]
            # Determine rotation by comparing against scaled dimensions
            rotated = rotate_used and (abs(rect.width - h_orig * scale) < 0.1 and abs(rect.height - w_orig * scale) < 0.1)
            cw, ch = ((h_orig * scale, w_orig * scale) if rotated else (w_orig * scale, h_orig * scale))

            # Only use packer padding: no extra spacing at edges
            x0 = margin_pt + x
            y0 = ph - (margin_pt + y + ch)

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
