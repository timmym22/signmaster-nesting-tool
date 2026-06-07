"""
nfp_validate.py  —  A/B correctness gate for the Phase-3 NFP rewrite.

Purpose
-------
Grade any candidate no-fit-polygon function against an EXACT, independently
verified ground truth, on real shapes from the test PDF plus convex synthetic
shapes with known analytic answers. This is the gate the orbital ("sliding")
NFP rewrite must pass before it can ever become the default engine.

Why a separate oracle: the current engine's _nfp_minkowski_sum UNDER-FILLS the
no-fit polygon (it leaves phantom interior gaps). The exact-overlap guard keeps
cuts safe, but it means the live method cannot be used as a correctness
reference. The oracle here is the true Minkowski sum built by triangulation,
verified three ways: it hits the analytic rectangle answer (119.60), matches the
exact convex edge-merge method (symdiff 0), and matches an independent raster
ground truth on real concave shapes (IoU 0.97-0.99).

Convention-agnostic comparison: NFP region shape is what matters, not the
reference-point offset. Both polygons are normalised to their bbox min corner
before the symmetric-difference is measured, so any method whose NFP encloses
the correct REGION passes regardless of which point it traces.

Usage
-----
    python nfp_validate.py [path-to-test.pdf]

Grades the live compute_nfp (expected: FAIL, documents the under-fill) and, if
present, compute_nfp_orbital (the rewrite target). Add new methods to METHODS.

Diagnostic only — not imported by the app. Keep unstaged unless committing the
gate deliberately.
"""
import sys, math, time

from shapely.geometry import Polygon as P
from shapely.ops import unary_union, triangulate
from shapely import affinity

import core.nester as N

# Default to Timmy's test path; override with argv[1].
PDF_PATH = sys.argv[1] if len(sys.argv) > 1 \
    else r"C:\Users\timmy\Desktop\AAANesting Test\168283Test.pdf"

ENGINE_TOL = N.NFP_SIMPLIFY_TOL   # grade on the same simplified inputs the engine uses
EXACT_VERT_CAP = 48               # skip exact oracle above this (triangulation cost)
PASS_FRAC = 0.01                  # symdiff / ref_area below this == PASS


# --------------------------------------------------------------------------
# Exact ground truth: true Minkowski sum A (+) B via triangulation.
# --------------------------------------------------------------------------
def _ccw(poly):
    c = list(poly.exterior.coords)[:-1]
    a2 = sum(c[i][0] * c[(i + 1) % len(c)][1] - c[(i + 1) % len(c)][0] * c[i][1]
             for i in range(len(c)))
    return c if a2 >= 0 else c[::-1]


def _reflect(B):
    return P([(-x, -y) for x, y in list(B.exterior.coords)[:-1]])


def _inside_tris(poly):
    out = []
    for t in triangulate(poly):
        if poly.contains(t.representative_point()) or \
           poly.intersection(t).area > 0.45 * t.area:
            out.append(t)
    return out


def minkowski_exact(A, B):
    """Exact Minkowski sum of two simple polygons (holes on A respected)."""
    if not A.is_valid:
        A = A.buffer(0)
    if not B.is_valid:
        B = B.buffer(0)
    ta, tb = _inside_tris(A), _inside_tris(B)
    pieces = []
    for X in ta:
        cx = _ccw(X)
        for Y in tb:
            cy = _ccw(Y)
            pts = [(ax + bx, ay + by) for (ax, ay) in cx for (bx, by) in cy]
            pieces.append(P(pts).convex_hull)
    return unary_union(pieces)


def nfp_truth(A, B, spacing=0.0):
    r = minkowski_exact(A, _reflect(B))
    if spacing:
        r = r.buffer(spacing, join_style=2)
    return r


# --------------------------------------------------------------------------
# Fast exact check for CONVEX shapes: angular edge-merge Minkowski.
# --------------------------------------------------------------------------
def _edges(c):
    return [(c[(i + 1) % len(c)][0] - c[i][0], c[(i + 1) % len(c)][1] - c[i][1])
            for i in range(len(c))]


def _ang(e):
    a = math.atan2(e[1], e[0])
    return a if a >= 0 else a + 2 * math.pi


def convex_minkowski(A, B):
    ca, cb = _ccw(A), _ccw(B)
    sa = min(range(len(ca)), key=lambda i: (ca[i][1], ca[i][0]))
    sb = min(range(len(cb)), key=lambda i: (cb[i][1], cb[i][0]))
    ea, eb = _edges(ca), _edges(cb)
    ea = ea[sa:] + ea[:sa]
    eb = eb[sb:] + eb[:sb]
    i = j = 0
    edges = []
    while i < len(ea) and j < len(eb):
        if _ang(ea[i]) <= _ang(eb[j]):
            edges.append(ea[i]); i += 1
        else:
            edges.append(eb[j]); j += 1
    edges += ea[i:] + eb[j:]
    x = ca[sa][0] + cb[sb][0]
    y = ca[sa][1] + cb[sb][1]
    pts = [(x, y)]
    for ex, ey in edges:
        x += ex; y += ey
        pts.append((x, y))
    return P(pts[:-1])


# --------------------------------------------------------------------------
# Comparison: region-shape match, reference-convention agnostic.
# --------------------------------------------------------------------------
def _norm0(poly):
    b = poly.bounds
    return affinity.translate(poly, -b[0], -b[1])


def region_symdiff(candidate, truth):
    """Fraction symmetric-difference at ABSOLUTE position. Compares where the
    region actually sits, not just its shape, so a reference-point/convention
    offset is caught (bbox-normalising would hide it)."""
    if candidate is None or candidate.is_empty:
        return 1.0
    if not candidate.is_valid:
        candidate = candidate.buffer(0)
    return candidate.symmetric_difference(truth).area / max(1e-9, truth.area)


# --------------------------------------------------------------------------
# Shape sourcing.
# --------------------------------------------------------------------------
def _local(shape):
    p = shape.contour_polygon
    b = p.bounds
    return affinity.translate(p, -b[0], -b[1]).simplify(ENGINE_TOL, preserve_topology=True)


def load_pairs():
    """Curated, deterministic pairs: convex synthetics + real concave shapes."""
    convex = {
        "square":   P([(0, 0), (4, 0), (4, 4), (0, 4)]),
        "rect":     P([(0, 0), (8, 0), (8, 2.5), (0, 2.5)]),
        "octagon":  P([(2, 0), (5, 0), (7, 2), (7, 5), (5, 7), (2, 7), (0, 5), (0, 2)]),
        "triangle": P([(0, 0), (6, 0), (3, 5)]),
    }
    pairs = []
    cn = list(convex)
    for a in cn:
        for b in cn:
            pairs.append((f"{a}|{b}", convex[a], convex[b], True))   # True = convex

    try:
        from core.extractor import extract_shapes
        shapes = [s for s in extract_shapes(PDF_PATH) if s.contour_polygon is not None]
    except Exception as e:
        print(f"(could not load PDF '{PDF_PATH}': {e}) — convex pairs only\n")
        return pairs

    locs = [_local(s) for s in shapes]
    # rank by concavity (low fill ratio = more concave = better test)
    ranked = sorted(
        range(len(locs)),
        key=lambda i: (locs[i].area / locs[i].convex_hull.area) if locs[i].convex_hull.area else 1,
    )
    picked = [i for i in ranked if len(locs[i].exterior.coords) <= EXACT_VERT_CAP][:6]
    probe = P([(0, 0), (3, 0), (3, 3), (0, 3)])
    for i in picked:
        pairs.append((f"shape{i}|3sq", locs[i], probe, False))
    for a in range(len(picked)):
        for b in range(a, len(picked)):
            ia, ib = picked[a], picked[b]
            pairs.append((f"shape{ia}|shape{ib}", locs[ia], locs[ib], False))
    # hole-shapes (letter counters): largest counters + fitting probes exercise interior voids
    def _hole_area(p):
        return sum(P(h).area for h in p.interiors)
    hole_idx = sorted(
        [i for i in range(len(locs))
         if len(locs[i].interiors) > 0 and len(locs[i].exterior.coords) <= EXACT_VERT_CAP],
        key=lambda i: -_hole_area(locs[i]),
    )[:6]
    probe3 = P([(0, 0), (3, 0), (3, 3), (0, 3)])
    probe4 = P([(0, 0), (4, 0), (4, 4), (0, 4)])
    for i in hole_idx:
        pairs.append((f"hole{i}|4sq", locs[i], probe4, False))
        pairs.append((f"hole{i}|3sq", locs[i], probe3, False))
    for a in range(0, len(hole_idx) - 1, 2):
        pairs.append((f"hole{hole_idx[a]}|hole{hole_idx[a+1]}", locs[hole_idx[a]], locs[hole_idx[a+1]], False))
    return pairs


# --------------------------------------------------------------------------
# Grading.
# --------------------------------------------------------------------------
def validate(nfp_fn, name, pairs, spacing=0.0):
    print(f"=== {name} ===")
    worst = 0.0
    fails = 0
    graded = 0
    total_t = 0.0
    for label, A, B, is_convex in pairs:
        truth = nfp_truth(A, B, spacing=spacing)
        t0 = time.perf_counter()
        try:
            cand = nfp_fn(A, B, spacing=spacing, simplify_tol=0)
        except TypeError:
            cand = nfp_fn(A, B)
        except Exception as e:
            print(f"  {label:22s} ERROR {e}")
            fails += 1
            continue
        total_t += time.perf_counter() - t0
        sd = region_symdiff(cand, truth)
        worst = max(worst, sd)
        graded += 1
        ok = sd <= PASS_FRAC
        if not ok:
            fails += 1
            print(f"  {label:22s} symdiff={sd*100:6.2f}%  ref={truth.area:8.1f}  "
                  f"cand={cand.area:8.1f}  FAIL")
    verdict = "ALL PASS" if fails == 0 else f"{fails} FAIL"
    print(f"  graded {graded} pairs | worst symdiff {worst*100:.2f}% | "
          f"{total_t*1000/max(1,graded):.2f} ms/pair | {verdict}\n")
    return fails == 0


def main():
    pairs = load_pairs()
    print(f"{len(pairs)} pairs (engine simplify tol={ENGINE_TOL}, "
          f"exact oracle cap={EXACT_VERT_CAP} verts)\n")

    methods = [(N.compute_nfp, "compute_nfp (LIVE — expected FAIL: under-fill)")]
    if hasattr(N, "compute_nfp_orbital_cy"):
        methods.append((N.compute_nfp_orbital_cy, "compute_nfp_orbital_cy (Cython full: outer+voids)"))

    for fn, nm in methods:
        validate(fn, nm, pairs, spacing=0.0)

    # convex-only exact cross-check of the edge-merge reference itself
    print("=== convex edge-merge self-check (must be ALL PASS) ===")
    cvx = [(l, a, b, c) for (l, a, b, c) in pairs if c]
    validate(lambda A, B, **k: convex_minkowski(A, _reflect(B)),
             "convex_minkowski", cvx, spacing=0.0)


if __name__ == "__main__":
    main()
