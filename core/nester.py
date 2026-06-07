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

_GEO_NFP_CACHE = {}
_SIMP_CACHE = {}
_GEOSIG = []


def _geo_sig(shape):
    cp = shape.contour_polygon
    if cp is None:
        return ("box", round(shape.width_in, 2), round(shape.height_in, 2))
    ext = tuple((round(x, 2), round(y, 2)) for x, y in cp.exterior.coords)
    ints = tuple(tuple((round(x, 2), round(y, 2)) for x, y in r.coords)
                 for r in cp.interiors)
    return hash((ext, ints))


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


# Prefer the compiled orbital NFP (exact + ~2x faster on large jobs, hole-aware
# so counter-voids are available). Fall back to the legacy GEOS Minkowski (holes
# stripped) if the compiled module is absent, so the app never hard-fails on a
# machine without the .pyd built.
try:
    from core import orbital_cy as _ORBITAL_CY  # noqa: F401
    _ORBITAL_AVAILABLE = True
except Exception:
    _ORBITAL_AVAILABLE = False


def _nfp_pair(keyA, polyA, keyB, polyB, spacing):
    iA, rA = keyA
    iB, rB = keyB
    gA = (_GEOSIG[iA], rA)
    gB = (_GEOSIG[iB], rB)
    k = (gA, gB)
    cached = _GEO_NFP_CACHE.get(k)
    if cached is not None:
        return cached
    sA = _SIMP_CACHE.get(gA)
    if sA is None:
        sA = polyA.simplify(NFP_SIMPLIFY_TOL, preserve_topology=True)
        if not _ORBITAL_AVAILABLE and sA.interiors:
            sA = ShapelyPolygon(sA.exterior.coords)
        _SIMP_CACHE[gA] = sA
    sB = _SIMP_CACHE.get(gB)
    if sB is None:
        sB = polyB.simplify(NFP_SIMPLIFY_TOL, preserve_topology=True)
        if not _ORBITAL_AVAILABLE and sB.interiors:
            sB = ShapelyPolygon(sB.exterior.coords)
        _SIMP_CACHE[gB] = sB
    if _ORBITAL_AVAILABLE:
        region = compute_nfp_orbital_cy(sA, sB, spacing=spacing, simplify_tol=0)
    else:
        region = compute_nfp(sA, sB, spacing=spacing, simplify_tol=0)
    _GEO_NFP_CACHE[k] = region
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


# Best-fit concave-tuck fill is enabled per-job by _nest_nfp for small jobs
# only (<=40 shapes), where it consolidates the tail without the global packing
# loss it causes on large jobs. Large jobs keep the original bottom-left fill.
_BESTFIT_FILL = False


def _nfp_place_guarded(local_poly, nfp_union, placed_prep, placed_bounds,
                       sheet_w, sheet_h, padding, spacing):
    cands = _nfp_candidates(local_poly, nfp_union, sheet_w, sheet_h, padding)
    if not cands:
        return None
    # Bottom-left first-valid: original production behaviour. Used for large
    # jobs (flag off) and always for the first piece of an empty sheet.
    if not _BESTFIT_FILL or not placed_bounds:
        for (x, y) in cands:
            if _nfp_exact_ok(local_poly, x, y, placed_prep, placed_bounds, spacing):
                return (x, y)
        return None
    # Best-fit concave-tuck scoring (small jobs only). Among valid spots, prefer
    # the one that grows the layout's bounding box the least -- this pulls a piece
    # into a neighbour's concave gap instead of starting fresh floor space.
    # Tie-break keeps the packed mass low (large y) so scrap consolidates at top.
    pminx = min(b[0] for b in placed_bounds); pminy = min(b[1] for b in placed_bounds)
    pmaxx = max(b[2] for b in placed_bounds); pmaxy = max(b[3] for b in placed_bounds)
    b = local_poly.bounds
    best = None
    seen = 0
    for (x, y) in cands:
        if not _nfp_exact_ok(local_poly, x, y, placed_prep, placed_bounds, spacing):
            continue
        nx0, ny0, nx1, ny1 = x + b[0], y + b[1], x + b[2], y + b[3]
        bw = max(pmaxx, nx1) - min(pminx, nx0)
        bh = max(pmaxy, ny1) - min(pminy, ny0)
        score = (round(bw * bh, 1), -round(min(pminy, ny0), 1), x)
        if best is None or score < best[0]:
            best = (score, x, y)
        seen += 1
        if seen >= 120:
            break
    return (best[1], best[2]) if best else None


def _nfp_place_lowest(local_poly, nfp_union, placed_prep, placed_bounds,
                      sheet_w, sheet_h, padding, spacing):
    """Bottom-left first-valid placement. Used by compaction to slide pieces
    straight down/left to tighten a sheet (best-fit scoring is for fill only)."""
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
            pos = _nfp_place_lowest(me["local"], u, opre, obnd,
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
    ki, shapes, sw, sh, pad, sp, rot, tol, use_bestfit = payload
    globals()['NFP_SIMPLIFY_TOL'] = tol
    globals()['_BESTFIT_FILL'] = use_bestfit
    global _GEOSIG, _GEO_NFP_CACHE, _SIMP_CACHE
    _GEOSIG = [_geo_sig(s) for s in shapes]
    _GEO_NFP_CACHE = {}
    _SIMP_CACHE = {}
    base = [(i, s) for i, s in enumerate(shapes)]
    order = sorted(base, key=_NFP_ORDERINGS[ki])
    sheets = _nfp_full_run(order, sw, sh, pad, sp, rot)
    score = (len(sheets), round(_nfp_last_density(sheets, sw, sh), 2))
    # Return only (index, x, y, rot) per shape so we don't pickle heavy
    # polygons back from workers; the main process rebuilds the layout.
    placements = [[(p["key"], p["x"], p["y"], p["rot"]) for p in sheet]
                  for sheet in sheets]
    return score, placements


def _nest_nfp(shapes, sheet_w, sheet_h, padding, spacing, rotation_mode):
    """Deterministic keep-best over several sort orders; returns list[list[PlacedShape]]."""
    tol = 0.10 if len(shapes) <= 40 else 0.5   # fine detail small, coarse large
    use_bestfit = len(shapes) <= 40            # best-fit fill: small jobs only
    payloads = [(ki, shapes, sheet_w, sheet_h, padding, spacing, rotation_mode, tol, use_bestfit)
                for ki in range(len(_NFP_ORDERINGS))]
    try:
        with ProcessPoolExecutor(max_workers=min(len(_NFP_ORDERINGS), os.cpu_count() or 1)) as ex:
            results = list(ex.map(_nfp_run_ordering, payloads))
    except Exception:
        results = [_nfp_run_ordering(p) for p in payloads]   # serial fallback
    best = min(results, key=lambda r: r[0])

    best_placements = best[1]
    result = []
    for si, sheet in enumerate(best_placements):
        locs = [(idx, x, y, rot, _nfp_local_poly(shapes[idx], rot))
                for (idx, x, y, rot) in sheet]
        if locs:
            minx = min(x + lp.bounds[0] for _, x, _, _, lp in locs)
            maxx = max(x + lp.bounds[2] for _, x, _, _, lp in locs)
            x_shift = (sheet_w - (maxx - minx)) / 2.0 - minx
        else:
            x_shift = 0.0
        sheet_list = []
        for idx, x, y, rot, lp in locs:
            sheet_list.append(PlacedShape(
                shape=shapes[idx], x_in=x + x_shift, y_in=y, sheet_index=si,
                rotated=rot, rotation_deg=180.0 if rot else 0.0))
        result.append(sheet_list)
    return result


# ===== Phase 3 (rewrite): orbital sliding NFP — DORMANT, outer loop only =====
import math as _orb_math
def _orb_aeq(a,b,t=1e-7): return abs(a-b)<t
def _orb_norm(v):
    l=_orb_math.hypot(v[0],v[1]); return (v[0]/l,v[1]/l) if l>1e-12 else (0.0,0.0)
def _orb_onseg(A,B,p):
    if _orb_aeq(A[0],B[0]) and _orb_aeq(A[1],B[1]): return False
    if _orb_aeq(A[0],B[0]) and _orb_aeq(p[0],A[0]):
        return (not _orb_aeq(p[1],B[1]) and not _orb_aeq(p[1],A[1]) and min(A[1],B[1])<p[1]<max(A[1],B[1]))
    if _orb_aeq(A[1],B[1]) and _orb_aeq(p[1],A[1]):
        return (not _orb_aeq(p[0],B[0]) and not _orb_aeq(p[0],A[0]) and min(A[0],B[0])<p[0]<max(A[0],B[0]))
    if (p[0]<A[0] and p[0]<B[0]) or (p[0]>A[0] and p[0]>B[0]): return False
    if (p[1]<A[1] and p[1]<B[1]) or (p[1]>A[1] and p[1]>B[1]): return False
    cr=(p[1]-A[1])*(B[0]-A[0])-(p[0]-A[0])*(B[1]-A[1])
    if abs(cr)>1e-7: return False
    dot=(p[0]-A[0])*(B[0]-A[0])+(p[1]-A[1])*(B[1]-A[1])
    if dot<0 or _orb_aeq(dot,0): return False
    L2=(B[0]-A[0])**2+(B[1]-A[1])**2
    if dot>L2 or _orb_aeq(dot,L2): return False
    return True
def _orb_pointdist(p,s1,s2,normal,infinite=False):
    normal=_orb_norm(normal); d=(normal[1],-normal[0])
    pd=p[0]*d[0]+p[1]*d[1]; s1d=s1[0]*d[0]+s1[1]*d[1]; s2d=s2[0]*d[0]+s2[1]*d[1]
    pn=p[0]*normal[0]+p[1]*normal[1]; s1n=s1[0]*normal[0]+s1[1]*normal[1]; s2n=s2[0]*normal[0]+s2[1]*normal[1]
    if not infinite:
        if (((pd<s1d or _orb_aeq(pd,s1d)) and (pd<s2d or _orb_aeq(pd,s2d))) or ((pd>s1d or _orb_aeq(pd,s1d)) and (pd>s2d or _orb_aeq(pd,s2d)))): return None
        if (_orb_aeq(pd,s1d) and _orb_aeq(pd,s2d)) and pn>s1n and pn>s2n: return min(pn-s1n,pn-s2n)
        if (_orb_aeq(pd,s1d) and _orb_aeq(pd,s2d)) and pn<s1n and pn<s2n: return -min(s1n-pn,s2n-pn)
    return -(pn-s1n+(s1n-s2n)*(s1d-pd)/(s1d-s2d))
def _orb_segdist(A,B,E,F,direction):
    nrm=(direction[1],-direction[0]); rev=(-direction[0],-direction[1])
    dA=A[0]*nrm[0]+A[1]*nrm[1]; dB=B[0]*nrm[0]+B[1]*nrm[1]; dE=E[0]*nrm[0]+E[1]*nrm[1]; dF=F[0]*nrm[0]+F[1]*nrm[1]
    cA=A[0]*direction[0]+A[1]*direction[1]; cB=B[0]*direction[0]+B[1]*direction[1]
    cE=E[0]*direction[0]+E[1]*direction[1]; cF=F[0]*direction[0]+F[1]*direction[1]
    ABmin=min(dA,dB); ABmax=max(dA,dB); EFmin=min(dE,dF); EFmax=max(dE,dF)
    if _orb_aeq(ABmax,EFmin) or _orb_aeq(ABmin,EFmax): return None
    if ABmax<EFmin or ABmin>EFmax: return None
    if (ABmax>EFmax and ABmin<EFmin) or (EFmax>ABmax and EFmin<ABmin): overlap=1
    else:
        mM=min(ABmax,EFmax); Mm=max(ABmin,EFmin); MM=max(ABmax,EFmax); mm=min(ABmin,EFmin)
        overlap=(mM-Mm)/(MM-mm) if (MM-mm)!=0 else 1
    cABE=(E[1]-A[1])*(B[0]-A[0])-(E[0]-A[0])*(B[1]-A[1]); cABF=(F[1]-A[1])*(B[0]-A[0])-(F[0]-A[0])*(B[1]-A[1])
    if _orb_aeq(cABE,0) and _orb_aeq(cABF,0):
        ABn=_orb_norm((B[1]-A[1],A[0]-B[0])); EFn=_orb_norm((F[1]-E[1],E[0]-F[0]))
        if abs(ABn[1]*EFn[0]-ABn[0]*EFn[1])<1e-7 and ABn[1]*EFn[1]+ABn[0]*EFn[0]<0:
            nd=ABn[1]*direction[1]+ABn[0]*direction[0]
            if _orb_aeq(nd,0): return None
            if nd<0: return 0.0
        return None
    ds=[]
    if _orb_aeq(dA,dE): ds.append(cA-cE)
    elif _orb_aeq(dA,dF): ds.append(cA-cF)
    elif EFmin<dA<EFmax:
        d=_orb_pointdist(A,E,F,rev)
        if d is not None and _orb_aeq(d,0):
            dBp=_orb_pointdist(B,E,F,rev,True)
            if dBp<0 or _orb_aeq(dBp*overlap,0): d=None
        if d is not None: ds.append(d)
    if _orb_aeq(dB,dE): ds.append(cB-cE)
    elif _orb_aeq(dB,dF): ds.append(cB-cF)
    elif EFmin<dB<EFmax:
        d=_orb_pointdist(B,E,F,rev)
        if d is not None and _orb_aeq(d,0):
            dBp=_orb_pointdist(A,E,F,rev,True)
            if dBp<0 or _orb_aeq(dBp*overlap,0): d=None
        if d is not None: ds.append(d)
    if ABmin<dE<ABmax:
        d=_orb_pointdist(E,A,B,direction)
        if d is not None and _orb_aeq(d,0):
            dBp=_orb_pointdist(F,A,B,direction,True)
            if dBp<0 or _orb_aeq(dBp*overlap,0): d=None
        if d is not None: ds.append(d)
    if ABmin<dF<ABmax:
        d=_orb_pointdist(F,A,B,direction)
        if d is not None and _orb_aeq(d,0):
            dBp=_orb_pointdist(E,A,B,direction,True)
            if dBp<0 or _orb_aeq(dBp*overlap,0): d=None
        if d is not None: ds.append(d)
    return min(ds) if ds else None
def _orb_slidedist(A,B,direction):
    dr=_orb_norm(direction); eA=A+[A[0]]; eB=B+[B[0]]; dist=None
    for i in range(len(eB)-1):
        for j in range(len(eA)-1):
            A1,A2=eA[j],eA[j+1]; B1,B2=eB[i],eB[i+1]
            if (_orb_aeq(A1[0],A2[0]) and _orb_aeq(A1[1],A2[1])) or (_orb_aeq(B1[0],B2[0]) and _orb_aeq(B1[1],B2[1])): continue
            d=_orb_segdist(A1,A2,B1,B2,dr)
            if d is not None and (dist is None or d<dist) and (d>0 or _orb_aeq(d,0)): dist=d
    return dist
def _orb_nfp_outer(A,B):
    minAi=min(range(len(A)),key=lambda i:A[i][1]); maxBi=max(range(len(B)),key=lambda i:B[i][1])
    ox=A[minAi][0]-B[maxBi][0]; oy=A[minAi][1]-B[maxBi][1]
    Bo=[(p[0]+ox,p[1]+oy) for p in B]; prev=None
    NFP=[(Bo[0][0],Bo[0][1])]; rx,ry=Bo[0]; sx,sy=rx,ry; nA,nB=len(A),len(B)
    for _ in range(10*(nA+nB)):
        T=[]
        for i in range(nA):
            ni=(i+1)%nA
            for j in range(nB):
                nj=(j+1)%nB
                if _orb_aeq(A[i][0],Bo[j][0]) and _orb_aeq(A[i][1],Bo[j][1]): T.append((0,i,j))
                elif _orb_onseg(A[i],A[ni],Bo[j]): T.append((1,ni,j))
                elif _orb_onseg(Bo[j],Bo[nj],A[i]): T.append((2,i,nj))
        V=[]
        for (ty,ai,bj) in T:
            vA=A[ai]; pA=A[(ai-1)%nA]; nA_=A[(ai+1)%nA]; vB=Bo[bj]; pB=Bo[(bj-1)%nB]; nB_=Bo[(bj+1)%nB]
            if ty==0:
                V+=[((pA[0]-vA[0],pA[1]-vA[1])),((nA_[0]-vA[0],nA_[1]-vA[1])),((vB[0]-pB[0],vB[1]-pB[1])),((vB[0]-nB_[0],vB[1]-nB_[1]))]
            elif ty==1:
                V+=[((vA[0]-vB[0],vA[1]-vB[1])),((pA[0]-vB[0],pA[1]-vB[1]))]
            elif ty==2:
                V+=[((vA[0]-vB[0],vA[1]-vB[1])),((vA[0]-pB[0],vA[1]-pB[1]))]
        tr=None; md=0.0
        for vec in V:
            if _orb_aeq(vec[0],0) and _orb_aeq(vec[1],0): continue
            if prev is not None and vec[1]*prev[1]+vec[0]*prev[0]<0:
                u=_orb_norm(vec); pu=_orb_norm(prev)
                if abs(u[1]*pu[0]-u[0]*pu[1])<1e-4: continue
            d=_orb_slidedist(A,Bo,vec); v2=vec[0]*vec[0]+vec[1]*vec[1]
            if d is None or d*d>v2: d=_orb_math.sqrt(v2)
            if d>md: md=d; tr=vec
        if tr is None or _orb_aeq(md,0): return None
        prev=tr; v2=tr[0]**2+tr[1]**2
        if md*md<v2 and not _orb_aeq(md*md,v2):
            sc=_orb_math.sqrt((md*md)/v2); tr=(tr[0]*sc,tr[1]*sc)
        rx+=tr[0]; ry+=tr[1]; Bo=[(p[0]+tr[0],p[1]+tr[1]) for p in Bo]
        if _orb_aeq(rx,sx) and _orb_aeq(ry,sy): break
        if any(_orb_aeq(rx,NFP[k][0]) and _orb_aeq(ry,NFP[k][1]) for k in range(len(NFP)-1)): break
        NFP.append((rx,ry))
    return NFP
def compute_nfp_orbital(A, B, spacing=0.0, simplify_tol=0.05):
    """Orbital (sliding) no-fit polygon — outer loop only. DORMANT: gate-validated
    exact on convex + hole-free concave shapes; not wired into nest_shapes.
    TODO: interior NFP loops (counter voids) + speed optimization before use."""
    if simplify_tol:
        A=A.simplify(simplify_tol,preserve_topology=True); B=B.simplify(simplify_tol,preserve_topology=True)
    ca=[(x,y) for x,y in list(A.exterior.coords)[:-1]]; cb=[(x,y) for x,y in list(B.exterior.coords)[:-1]]
    loop=_orb_nfp_outer(ca,cb)
    if loop is None or len(loop)<3: return _NFPPolygon()
    poly=_NFPPolygon(loop)
    if not poly.is_valid: poly=poly.buffer(0)
    if spacing: poly=poly.buffer(spacing, join_style=2)
    return poly

def compute_nfp_orbital_cy(A, B, spacing=0.0, simplify_tol=NFP_SIMPLIFY_TOL):
    """Full orbital NFP via the compiled Cython module: outer loop + interior
    counter-voids (B nesting inside A's holes). Gate-validated exact vs the
    triangulation oracle. DORMANT — not wired into nest_shapes yet."""
    from core import orbital_cy as _ocy
    if simplify_tol:
        A = A.simplify(simplify_tol, preserve_topology=True)
        B = B.simplify(simplify_tol, preserve_topology=True)
    ca = [(x, y) for x, y in list(A.exterior.coords)[:-1]]
    cb = [(x, y) for x, y in list(B.exterior.coords)[:-1]]
    outer = _ocy.nfp_outer(ca, cb)
    if not outer or len(outer) < 3:
        return _NFPPolygon()
    voids = []
    for h in A.interiors:
        hc = [(x, y) for x, y in list(h.coords)[:-1]]
        v = _ocy.nfp_inside(hc, cb)
        if v and len(v) >= 3:
            voids.append(v)
    poly = _NFPPolygon(outer, voids)
    if not poly.is_valid:
        poly = poly.buffer(0)
    # Align to compute_nfp's convention: the NFP is expressed as translations of
    # B's ORIGIN, but the orbital traces B's first vertex, so shift by -B[0].
    poly = _nfp_affinity.translate(poly, xoff=-cb[0][0], yoff=-cb[0][1])
    if spacing:
        poly = poly.buffer(spacing, join_style=2)
    return poly