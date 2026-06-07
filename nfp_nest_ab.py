"""
nfp_nest_ab.py — whole-nest A/B: legacy GEOS NFP (holes stripped) vs the
compiled orbital NFP (holes kept -> counter-voids), over the full keep-best
sort-ordering search. Read-only: does NOT modify the nesting pipeline.

    python nfp_nest_ab.py [path-to-test.pdf]
"""
import sys, time
sys.path.insert(0, ".")
import core.nester as nester
from core.nester import _nfp_run_ordering, _nfp_local_poly, _NFP_ORDERINGS, ShapelyPolygon
from core.extractor import extract_shapes
from shapely import affinity
from shapely.geometry import Polygon as P

PDF = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\timmy\Desktop\AAANesting Test\LargeTestCutOnly.pdf"
SW, SH, PAD, SP, ROT = 48, 96, 0.25, 0.25, "none/180"

_orig_pair = nester._nfp_pair

def _pair_legacy(keyA, polyA, keyB, polyB, spacing):
    return _orig_pair(keyA, polyA, keyB, polyB, spacing)

def _pair_orbital(keyA, polyA, keyB, polyB, spacing):
    iA, rA = keyA; iB, rB = keyB
    gA = (nester._GEOSIG[iA], rA); gB = (nester._GEOSIG[iB], rB); k = (gA, gB)
    c = nester._GEO_NFP_CACHE.get(k)
    if c is not None: return c
    sA = nester._SIMP_CACHE.get(gA)
    if sA is None:
        sA = polyA.simplify(nester.NFP_SIMPLIFY_TOL, preserve_topology=True)
        nester._SIMP_CACHE[gA] = sA
    sB = nester._SIMP_CACHE.get(gB)
    if sB is None:
        sB = polyB.simplify(nester.NFP_SIMPLIFY_TOL, preserve_topology=True)
        nester._SIMP_CACHE[gB] = sB
    region = nester.compute_nfp_orbital_cy(sA, sB, spacing=spacing, simplify_tol=0)
    nester._GEO_NFP_CACHE[k] = region
    return region

def keepbest(shapes):
    tol = 0.10 if len(shapes) <= 40 else 0.5
    results = []
    for ki in range(len(_NFP_ORDERINGS)):
        score, pl = _nfp_run_ordering((ki, shapes, SW, SH, PAD, SP, ROT, tol))
        results.append((score, pl))
    return min(results, key=lambda r: r[0])

def audit(pl, shapes):
    overlaps = 0; counters = 0; total = 0
    for sheet in pl:
        polys = []
        for (idx, x, y, rot) in sheet:
            total += 1
            polys.append((idx, affinity.translate(_nfp_local_poly(shapes[idx], rot), x, y)))
        for a in range(len(polys)):
            for b in range(a + 1, len(polys)):
                if polys[a][1].intersection(polys[b][1]).area > 0.01:
                    overlaps += 1
        for ia, pa in polys:
            for ib, pb in polys:
                if ia == ib: continue
                if any(P(h).contains(pa.representative_point()) for h in pb.interiors):
                    counters += 1; break
    return total, overlaps, counters

def run(label, pairfn, shapes):
    nester._nfp_pair = pairfn
    t = time.perf_counter()
    (sheets, dens), pl = keepbest(shapes)
    dt = time.perf_counter() - t
    placed, overlaps, counters = audit(pl, shapes)
    print(f"{label:34s} sheets={sheets:2d}  last_density={dens:5.1f}%  "
          f"placed={placed}  overlaps={overlaps}  counter_nests={counters}  time={dt:.1f}s")
    return sheets, overlaps, dt

def main():
    shapes = [s for s in extract_shapes(PDF) if s.contour_polygon is not None]
    print(f"{len(shapes)} shapes | full {len(_NFP_ORDERINGS)}-ordering keep-best | sheet {SW}x{SH}\n")
    s_old, ov_old, t_old = run("LEGACY  (GEOS, holes stripped)", _pair_legacy, shapes)
    s_new, ov_new, t_new = run("ORBITAL (Cython, holes kept)", _pair_orbital, shapes)
    print()
    print(f"sheets:  legacy {s_old} -> orbital {s_new}   "
          f"({'OK same/better' if s_new <= s_old else 'REGRESSION'})")
    print(f"speed:   {t_old:.1f}s -> {t_new:.1f}s   ({t_old/max(0.01,t_new):.1f}x)")
    print(f"safety:  overlaps legacy={ov_old} orbital={ov_new}   "
          f"({'OK' if ov_new == 0 else 'OVERLAP FOUND - DO NOT FLIP'})")

if __name__ == "__main__":
    main()
