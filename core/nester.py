# core/nester.py
# Responsible for one thing only: arranging shapes onto sheets.
# Uses a maximal rectangles algorithm for efficient packing.
# Supports rotation modes: none, 90, 180, 270, free.
# Nothing in this file knows about the UI or PDF reading.

import os
from concurrent.futures import ProcessPoolExecutor

from models.shape import PlacedShape
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.prepared import prep
from shapely.geometry import Polygon as _NFPPolygon
from shapely.ops import unary_union as _nfp_unary_union
from shapely import affinity as _nfp_affinity

# ── Sheet defaults ────────────────────────────────────────────────────────────

SHEET_W_IN         = 48.0
SHEET_H_IN         = 96.0
DEFAULT_PADDING_IN  = 0.25
DEFAULT_SPACING_IN  = 0.1969
NFP_SIMPLIFY_TOL    = 0.5  # caps NFP polygon detail for speed; the exact-contour guard still prevents overlaps

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
    if method == "nfp":
        return _nest_nfp(shapes, sheet_w, sheet_h, padding, spacing, rotation_mode)

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


# ---------------------------------------------------------------------------
# Phase 3: No-Fit-Polygon generator (Minkowski-sum method via Shapely).
# DORMANT — not yet wired into the nesting pipeline. Do not call from
# placement code until Phase 3 Step 2.
#
# NFP(A, B) = A (+) (-B), the Minkowski sum of A with B reflected through the
# origin. Place B's reference point (its lower-left / first exterior coord)
# ON or OUTSIDE the returned region to guarantee B does not overlap A.
# Inside the region => overlap. Hole-aware: interior counters of A (e.g. the
# center of an O, the bowls of a B) become interior voids of the NFP, so a
# piece is allowed to nest inside another shape's counter.
# ---------------------------------------------------------------------------

def _nfp_reflect_origin(poly):
    """Return -poly: poly reflected through the origin (180 deg point reflection)."""
    return _NFPPolygon([(-x, -y) for x, y in poly.exterior.coords])


def _nfp_minkowski_sum(A, B):
    """
    Minkowski sum A (+) B for simple, possibly concave polygons, hole-aware on A.
    Computed by the vertex-sweep union method (robust via GEOS):
      union of A translated to each vertex of B, plus B translated to each
      vertex of every ring (exterior + interior) of A. Equals the Minkowski
      sum for simple polygons and preserves interior voids from A's holes.
    """
    b_coords = list(B.exterior.coords)[:-1]
    pieces = []
    for bx, by in b_coords:
        pieces.append(_nfp_affinity.translate(A, xoff=bx, yoff=by))
    # exterior ring of A
    for ax, ay in list(A.exterior.coords)[:-1]:
        pieces.append(_nfp_affinity.translate(B, xoff=ax, yoff=ay))
    # interior rings (holes) of A — keeps counter voids open in the result
    for ring in A.interiors:
        for ax, ay in list(ring.coords)[:-1]:
            pieces.append(_nfp_affinity.translate(B, xoff=ax, yoff=ay))
    return _nfp_unary_union(pieces)


def compute_nfp(A, B, spacing=0.0, simplify_tol=0.05):
    """
    No-fit polygon of B around A. Both A and B are Shapely polygons in inches
    (A may have interior holes). Returns a Shapely Polygon/MultiPolygon: B's
    reference point must lie ON or OUTSIDE this region to avoid overlapping A.

    spacing      : inflate the NFP by this clearance (inches) so "touching the
                   boundary" means exactly one spacing-width gap between pieces.
    simplify_tol : pre-simplify both polygons to cap vertex counts (curvy
                   bezier-sampled contours can carry hundreds of points). 0.05"
                   keeps shapes accurate while keeping the NFP bounded/fast.
    """
    if simplify_tol:
        A = A.simplify(simplify_tol, preserve_topology=True)
        B = B.simplify(simplify_tol, preserve_topology=True)
    neg_b = _nfp_reflect_origin(B)
    region = _nfp_minkowski_sum(A, neg_b)
    if spacing:
        region = region.buffer(spacing, join_style=2)
    return region


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3: TRUE NFP NESTING  (placement + compaction + backfill + keep-best)
# Uses compute_nfp() (from Step 1). 180-flip uses the source_rect center so the
# collision polygon stays aligned with the rotated thumbnail (canvas convention).
# Wired as method="nfp" in nest_shapes; "contour" and "bbox" are unchanged.
# ═══════════════════════════════════════════════════════════════════════════

from shapely.geometry import box as _nfp_box, MultiPolygon as _NFPMulti
from shapely.ops import unary_union as _nfp_union2
from shapely import affinity as _nfp_aff2

_NFP_PAIR_CACHE = {}


def _nfp_local_poly(shape, rot180):
    """Local contour polygon for a shape (hole-aware), 180-flipped around the
    source_rect center when rot180 so it stays aligned with the thumbnail."""
    poly = shape.contour_polygon
    if poly is None:
        return ShapelyPolygon([(0, 0), (shape.width_in, 0),
                               (shape.width_in, shape.height_in),
                               (0, shape.height_in)])
    if rot180:
        rw = shape.source_rect.width / 72.0
        rh = shape.source_rect.height / 72.0
        cx, cy = rw / 2.0, rh / 2.0
        ext = [(2 * cx - px, 2 * cy - py) for px, py in poly.exterior.coords]
        ints = [[(2 * cx - px, 2 * cy - py) for px, py in r.coords]
                for r in poly.interiors]
        return ShapelyPolygon(ext, ints)
    return poly


def _nfp_pair(keyA, polyA, keyB, polyB, spacing):
    """Cached NFP of B around A (A at origin)."""
    k = (keyA, keyB)
    cached = _NFP_PAIR_CACHE.get(k)
    if cached is not None:
        return cached
    region = compute_nfp(polyA, polyB, spacing=spacing, simplify_tol=NFP_SIMPLIFY_TOL)
    _NFP_PAIR_CACHE[k] = region
    return region


def _nfp_region_vertices(geom):
    pts = []
    if geom.is_empty:
        return pts
    polys = geom.geoms if isinstance(geom, _NFPMulti) else [geom]
    for p in polys:
        pts.extend(list(p.exterior.coords))
        for r in p.interiors:
            pts.extend(list(r.coords))
    return pts


def _nfp_candidates(local_poly, nfp_union, sheet_w, sheet_h, padding):
    """Bottom-most-then-leftmost-sorted candidate (x,y) translations for a shape
    whose local polygon is local_poly, given the union of placed NFPs."""
    b = local_poly.bounds
    tx_lo, tx_hi = padding - b[0], sheet_w - padding - b[2]
    ty_lo, ty_hi = padding - b[1], sheet_h - padding - b[3]
    if tx_lo > tx_hi or ty_lo > ty_hi:
        return []
    ifr = _nfp_box(tx_lo, ty_lo, tx_hi, ty_hi)
    valid = ifr if (nfp_union is None or nfp_union.is_empty) \
        else ifr.difference(nfp_union)
    if valid.is_empty:
        return []
    out = []
    for (x, y) in _nfp_region_vertices(valid):
        if x < tx_lo - 1e-6 or x > tx_hi + 1e-6 or y < ty_lo - 1e-6 or y > ty_hi + 1e-6:
            continue
        out.append((-y, x, x, y))   # sort key: max y (bottom), then min x (left)
    out.sort()
    return [(x, y) for _, _, x, y in out]


def _nfp_exact_ok(local_poly, x, y, placed_prep, placed_bounds, spacing):
    """Real-contour validation: reject if the placed shape would actually
    intersect any placed shape (guards against NFP simplification slack)."""
    cand = ShapelyPolygon([(px + x, py + y) for px, py in local_poly.exterior.coords],
                          [[(px + x, py + y) for px, py in r.coords]
                           for r in local_poly.interiors])
    cbuf = cand.buffer(spacing / 2.0)
    cb = cbuf.bounds
    for i in range(len(placed_prep)):
        pb = placed_bounds[i]
        if cb[2] <= pb[0] or cb[0] >= pb[2] or cb[3] <= pb[1] or cb[1] >= pb[3]:
            continue
        if placed_prep[i].intersects(cbuf):
            return False
    return True


def _nfp_place_guarded(local_poly, nfp_union, placed_prep, placed_bounds,
                       sheet_w, sheet_h, padding, spacing):
    for (x, y) in _nfp_candidates(local_poly, nfp_union, sheet_w, sheet_h, padding):
        if _nfp_exact_ok(local_poly, x, y, placed_prep, placed_bounds, spacing):
            return (x, y)
    return None


def _translate_geom(geom, dx, dy):
    return _nfp_aff2.translate(geom, xoff=dx, yoff=dy)


def _nfp_union_against(placed, rk, local_poly, spacing):
    if not placed:
        return None
    parts = []
    for p in placed:
        region = _nfp_pair(p["rk"], p["local"], rk, local_poly, spacing)
        parts.append(_translate_geom(region, p["x"], p["y"]))
    return _nfp_union2(parts)


def _nfp_prep_for(local_poly, x, y, spacing):
    cand = ShapelyPolygon([(px + x, py + y) for px, py in local_poly.exterior.coords],
                          [[(px + x, py + y) for px, py in r.coords]
                           for r in local_poly.interiors])
    g = cand.buffer(spacing / 2.0)
    return prep(g), g.bounds


def _nfp_fill_sheet(remaining, sheet_w, sheet_h, padding, spacing, rotation_mode):
    placed, pre, bnd, leftover = [], [], [], []
    for (key, shape) in remaining:
        best = None
        for rot in ([False, True] if rotation_mode == "none/180" else [False]):
            local = _nfp_local_poly(shape, rot)
            rk = (key, rot)
            u = _nfp_union_against(placed, rk, local, spacing)
            pos = _nfp_place_guarded(local, u, pre, bnd, sheet_w, sheet_h, padding, spacing)
            if pos is None:
                continue
            x, y = pos
            k = (-y, x, 0 if not rot else 1)
            if best is None or k < best[0]:
                best = (k, x, y, rot, local, rk)
        if best is None:
            leftover.append((key, shape))
            continue
        _, x, y, rot, local, rk = best
        placed.append({"key": key, "shape": shape, "x": x, "y": y,
                       "rot": rot, "local": local, "rk": rk})
        p, b = _nfp_prep_for(local, x, y, spacing)
        pre.append(p); bnd.append(b)
    return placed, pre, bnd, leftover


def _nfp_compact(placed, pre, bnd, sheet_w, sheet_h, padding, spacing, passes=8):
    for _ in range(passes):
        moved = 0.0
        order = sorted(range(len(placed)), key=lambda i: -placed[i]["y"])
        for i in order:
            me = placed[i]
            opre = [pre[j] for j in range(len(placed)) if j != i]
            obnd = [bnd[j] for j in range(len(placed)) if j != i]
            others = [placed[j] for j in range(len(placed)) if j != i]
            u = _nfp_union_against(others, me["rk"], me["local"], spacing)
            pos = _nfp_place_guarded(me["local"], u, opre, obnd,
                                     sheet_w, sheet_h, padding, spacing)
            if pos:
                nx, ny = pos
                if (ny > me["y"] + 1e-4) or (abs(ny - me["y"]) <= 1e-4 and nx < me["x"] - 1e-4):
                    moved += abs(nx - me["x"]) + abs(ny - me["y"])
                    me["x"], me["y"] = nx, ny
                    p, b = _nfp_prep_for(me["local"], nx, ny, spacing)
                    pre[i] = p; bnd[i] = b
        if moved < 1e-3:
            break
    return placed, pre, bnd


def _pack_sheet_nfp_once(remaining, sheet_w, sheet_h, padding, spacing, rotation_mode):
    placed, pre, bnd, leftover = _nfp_fill_sheet(
        remaining, sheet_w, sheet_h, padding, spacing, rotation_mode)
    if not placed:
        return placed, leftover
    for _ in range(4):
        placed, pre, bnd = _nfp_compact(
            placed, pre, bnd, sheet_w, sheet_h, padding, spacing)
        added = False
        while leftover:
            best = None
            for ri, (key, shape) in enumerate(leftover):
                for rot in ([False, True] if rotation_mode == "none/180" else [False]):
                    local = _nfp_local_poly(shape, rot)
                    rk = (key, rot)
                    u = _nfp_union_against(placed, rk, local, spacing)
                    pos = _nfp_place_guarded(local, u, pre, bnd,
                                             sheet_w, sheet_h, padding, spacing)
                    if pos is None:
                        continue
                    x, y = pos
                    k = (-y, x, 0 if not rot else 1)
                    if best is None or k < best[0]:
                        best = (k, ri, x, y, rot, local, rk)
            if best is None:
                break
            _, ri, x, y, rot, local, rk = best
            key, shape = leftover.pop(ri)
            placed.append({"key": key, "shape": shape, "x": x, "y": y,
                           "rot": rot, "local": local, "rk": rk})
            p, b = _nfp_prep_for(local, x, y, spacing)
            pre.append(p); bnd.append(b)
            added = True
        if not added:
            break
    return placed, leftover


def _nfp_full_run(keyed, sheet_w, sheet_h, padding, spacing, rotation_mode):
    sheets = []
    remaining = list(keyed)
    while remaining:
        placed, leftover = _pack_sheet_nfp_once(
            remaining, sheet_w, sheet_h, padding, spacing, rotation_mode)
        if not placed:
            break
        sheets.append(placed)
        remaining = leftover
    return sheets


def _nfp_last_density(sheets, sheet_w, sheet_h):
    if not sheets:
        return 0.0
    last = sheets[-1]
    used = sum(_nfp_aff2.translate(p["local"], xoff=p["x"], yoff=p["y"]).area for p in last)
    return used / (sheet_w * sheet_h) * 100.0


def _sk_perim(s): return s.contour_polygon.length if s.contour_polygon else 0.0
def _sk_carea(s): return s.contour_polygon.area if s.contour_polygon else s.area()
def _ord_0(ks):  return -max(ks[1].width_in, ks[1].height_in)
def _ord_1(ks):  return -ks[1].area()
def _ord_2(ks):  return -ks[1].height_in
def _ord_3(ks):  return -ks[1].width_in
def _ord_4(ks):  return -_sk_perim(ks[1])
def _ord_5(ks):  return -min(ks[1].width_in, ks[1].height_in)
def _ord_6(ks):  return -(ks[1].area() * ks[1].height_in)
def _ord_7(ks):  return (-round(ks[1].height_in, 1), -ks[1].width_in)
def _ord_8(ks):  return (-round(ks[1].width_in, 1), -ks[1].height_in)
def _ord_9(ks):  return -_sk_carea(ks[1])
def _ord_10(ks): return (-round(max(ks[1].width_in, ks[1].height_in), 1), -ks[1].area())
def _ord_11(ks): return (-round(_sk_perim(ks[1]), 0), -ks[1].height_in)
_NFP_ORDERINGS = [_ord_0,_ord_1,_ord_2,_ord_3,_ord_4,_ord_5,
                  _ord_6,_ord_7,_ord_8,_ord_9,_ord_10,_ord_11]


def _nfp_run_ordering(payload):
    ki, shapes, sw, sh, pad, sp, rot, tol = payload
    globals()['NFP_SIMPLIFY_TOL'] = tol
    base = [(i, s) for i, s in enumerate(shapes)]
    order = sorted(base, key=_NFP_ORDERINGS[ki])
    _NFP_PAIR_CACHE.clear()
    sheets = _nfp_full_run(order, sw, sh, pad, sp, rot)
    return (len(sheets), round(_nfp_last_density(sheets, sw, sh), 2)), sheets


def _nest_nfp(shapes, sheet_w, sheet_h, padding, spacing, rotation_mode):
    """Deterministic keep-best over several sort orders; returns list[list[PlacedShape]]."""
    tol = 0.10 if len(shapes) <= 40 else 0.5   # fine detail small, coarse large
    payloads = [(ki, shapes, sheet_w, sheet_h, padding, spacing, rotation_mode, tol)
                for ki in range(len(_NFP_ORDERINGS))]
    try:
        with ProcessPoolExecutor(max_workers=min(len(_NFP_ORDERINGS), os.cpu_count() or 1)) as ex:
            results = list(ex.map(_nfp_run_ordering, payloads))
    except Exception:
        results = [_nfp_run_ordering(p) for p in payloads]   # serial fallback
    best = min(results, key=lambda r: r[0])
    sheets = best[1]

    # Convert to PlacedShape, with horizontal block-centering per sheet (x-only,
    # overlap-safe) so scrap consolidates symmetrically; bottom-up keeps scrap on top.
    result = []
    for si, placed in enumerate(sheets):
        if placed:
            minx = min(p["x"] + p["local"].bounds[0] for p in placed)
            maxx = max(p["x"] + p["local"].bounds[2] for p in placed)
            block_w = maxx - minx
            x_shift = (sheet_w - block_w) / 2.0 - minx
        else:
            x_shift = 0.0
        sheet_list = []
        for p in placed:
            nx = p["x"] + x_shift
            sheet_list.append(PlacedShape(
                shape=p["shape"],
                x_in=nx,
                y_in=p["y"],
                sheet_index=si,
                rotated=p["rot"],
                rotation_deg=180.0 if p["rot"] else 0.0,
            ))
        result.append(sheet_list)
    return result