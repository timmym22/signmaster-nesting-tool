# core/nester.py
# Responsible for one thing only: arranging shapes onto sheets.
# Uses a maximal rectangles algorithm for efficient packing.
# Supports rotation modes: none, 90, 180, 270, free.
# Nothing in this file knows about the UI or PDF reading.

from models.shape import PlacedShape
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.prepared import prep

# ── Sheet defaults ────────────────────────────────────────────────────────────

SHEET_W_IN         = 48.0
SHEET_H_IN         = 96.0
DEFAULT_PADDING_IN  = 0.25
DEFAULT_SPACING_IN  = 0.1969

# Valid rotation modes
# none  — no rotation allowed (Coroplast / flute-direction materials)
# 90    — try original + 90° rotation
# 180   — try original + 180° rotation
# 270   — try original + 270° rotation
# free  — try all four orientations, pick best fit
ROTATION_MODES = ["none/180", "90°", "180°", "270°", "free"]


# ── Free rectangle tracking ───────────────────────────────────────────────────

class FreeRect:
    """Represents a rectangular region of free space on a sheet."""

    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def can_fit(self, w, h):
        return w <= self.w and h <= self.h

    def __repr__(self):
        return (f"FreeRect({self.x:.2f},{self.y:.2f} "
                f"{self.w:.2f}x{self.h:.2f})")


# ── Rotation helpers ──────────────────────────────────────────────────────────

def _candidate_sizes(shape, rotation_mode):
    """
    Return a list of (width, height, rotated) tuples to try for a shape
    based on the current rotation mode.

    rotated=True means the shape has been rotated 90 degrees from original.
    """
    w = shape.width_in
    h = shape.height_in

    if rotation_mode == "none/180":
        # No rotation — flute-safe for Coroplast
        return [(w, h, False)]

    elif rotation_mode == "90°":
        # Try original and 90° rotation
        return [(w, h, False), (h, w, True)]

    elif rotation_mode == "180°":
        # 180° is same bounding box as original for rectangles
        return [(w, h, False)]

    elif rotation_mode == "270°":
        # 270° same bounding box as 90° for rectangles
        return [(w, h, False), (h, w, True)]

    elif rotation_mode == "free":
        # Try all orientations — pick whichever fits best
        if abs(w - h) < 0.01:
            # Square — rotation makes no difference
            return [(w, h, False)]
        return [(w, h, False), (h, w, True)]

    # Fallback — no rotation
    return [(w, h, False)]


# ── Maximal rectangles packing ────────────────────────────────────────────────

def _split_free_rects(free_rects, px, py, pw, ph):
    """
    After placing a shape at (px, py) with size (pw, ph),
    split all free rectangles that overlap with the placed shape
    into non-overlapping sub-rectangles covering the remaining space.
    """
    new_free = []

    for fr in free_rects:
        # No overlap — keep as-is
        if (px >= fr.x + fr.w or px + pw <= fr.x or
                py >= fr.y + fr.h or py + ph <= fr.y):
            new_free.append(fr)
            continue

        # Left slice
        if px > fr.x:
            new_free.append(FreeRect(
                fr.x, fr.y,
                px - fr.x, fr.h
            ))

        # Right slice
        if px + pw < fr.x + fr.w:
            new_free.append(FreeRect(
                px + pw, fr.y,
                fr.x + fr.w - (px + pw), fr.h
            ))

        # Top slice
        if py > fr.y:
            new_free.append(FreeRect(
                fr.x, fr.y,
                fr.w, py - fr.y
            ))

        # Bottom slice
        if py + ph < fr.y + fr.h:
            new_free.append(FreeRect(
                fr.x, py + ph,
                fr.w, fr.y + fr.h - (py + ph)
            ))

    return new_free


def _prune_contained(free_rects):
    """
    Remove any free rectangle fully contained within another.
    Keeps the list clean and the algorithm efficient.
    """
    pruned = []
    for i, a in enumerate(free_rects):
        contained = False
        for j, b in enumerate(free_rects):
            if i == j:
                continue
            if (b.x <= a.x and b.y <= a.y and
                    b.x + b.w >= a.x + a.w and
                    b.y + b.h >= a.y + a.h and
                    (b.x < a.x or b.y < a.y or
                     b.x + b.w > a.x + a.w or
                     b.y + b.h > a.y + a.h)):
                contained = True
                break
        if not contained:
            pruned.append(a)
    return pruned


def _pack_sheet(shapes, sheet_w, sheet_h, padding, spacing, rotation_mode):
    """
    Pack as many shapes as possible onto one sheet.
    Tries rotation candidates based on rotation_mode.
    Returns (placed, unplaced).
    """
    free_rects = [FreeRect(
        x=padding,
        y=padding,
        w=sheet_w - 2 * padding,
        h=sheet_h - 2 * padding,
    )]

    placed   = []
    unplaced = []

    for shape in shapes:
        candidates = _candidate_sizes(shape, rotation_mode)

        best_fr      = None
        best_score   = float("inf")
        best_w       = None
        best_h       = None
        best_rotated = False

        # Try each candidate size and find the best fitting free rect
        for (cw, ch) in [(c[0] + spacing, c[1] + spacing)
                         for c in candidates]:
            for fr in free_rects:
                if fr.can_fit(cw, ch):
                    score = min(fr.w - cw, fr.h - ch)
                    if score < best_score:
                        best_score = score
                        best_fr    = fr
                        best_w     = cw
                        best_h     = ch
                        # Determine if this candidate is rotated
                        best_rotated = (
                            abs(cw - spacing - shape.height_in) < 0.01 and
                            abs(ch - spacing - shape.width_in)  < 0.01
                        )

        if best_fr is None:
            unplaced.append(shape)
            continue

        px, py = best_fr.x, best_fr.y

        placed.append(PlacedShape(
            shape       = shape,
            x_in        = px,
            y_in        = py,
            sheet_index = 0,
            rotated     = best_rotated,
        ))

        free_rects = _split_free_rects(
            free_rects, px, py, best_w, best_h)
        free_rects = _prune_contained(free_rects)

    return placed, unplaced


def _build_candidate_positions(sheet_w, sheet_h, padding, spacing, shape, placed_polys, rotation_mode="none/180"):
    """
    Generate candidate positions using bounding box snap points from
    already-placed shapes. Fast and reliable baseline.
    Sorted bottom-to-top, centered horizontally within each y level.
    """
    x_snaps = set()
    y_snaps = set()

    x_snaps.add(padding)
    y_snaps.add(sheet_h - padding - shape.height_in)

    for poly in placed_polys:
        bounds = poly.bounds
        x_snaps.add(bounds[0])
        x_snaps.add(bounds[2] + spacing)
        if bounds[0] - shape.width_in - spacing >= padding:
            x_snaps.add(bounds[0] - shape.width_in - spacing)
        y_snaps.add(bounds[1])
        y_snaps.add(bounds[1] - shape.height_in - spacing)

    candidates = []
    for y in sorted(y_snaps, reverse=True):
        if y < padding:
            continue
        if y + shape.height_in > sheet_h - padding:
            continue
        row = []
        for x in sorted(x_snaps):
            if x < padding:
                continue
            if x + shape.width_in > sheet_w - padding:
                continue
            row.append((x, y))
        sheet_center = sheet_w / 2.0
        row.sort(key=lambda c: abs(c[0] + shape.width_in / 2.0 - sheet_center))
        candidates.extend(row)

    return candidates


def _offset_polygon(contour_polygon, x_in, y_in):
    """
    Translate a contour polygon (already in local inch coordinates, origin 0,0)
    to its placement position (x_in, y_in) on the sheet.
    """
    coords = [(px + x_in, py + y_in)
              for px, py in contour_polygon.exterior.coords]
    return ShapelyPolygon(coords)


def _rotate_polygon_180(contour_polygon, ref_w=None, ref_h=None):
    """
    Rotate a contour polygon 180 degrees.
    If ref_w and ref_h are given (the source_rect width/height in inches),
    rotate around that box's center so the result stays aligned with the
    thumbnail image, which rotates around the source_rect center.
    Otherwise fall back to the polygon's own bounding box center.
    """
    if ref_w is not None and ref_h is not None:
        cx = ref_w / 2.0
        cy = ref_h / 2.0
    else:
        bounds = contour_polygon.bounds
        cx = (bounds[0] + bounds[2]) / 2.0
        cy = (bounds[1] + bounds[3]) / 2.0
    coords = [(2*cx - px, 2*cy - py) for px, py in contour_polygon.exterior.coords]
    return ShapelyPolygon(coords)


def _compute_nfp_candidates(placed_poly, new_poly, spacing):
    """
    Compute candidate positions where new_poly just touches placed_poly
    by using the placed polygon's buffered exterior vertices directly.
    Much faster than interpolation — uses only actual vertex points.
    Returns a list of (x, y) offset positions.
    """
    try:
        buffered  = placed_poly.buffer(spacing)
        new_bounds = new_poly.bounds
        ref_x = new_bounds[0]
        ref_y = new_bounds[1]

        candidates = []
        # Use the actual vertices of the buffered boundary — no interpolation
        coords = list(buffered.exterior.coords)
        for (px, py) in coords:
            cx = px - ref_x
            cy = py - ref_y
            candidates.append((cx, cy))
        return candidates
    except Exception:
        return []


def _shapes_overlap(poly_a, poly_b, spacing):
    """
    Return True if poly_a and poly_b overlap or are within spacing inches of each other.
    """
    buffered = poly_b.buffer(spacing / 2.0)
    return poly_a.intersects(buffered)


def _pack_sheet_contour(shapes, sheet_w, sheet_h, padding, spacing, rotation_mode="none/180"):
    """
    Bottom-up fill with contour awareness.

    Packs shapes directly toward the bottom of the sheet (largest y first),
    using real contour polygons for collision. No post-flip, so no overlaps
    are ever introduced. Then centers the packed block horizontally with an
    x-only shift (which never affects vertical relationships, so it stays
    overlap-free). Scrap material consolidates at the top of the sheet.

    Returns (placed, unplaced).
    """
    placed_buf    = []   # buffered placement polygons
    placed_bounds = []   # (minx, miny, maxx, maxy) for fast reject
    placed_prep   = []   # prepared geometry for fast intersects
    raw_placed    = []   # (shape, x, y, rotate180, local_poly)

    def make_local(shape, rotate180=False):
        if shape.contour_polygon is not None:
            poly = shape.contour_polygon
            if rotate180:
                ref_w = shape.source_rect.width  / 72.0
                ref_h = shape.source_rect.height / 72.0
                return _rotate_polygon_180(poly, ref_w, ref_h)
            return poly
        return ShapelyPolygon([
            (0, 0),
            (shape.width_in, 0),
            (shape.width_in, shape.height_in),
            (0, shape.height_in),
        ])

    def collides(cand_poly, cand_bounds):
        cminx, cminy, cmaxx, cmaxy = cand_bounds
        for i in range(len(placed_buf)):
            pb = placed_bounds[i]
            if cmaxx <= pb[0] or cminx >= pb[2] or cmaxy <= pb[1] or cminy >= pb[3]:
                continue
            if placed_prep[i].intersects(cand_poly):
                return True
        return False

    def fits(local_poly, w, h, x, y):
        if x < padding or x + w > sheet_w - padding:
            return False
        if y < padding or y + h > sheet_h - padding:
            return False
        lb   = local_poly.bounds
        cand = ShapelyPolygon([(px + x, py + y) for px, py in local_poly.exterior.coords])
        cb   = (lb[0] + x, lb[1] + y, lb[2] + x, lb[3] + y)
        return not collides(cand, cb)

    def best_position(shape, rotate180=False):
        w = shape.width_in
        h = shape.height_in
        local_poly = make_local(shape, rotate180)

        # Candidate X positions
        x_snaps = {padding}
        for b in placed_bounds:
            x_snaps.add(b[0])
            x_snaps.add(b[2] + spacing)
        x = padding
        while x + w <= sheet_w - padding:
            x_snaps.add(round(x, 3))
            x += 1.0

        # Candidate Y positions: bottom of sheet, above each placed shape,
        # plus a coarse vertical grid so shapes can find tighter settling spots
        y_snaps = {sheet_h - padding - h}
        for b in placed_bounds:
            y_snaps.add(b[1] - h - spacing)
            y_snaps.add(b[3] + spacing)
        gy = padding
        while gy <= sheet_h - padding - h:
            y_snaps.add(round(gy, 3))
            gy += 2.0

        x_list = sorted(c for c in x_snaps if padding <= c <= sheet_w - padding - w)
        # Largest y first = bottom of sheet first
        y_list = sorted((c for c in y_snaps if padding <= c <= sheet_h - padding - h),
                        reverse=True)

        for y in y_list:
            for cx in x_list:
                if fits(local_poly, w, h, cx, y):
                    return (cx, y, local_poly)
        return None

    unplaced = []

    for shape in shapes:
        result    = best_position(shape, rotate180=False)
        rotate180 = False
        if result is None and rotation_mode == "none/180":
            result    = best_position(shape, rotate180=True)
            rotate180 = True
        if result is None:
            unplaced.append(shape)
            continue

        cx, cy, local_poly = result
        cand = ShapelyPolygon([(px + cx, py + cy) for px, py in local_poly.exterior.coords])
        buf  = cand.buffer(spacing)
        placed_buf.append(buf)
        placed_bounds.append(buf.bounds)
        placed_prep.append(prep(buf))
        raw_placed.append((shape, cx, cy, rotate180, local_poly))

    # ── Center the packed block horizontally (x-only shift = overlap-safe) ───
    placed = []
    if raw_placed:
        minx = min(x for (_, x, _, _, _) in raw_placed)
        maxx = max(x + s.width_in for (s, x, _, _, _) in raw_placed)
        block_w = maxx - minx
        x_shift = (sheet_w - block_w) / 2.0 - minx

        for (shape, x, y, rotate180, local_poly) in raw_placed:
            new_x = x + x_shift
            new_x = max(padding, min(new_x, sheet_w - padding - shape.width_in))
            placed.append(PlacedShape(
                shape        = shape,
                x_in         = new_x,
                y_in         = y,
                sheet_index  = 0,
                rotated      = rotate180,
                rotation_deg = 180.0 if rotate180 else 0.0,
            ))

    return placed, unplaced


# ── Public interface ──────────────────────────────────────────────────────────

def nest_shapes(shapes,
                sheet_w=SHEET_W_IN,
                sheet_h=SHEET_H_IN,
                padding=DEFAULT_PADDING_IN,
                spacing=DEFAULT_SPACING_IN,
                rotation_mode="none/180",
                method="contour"):
    """
    Arrange shapes onto as few sheets as possible.

    Args:
        shapes        : list of Shape objects
        sheet_w       : sheet width in inches
        sheet_h       : sheet height in inches
        padding       : edge margin in inches
        spacing       : gap between shapes in inches
        rotation_mode : one of 'none', '90°', '180°', '270°', 'free'
                        'none' is safe for Coroplast / flute-direction materials

    Returns:
        A list of sheets, each a list of PlacedShape objects.
    """
    remaining = sorted(shapes,
                       key=lambda s: s.area(),
                       reverse=True)

    sheets = []

    while remaining:
        if method == "contour":
            placed, remaining = _pack_sheet_contour(
                remaining, sheet_w, sheet_h, padding, spacing, rotation_mode)
        else:
            placed, remaining = _pack_sheet(
                remaining, sheet_w, sheet_h,
                padding, spacing, rotation_mode)

        sheet_index = len(sheets)
        for ps in placed:
            ps.sheet_index = sheet_index

        sheets.append(placed)

        if not placed:
            break

    return sheets