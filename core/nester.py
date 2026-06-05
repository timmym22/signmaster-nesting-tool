# core/nester.py
# Responsible for one thing only: arranging shapes onto sheets.
# Uses a maximal rectangles algorithm for efficient packing.
# Nothing in this file knows about the UI or PDF reading.

from models.shape import PlacedShape

# ── Sheet defaults ────────────────────────────────────────────────────────────

SHEET_W_IN       = 48.0
SHEET_H_IN       = 96.0
DEFAULT_PADDING_IN = 0.25
DEFAULT_SPACING_IN = 0.1969


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
        return f"FreeRect({self.x:.2f},{self.y:.2f} {self.w:.2f}x{self.h:.2f})"


# ── Maximal rectangles packing ────────────────────────────────────────────────

def _split_free_rects(free_rects, px, py, pw, ph):
    """
    After placing a shape at (px, py) with size (pw, ph),
    split all free rectangles that overlap with the placed shape
    into non-overlapping sub-rectangles covering the remaining space.
    """
    new_free = []

    for fr in free_rects:
        # Check if this free rect overlaps the placed shape
        if (px >= fr.x + fr.w or px + pw <= fr.x or
                py >= fr.y + fr.h or py + ph <= fr.y):
            # No overlap — keep as-is
            new_free.append(fr)
            continue

        # Overlaps — split into up to 4 sub-rectangles

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


def _pack_sheet(shapes, sheet_w, sheet_h, padding, spacing):
    """
    Pack as many shapes as possible onto one sheet.
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
        sw = shape.width_in  + spacing
        sh = shape.height_in + spacing

        # Find best free rect — Best Short Side Fit heuristic
        best_fr    = None
        best_score = float("inf")

        for fr in free_rects:
            if fr.can_fit(sw, sh):
                score = min(fr.w - sw, fr.h - sh)
                if score < best_score:
                    best_score = score
                    best_fr    = fr

        if best_fr is None:
            unplaced.append(shape)
            continue

        # Place at top-left of best free rect
        px, py = best_fr.x, best_fr.y

        placed.append(PlacedShape(
            shape       = shape,
            x_in        = px,
            y_in        = py,
            sheet_index = 0,
        ))

        # Split all overlapping free rects
        free_rects = _split_free_rects(free_rects, px, py, sw, sh)
        free_rects = _prune_contained(free_rects)

    return placed, unplaced


# ── Public interface ──────────────────────────────────────────────────────────

def nest_shapes(shapes,
                sheet_w=SHEET_W_IN,
                sheet_h=SHEET_H_IN,
                padding=DEFAULT_PADDING_IN,
                spacing=DEFAULT_SPACING_IN):
    """
    Arrange shapes onto as few sheets as possible using
    maximal rectangles bin packing.

    Returns a list of sheets, each a list of PlacedShape objects.
    """
    remaining = sorted(shapes,
                       key=lambda s: s.area(),
                       reverse=True)

    sheets = []

    while remaining:
        placed, remaining = _pack_sheet(
            remaining, sheet_w, sheet_h, padding, spacing)

        sheet_index = len(sheets)
        for ps in placed:
            ps.sheet_index = sheet_index

        sheets.append(placed)

        if not placed:
            break

    return sheets