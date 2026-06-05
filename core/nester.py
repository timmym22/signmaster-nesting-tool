# core/nester.py
# Responsible for one thing only: arranging shapes onto sheets.
# Uses a maximal rectangles algorithm for efficient packing.
# Supports rotation modes: none, 90, 180, 270, free.
# Nothing in this file knows about the UI or PDF reading.

from models.shape import PlacedShape

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


# ── Public interface ──────────────────────────────────────────────────────────

def nest_shapes(shapes,
                sheet_w=SHEET_W_IN,
                sheet_h=SHEET_H_IN,
                padding=DEFAULT_PADDING_IN,
                spacing=DEFAULT_SPACING_IN,
                rotation_mode="none"):
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