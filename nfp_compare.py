from core.extractor import extract_shapes
from core.nester import nest_shapes, SHEET_W_IN, SHEET_H_IN
from shapely.geometry import Polygon as SP

shapes = extract_shapes(r"C:\Users\timmy\Desktop\AAANesting Test\168283Test.pdf")
print(f"{len(shapes)} shapes extracted\n")

def placed_poly(ps):
    poly = ps.shape.contour_polygon
    if poly is None:
        return None
    if getattr(ps, "rotation_deg", 0) == 180:
        rw = ps.shape.source_rect.width / 72.0
        rh = ps.shape.source_rect.height / 72.0
        cx, cy = rw / 2.0, rh / 2.0
        poly = SP([(2*cx-px, 2*cy-py) for px, py in poly.exterior.coords],
                  [[(2*cx-px, 2*cy-py) for px, py in r.coords] for r in poly.interiors])
    return SP([(px+ps.x_in, py+ps.y_in) for px, py in poly.exterior.coords],
              [[(px+ps.x_in, py+ps.y_in) for px, py in r.coords] for r in poly.interiors])

for method in ("contour", "nfp"):
    sheets = nest_shapes(shapes, method=method, rotation_mode="none/180")
    print(f"=== method='{method}': {len(sheets)} sheets, counts={[len(s) for s in sheets]} ===")
    grand = 0
    for si, sh in enumerate(sheets):
        polys = [placed_poly(ps) for ps in sh]
        polys = [p for p in polys if p is not None]
        cdens = sum(p.area for p in polys) / (SHEET_W_IN*SHEET_H_IN) * 100
        bad = 0
        for i in range(len(polys)):
            for j in range(i+1, len(polys)):
                if polys[i].intersection(polys[j]).area > 0.01:
                    bad += 1
        grand += bad
        print(f"  sheet {si+1}: {len(sh)} shapes, contour density {cdens:.1f}%, real overlaps {bad}")
    print(f"  TOTAL REAL OVERLAPS: {grand}\n")
