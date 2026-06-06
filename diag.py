from core.extractor import extract_shapes
from core.nester import nest_shapes, SHEET_W_IN, SHEET_H_IN
from shapely.geometry import Polygon as SP

shapes = extract_shapes("C:/Users/timmy/Desktop/AAANesting Test/168283.pdf")
sheets = nest_shapes(shapes, method="contour", rotation_mode="none/180")

print(f"Total sheets: {len(sheets)}")
for si, sheet in enumerate(sheets):
    print(f"\nSheet {si+1}: {len(sheet)} shapes")
    # Build real contour polygons at placed positions and check overlaps
    polys = []
    for ps in sheet:
        poly = ps.shape.contour_polygon
        if poly is None:
            continue
        if ps.rotation_deg == 180:
            rw = ps.shape.source_rect.width / 72.0
            rh = ps.shape.source_rect.height / 72.0
            cx, cy = rw/2.0, rh/2.0
            poly = SP([(2*cx-px, 2*cy-py) for px, py in poly.exterior.coords])
        b = poly.bounds
        # offset so min corner aligns with placement like nester does
        placed = SP([(px - b[0] + ps.x_in, py - b[1] + ps.y_in) for px, py in poly.exterior.coords])
        polys.append((f"{ps.shape.width_in:.1f}x{ps.shape.height_in:.1f} rot={ps.rotation_deg}", placed))
    bad = 0
    for i in range(len(polys)):
        for j in range(i+1, len(polys)):
            a = polys[i][1].intersection(polys[j][1]).area
            if a > 0.01:
                bad += 1
                print(f"  REAL OVERLAP: {polys[i][0]} & {polys[j][0]} = {a:.2f} sq in")
    print(f"  overlaps on this sheet: {bad}")
