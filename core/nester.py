# core/nester.py
# Responsible for one thing only: arranging shapes onto sheets.
# Uses a maximal rectangles algorithm for efficient packing.
# Supports rotation modes: none, 90, 180, 270, free.
# Nothing in this file knows about the UI or PDF reading.

from models.shape import PlacedShape
from shapely.geometry import Polygon as ShapelyPolygon

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
ROTATION_MODES = ["none", "90°", "180°", "270°", "free"]


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

    if rotation_mode == "none":
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


def _build_candidate_positions(sheet_w, sheet_h, padding, spacing, shape, placed_polys):
    """
    Generate candidate positions using snap points from placed shapes.
    Prioritizes bottom-of-sheet first, fills left-to-right within each row,
    sorted by distance from horizontal center within each y level.
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


def _shapes_overlap(poly_a, poly_b, spacing):
    """
    Return True if poly_a and poly_b overlap or are within spacing inches of each other.
    """
    buffered = poly_b.buffer(spacing / 2.0)
    return poly_a.intersects(buffered)


def _pack_sheet_contour(shapes, sheet_w, sheet_h, padding, spacing):
    """
    Pack shapes onto one sheet using a two-pass strategy:
    Pass 1 — greedy row fill: build rows from the bottom up, filling each
              row left-to-right before starting a new row above it.
    Pass 2 — gap fill: try to fit any remaining unplaced shapes into gaps
              left by pass 1 using snap-point candidates.
    Falls back to bounding-box rectangle for shapes without contour_polygon.
    Returns (placed, unplaced).
    """
    placed_polys = []
    placed       = []
    remaining    = list(shapes)

    sheet_poly = ShapelyPolygon([
        (padding,           padding),
        (sheet_w - padding, padding),
        (sheet_w - padding, sheet_h - padding),
        (padding,           sheet_h - padding),
    ])

    def make_poly(shape, cx, cy):
        if shape.contour_polygon is not None:
            return _offset_polygon(shape.contour_polygon, cx, cy)
        return ShapelyPolygon([
            (cx,                  cy),
            (cx + shape.width_in, cy),
            (cx + shape.width_in, cy + shape.height_in),
            (cx,                  cy + shape.height_in),
        ])

    def try_place(shape, cx, cy):
        poly = make_poly(shape, cx, cy)
        if not sheet_poly.contains(poly):
            return None
        for pp in placed_polys:
            if _shapes_overlap(poly, pp, spacing):
                return None
        return poly

    # ── Pass 1: row-based fill bottom to top ─────────────────────────────────
    current_y    = sheet_h - padding  # start at bottom
    unplaced     = []

    while remaining:
        # Find the tallest shape that fits from remaining to set row height
        row_shapes   = []
        row_height   = 0
        still_remaining = []

        # Try to build a row: scan remaining shapes, place them left to right
        current_x = padding
        row_candidates = list(remaining)

        # Sort by height descending to set row height with tallest first
        row_candidates.sort(key=lambda s: s.height_in, reverse=True)

        placed_in_row = []
        for shape in row_candidates:
            if current_x + shape.width_in + spacing > sheet_w - padding:
                continue
            place_y = current_y - shape.height_in
            if place_y < padding:
                continue
            poly = try_place(shape, current_x, place_y)
            if poly is not None:
                placed_in_row.append((shape, current_x, place_y, poly))
                current_x += shape.width_in + spacing
                if shape.height_in > row_height:
                    row_height = shape.height_in

        if not placed_in_row:
            break

        # Commit the row — center it horizontally
        row_width = current_x - spacing - padding
        x_offset  = (sheet_w - row_width - padding) / 2.0

        for (shape, rx, ry, poly) in placed_in_row:
            centered_x = rx + x_offset - padding
            centered_x = max(padding, min(centered_x, sheet_w - padding - shape.width_in))
            final_poly = try_place(shape, centered_x, ry)
            if final_poly is None:
                final_poly = poly
                centered_x = rx

            placed_polys.append(final_poly)
            placed.append(PlacedShape(
                shape       = shape,
                x_in        = centered_x,
                y_in        = ry,
                sheet_index = 0,
                rotated     = False,
            ))
            remaining.remove(shape)

        current_y -= row_height + spacing

    # ── Pass 2: gap fill with snap points ────────────────────────────────────
    still_unplaced = []
    for shape in remaining:
        candidates = _build_candidate_positions(
            sheet_w, sheet_h, padding, spacing, shape, placed_polys)

        placed_this = False
        for (cx, cy) in candidates:
            poly = try_place(shape, cx, cy)
            if poly is not None:
                placed_polys.append(poly)
                placed.append(PlacedShape(
                    shape       = shape,
                    x_in        = cx,
                    y_in        = cy,
                    sheet_index = 0,
                    rotated     = False,
                ))
                placed_this = True
                break

        if not placed_this:
            still_unplaced.append(shape)

    return placed, still_unplaced


# ── Public interface ──────────────────────────────────────────────────────────

def nest_shapes(shapes,
                sheet_w=SHEET_W_IN,
                sheet_h=SHEET_H_IN,
                padding=DEFAULT_PADDING_IN,
                spacing=DEFAULT_SPACING_IN,
                rotation_mode="none",
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
                remaining, sheet_w, sheet_h, padding, spacing)
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