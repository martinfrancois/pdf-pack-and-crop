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
                # Get the cropped pixmap by creating a new one from the cropped area (compat mode)
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

    Tries multiple packing algorithms and sort strategies for each bin count
    to find a feasible solution as early as possible (lowest sheet count).
    Falls back gracefully if certain algorithms are unavailable (e.g. in tests).
    Additionally, explores multiple input orders (heuristics + random shuffles)
    under SORT_NONE to improve chances of tighter packings.
    Also tries both page orientations (portrait and landscape) and uses the
    one that yields the fewest sheets.
    """
    # ---------------------------- Custom shelf packer ---------------------------- #
    # Lightweight classes to mimic rectpack's interface
    class SimpleRect:
        def __init__(self, x, y, width, height, rid):
            self.x = x
            self.y = y
            self.width = width
            self.height = height
            self.rid = rid

    class SimpleBin:
        def __init__(self):
            self._rects: list[SimpleRect] = []
        def add(self, rect: SimpleRect):
            self._rects.append(rect)
        def __iter__(self):
            return iter(self._rects)

    class SimplePacker:
        def __init__(self, bins: list[SimpleBin], orientations: list[str]):
            self._bins = bins
            self._page_orientations = orientations
        def __iter__(self):
            return (b for b in self._bins)
        def __len__(self):
            return len(self._bins)
        def rect_list(self):
            return [r for b in self._bins for r in b]

    def try_shelf_pack(num_bins: int, page_w: float, page_h: float, allow_rotate: bool,
                        orders: list[list[int]], orientations: list[str]):
        # page_w/page_h are the effective packing area sizes (may include +spacing to avoid edge spacing)
        def pack_one_page(order: list[int], items_local: list[tuple], bins_needed: int) -> SimplePacker | None:
            bins: list[SimpleBin] = [SimpleBin() for _ in range(bins_needed)]
            # For each bin, maintain shelves: (y_offset_top, shelf_height, x_offset)
            shelves = [
                []  # list of dicts per page: [{'y': float, 'h': float, 'x': float}]
                for _ in range(bins_needed)
            ]
            used_heights = [0.0 for _ in range(bins_needed)]

            for idx in order:
                _, w0, h0 = items_local[idx]
                placed = False
                # Try to place on any existing page
                for p in range(bins_needed):
                    # Try both orientations if allowed; prefer non-rotated first
                    candidate_dims = [(w0, h0)]
                    if allow_rotate:
                        candidate_dims.append((h0, w0))
                    # Try to place on existing shelves first
                    for (cw, ch) in candidate_dims:
                        ew, eh = cw, ch
                        # Add trailing spacing by inflating block size
                        ew_eff = ew + spacing_pt
                        eh_eff = eh + spacing_pt
                        # Try existing shelves
                        for sh in shelves[p]:
                            if eh_eff <= sh['h']:
                                # fits height of shelf; check remaining width
                                if sh['x'] + ew_eff <= page_w + 1e-6:
                                    # place here
                                    rect = SimpleRect(sh['x'], sh['y'], ew_eff, eh_eff, idx)
                                    bins[p].add(rect)
                                    sh['x'] += ew_eff
                                    placed = True
                                    break
                        if placed:
                            break
                        # Try to grow last shelf height if any
                        if shelves[p]:
                            sh = shelves[p][-1]
                            new_h = max(sh['h'], eh_eff)
                            delta = new_h - sh['h']
                            if used_heights[p] + delta <= page_h + 1e-6 and sh['x'] + ew_eff <= page_w + 1e-6:
                                sh['h'] = new_h
                                used_heights[p] += delta
                                rect = SimpleRect(sh['x'], sh['y'], ew_eff, eh_eff, idx)
                                bins[p].add(rect)
                                sh['x'] += ew_eff
                                placed = True
                                break
                        # Start a new shelf if space remains
                        if used_heights[p] + eh_eff <= page_h + 1e-6:
                            y_top = used_heights[p]
                            shelves[p].append({'y': y_top, 'h': eh_eff, 'x': 0.0})
                            used_heights[p] += eh_eff
                            rect = SimpleRect(0.0, y_top, ew_eff, eh_eff, idx)
                            bins[p].add(rect)
                            shelves[p][-1]['x'] = ew_eff
                            placed = True
                            break
                    if placed:
                        break
                if not placed:
                    return None

            return SimplePacker(bins, orientations)

        # Try each order once for given bin count / page size
        for order in orders:
            packer = pack_one_page(order, items, num_bins)
            if packer is not None:
                return packer
        return None

    # Lazy import full rectpack namespace to probe available algorithms safely
    try:
        import rectpack as rp
    except Exception:  # pragma: no cover - should always be importable in app/tests
        rp = None

    # Candidate packing algorithms in priority order
    pack_algo_names_priority = [
        'MaxRectsBssf', 'MaxRectsBlsf', 'MaxRectsBl', 'MaxRectsBaf',
        'SkylineMwflWm', 'SkylineMwfl', 'SkylineMwfWm', 'SkylineMwf',
        'SkylineBlWm', 'SkylineBl',
        'GuillotineBssfLas', 'GuillotineBssfSlas',
        'GuillotineBlsfLas', 'GuillotineBlsfSlas',
        'GuillotineBafLas', 'GuillotineBafSlas',
    ]

    # Candidate sort algorithms in priority order
    sort_algo_names_priority = [
        'SORT_NONE', 'SORT_AREA', 'SORT_PERI', 'SORT_RATIO', 'SORT_SSIDE', 'SORT_LSIDE', 'SORT_DIFF'
    ]

    def resolve_algorithms():
        pack_algos = []
        sort_algos = []
        # Always include MaxRectsBssf via direct import to stay compatible with stubs
        pack_algos.append(MaxRectsBssf)
        sort_algos.append(SORT_AREA)
        if rp is not None:
            # Extend with any other available algorithms
            for name in pack_algo_names_priority:
                if hasattr(rp, name):
                    algo = getattr(rp, name)
                    if algo is not MaxRectsBssf and algo not in pack_algos:
                        pack_algos.append(algo)
            # Extend with available sort strategies
            for name in sort_algo_names_priority:
                if hasattr(rp, name):
                    algo = getattr(rp, name)
                    if algo is not SORT_AREA and algo not in sort_algos:
                        sort_algos.append(algo)
        return pack_algos, sort_algos

    pack_algos, sort_algos = resolve_algorithms()

    # Build candidate orders for SORT_NONE attempts
    import random
    idxs = list(range(len(items)))
    sizes = [(w, h) for _, w, h in items]
    areas = [w * h for w, h in sizes]

    def candidate_orders(max_random: int = 12):
        orders = []
        # Deterministic heuristics
        orders.append(sorted(idxs, key=lambda i: -areas[i]))
        orders.append(sorted(idxs, key=lambda i: -max(sizes[i])))
        orders.append(sorted(idxs, key=lambda i: -sizes[i][0]))  # width desc
        orders.append(sorted(idxs, key=lambda i: -sizes[i][1]))  # height desc
        orders.append(sorted(idxs, key=lambda i: (sizes[i][0], sizes[i][1]), reverse=True))
        orders.append(list(idxs))
        orders.append(list(reversed(idxs)))
        # Random shuffles
        rng = random.Random(1337)
        for _ in range(max_random):
            arr = list(idxs)
            rng.shuffle(arr)
            orders.append(arr)
        # Deduplicate while preserving order
        seen = set()
        uniq = []
        for ord_ in orders:
            t = tuple(ord_)
            if t not in seen:
                seen.add(t)
                uniq.append(ord_)
        return uniq

    orders_for_none = candidate_orders()

    def try_pack(bins, rotate, pack_algo, sort_algo, bin_sizes, orientations, order=None):
        pk = newPacker(rotation=rotate, pack_algo=pack_algo, sort_algo=sort_algo)
        if order is None:
            # Default path uses rectpack's own sorting
            for idx, (_, w, h) in enumerate(items):
                pk.add_rect(w + spacing_pt, h + spacing_pt, rid=idx)
        else:
            # Force user-defined order by using SORT_NONE and adding in that order
            for idx in order:
                _, w, h = items[idx]
                pk.add_rect(w + spacing_pt, h + spacing_pt, rid=idx)
        for (bw, bh) in bin_sizes:
            # Enlarge the bin by the spacing to avoid forcing spacing at the right/bottom edges
            pk.add_bin(bw, bh)
        # Attach page orientation hints for renderer
        try:
            setattr(pk, "_page_orientations", orientations[:len(bin_sizes)])
        except Exception:
            pass
        pk.pack()
        return pk

    # Two canonical orientations to try: portrait bins and landscape bins
    portrait_w = eff_w + spacing_pt
    portrait_h = eff_h + spacing_pt
    landscape_w = eff_h + spacing_pt
    landscape_h = eff_w + spacing_pt

    def bin_orientation_patterns(n):
        # Yield sequences of 'portrait'/'landscape' of length n, prioritized
        if n <= 0:
            return []
        patterns = []
        # All portrait, all landscape first
        patterns.append(["portrait"] * n)
        patterns.append(["landscape"] * n)
        # Then balanced mixes: alternate starting with portrait and landscape
        patterns.append(["portrait" if i % 2 == 0 else "landscape" for i in range(n)])
        patterns.append(["landscape" if i % 2 == 0 else "portrait" for i in range(n)])
        # Then for k from 1..n-1, k portrait then rest landscape, and vice versa
        for k in range(1, n):
            patterns.append(["portrait"] * k + ["landscape"] * (n - k))
            patterns.append(["landscape"] * k + ["portrait"] * (n - k))
        # Deduplicate while preserving order
        uniq = []
        seen = set()
        for pat in patterns:
            t = tuple(pat)
            if t not in seen:
                seen.add(t)
                uniq.append(pat)
        return uniq

    for bins in range(1, len(items) + 1):
        # Phase 0: Try our custom shelf packer first (fast) with a set of heuristic orders
        import random
        idxs = list(range(len(items)))
        sizes = [(w, h) for _, w, h in items]
        areas = [w * h for w, h in sizes]
        heuristic_orders = [
            sorted(idxs, key=lambda i: -areas[i]),
            sorted(idxs, key=lambda i: -max(sizes[i])),
            sorted(idxs, key=lambda i: -sizes[i][1]),  # height desc
            sorted(idxs, key=lambda i: -sizes[i][0]),  # width desc
            list(idxs),
            list(reversed(idxs)),
        ]
        rng0 = random.Random(4242)
        for _ in range(10):
            arr = list(idxs)
            rng0.shuffle(arr)
            heuristic_orders.append(arr)
        # Deduplicate
        seen_o = set()
        uniq_orders = []
        for o in heuristic_orders:
            t = tuple(o)
            if t not in seen_o:
                seen_o.add(t)
                uniq_orders.append(o)

        # Try uniform page orientations first for shelf packing
        shelf_attempts = [
            (['portrait'] * bins, portrait_w, portrait_h),
            (['landscape'] * bins, landscape_w, landscape_h),
        ]
        for orient_seq, bw, bh in shelf_attempts:
            sp = try_shelf_pack(bins, bw, bh, allow_rotate=True, orders=uniq_orders, orientations=orient_seq)
            if sp is not None:
                return sp, True

        for rotate in (True, False):
            # Phase 1: intensive search with MaxRectsBssf + SORT_NONE using many randomized orders,
            # limited orientation patterns (all portrait or all landscape). This often yields tighter packings.
            primary_pack_algos = [a for a in pack_algos if a is MaxRectsBssf] or [MaxRectsBssf]
            if rp is not None and hasattr(rp, 'SORT_NONE'):
                sort_none = getattr(rp, 'SORT_NONE')
            else:
                sort_none = None
            if sort_none is not None:
                # Build heavier set of orders
                import random
                heavy_orders = orders_for_none + []
                rng = random.Random(2025)
                for _ in range(100):
                    arr = list(range(len(items)))
                    rng.shuffle(arr)
                    heavy_orders.append(arr)
                # Deduplicate
                seen = set()
                uniq_orders = []
                for ord_ in heavy_orders:
                    t = tuple(ord_)
                    if t not in seen:
                        seen.add(t)
                        uniq_orders.append(ord_)
                for pack_algo in primary_pack_algos:
                    for orient_seq in ([['portrait'] * bins][0], [['landscape'] * bins][0]):
                        bin_sizes = [
                            (portrait_w, portrait_h) if o == 'portrait' else (landscape_w, landscape_h)
                            for o in orient_seq
                        ]
                        # Try native order first
                        pk = try_pack(bins, rotate, pack_algo, sort_none, bin_sizes, orientations=orient_seq)
                        if len(pk.rect_list()) == len(items):
                            return pk, rotate
                        # Then randomized orders
                        for ord_ in uniq_orders:
                            pk2 = try_pack(bins, rotate, pack_algo, sort_none, bin_sizes, orientations=orient_seq, order=ord_)
                            if len(pk2.rect_list()) == len(items):
                                return pk2, rotate

            # Phase 2: broader fallback over all algorithms, sorts, and mixed orientations
            for pack_algo in pack_algos:
                for sort_algo in sort_algos:
                    for orient_seq in bin_orientation_patterns(bins):
                        bin_sizes = [
                            (portrait_w, portrait_h) if o == "portrait" else (landscape_w, landscape_h)
                            for o in orient_seq
                        ]
                        # Native order
                        pk = try_pack(bins, rotate, pack_algo, sort_algo, bin_sizes, orientations=orient_seq)
                        if len(pk.rect_list()) == len(items):
                            return pk, rotate
                        if rp is not None and hasattr(rp, 'SORT_NONE') and sort_algo == getattr(rp, 'SORT_NONE'):
                            for ord_ in orders_for_none:
                                pk2 = try_pack(bins, rotate, pack_algo, sort_algo, bin_sizes, orientations=orient_seq, order=ord_)
                                if len(pk2.rect_list()) == len(items):
                                    return pk2, rotate
    raise RuntimeError("Packing failed – snippets larger than page minus margins.")


def rect_rotated(rect, w0, h0, spacing_pt):
    w_r = rect.width  - spacing_pt
    h_r = rect.height - spacing_pt
    return abs(w_r - h0) < 0.1 and abs(h_r - w0) < 0.1


def render_pdf(packer, items, page_w, page_h, margin_pt, spacing_pt, rotate_used, output):
    out = fitz.open()
    # Create pages. If the packer carries per-page orientation hints, honor them
    page_orients = getattr(packer, "_page_orientations", None)
    if page_orients is None:
        for _ in packer:
            out.new_page(width=page_w, height=page_h)
    else:
        for orient in page_orients:
            if orient == "landscape":
                out.new_page(width=page_h, height=page_w)
            else:
                out.new_page(width=page_w, height=page_h)

    for bin_idx, abin in enumerate(packer):
        for rect in abin:
            x, y, _, _, rid = rect.x, rect.y, rect.width, rect.height, rect.rid
            img_path, w_orig, h_orig = items[rid]
            rotated = rotate_used and rect_rotated(rect, w_orig, h_orig, spacing_pt)
            cw, ch = (h_orig, w_orig) if rotated else (w_orig, h_orig)

            # Only use packer padding: no extra spacing at edges
            x0 = margin_pt + x
            # Determine this page's height based on orientation
            if page_orients is not None and page_orients[bin_idx] == "landscape":
                this_page_h = page_w
            else:
                this_page_h = page_h
            y0 = this_page_h - (margin_pt + y + ch)

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
