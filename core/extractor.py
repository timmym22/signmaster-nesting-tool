# core/extractor.py
# Responsible for one thing only: reading a PDF and extracting
# the pink cut-contour shapes from it.
# Nothing in this file knows about the UI or the nesting algorithm.

import fitz  # PyMuPDF
from models.shape import Shape
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.ops import unary_union

# ── Cut contour color detection ───────────────────────────────────────────────
# CorelDRAW exports the cut contour as a specific pink/magenta stroke.
# We detect it by checking the RGB values of each path's stroke color.

PINK_R_MIN, PINK_R_MAX = 180, 255
PINK_G_MIN, PINK_G_MAX = 0,   80
PINK_B_MIN, PINK_B_MAX = 100, 220


def _to_rgb(color_tuple):
    """
    Convert a PyMuPDF color tuple to (r, g, b) in 0-255 range.
    Handles both RGB (3-tuple) and CMYK (4-tuple) formats.
    Returns None if the color cannot be converted.
    """
    if color_tuple is None:
        return None

    if len(color_tuple) == 3:
        r, g, b = color_tuple
        return int(r * 255), int(g * 255), int(b * 255)

    if len(color_tuple) == 4:
        c, m, y, k = color_tuple
        r = int((1 - c) * (1 - k) * 255)
        g = int((1 - m) * (1 - k) * 255)
        b = int((1 - y) * (1 - k) * 255)
        return r, g, b

    return None


def _is_cut_contour(color_tuple):
    """
    Returns True if the color matches the pink cut-contour signature.
    """
    rgb = _to_rgb(color_tuple)
    if rgb is None:
        return False
    r, g, b = rgb
    return (PINK_R_MIN <= r <= PINK_R_MAX and
            PINK_G_MIN <= g <= PINK_G_MAX and
            PINK_B_MIN <= b <= PINK_B_MAX)


def _sample_bezier(p0, p1, p2, p3, segments=8):
    """
    Sample points along a cubic bezier curve defined by four control points.
    Each point is an (x, y) tuple. Returns 'segments' points along the curve,
    not including the start point (which the caller already added).
    """
    pts = []
    for i in range(1, segments + 1):
        t  = i / segments
        mt = 1 - t
        x = (mt**3 * p0[0] + 3*mt**2*t * p1[0] +
             3*mt*t**2 * p2[0] + t**3 * p3[0])
        y = (mt**3 * p0[1] + 3*mt**2*t * p1[1] +
             3*mt*t**2 * p2[1] + t**3 * p3[1])
        pts.append((x, y))
    return pts


def _path_to_polygon(path, rect):
    """
    Build a Shapely polygon (local inch coords, origin at rect top-left) from a
    PyMuPDF path. Splits the path into subpaths; the largest subpath is the
    outer cut outline and any subpaths enclosed by it become holes. Bezier
    curves are sampled so curved outlines are accurate. Returns None if nothing
    usable is found.
    """
    ox, oy = rect.x0, rect.y0
    sc = 1.0 / 72.0
    def loc(pt):
        return ((pt.x - ox) * sc, (pt.y - oy) * sc)

    subs = []
    cur = []
    last = None
    def flush():
        nonlocal cur
        if len(cur) >= 3:
            try:
                p = ShapelyPolygon(cur)
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty and p.area > 0:
                    subs.append(p)
            except Exception:
                pass
        cur = []

    for item in path.get("items", []):
        kind = item[0]
        if kind == "l":
            s, e = item[1], item[2]
            pts = [loc(s), loc(e)]
        elif kind == "c":
            s, e = item[1], item[4]
            pts = [loc(item[1])] + _sample_bezier(loc(item[1]), loc(item[2]),
                                                  loc(item[3]), loc(item[4]), segments=8)
        elif kind == "re":
            flush()
            r = item[1]
            subs.append(ShapelyPolygon([
                ((r.x0 - ox) * sc, (r.y0 - oy) * sc),
                ((r.x1 - ox) * sc, (r.y0 - oy) * sc),
                ((r.x1 - ox) * sc, (r.y1 - oy) * sc),
                ((r.x0 - ox) * sc, (r.y1 - oy) * sc)]))
            last = None
            continue
        elif kind == "qu":
            flush()
            q = item[1]
            subs.append(ShapelyPolygon([loc(q.ul), loc(q.ur), loc(q.lr), loc(q.ll)]))
            last = None
            continue
        else:
            continue
        if last is not None and (abs(s.x - last.x) > 0.01 or abs(s.y - last.y) > 0.01):
            flush()
        cur += pts
        last = e
    flush()

    if not subs:
        return None
    subs.sort(key=lambda p: p.area, reverse=True)
    outer = subs[0]
    holes, separate = [], []
    for p in subs[1:]:
        if outer.contains(p.representative_point()):
            holes.append(list(p.exterior.coords))
        elif p.area > outer.area * 0.2:
            separate.append(p)
        # tiny strays outside the outer are ignored
    if separate:
        g = unary_union([outer] + separate)
        return g.convex_hull
    poly = ShapelyPolygon(list(outer.exterior.coords), holes)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly if (not poly.is_empty and poly.is_valid) else None


def extract_shapes(pdf_path):
    """
    Open a CorelDRAW-exported PDF and extract all pink cut-contour shapes.

    Returns a list of Shape objects, one per detected contour path.
    Shapes are returned in the order they appear in the PDF.

    Raises:
        FileNotFoundError: if the PDF path does not exist
        RuntimeError: if the PDF cannot be opened
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise RuntimeError(f"Could not open PDF: {e}")

    shapes = []

    for page_index, page in enumerate(doc):
        for path in page.get_drawings():
            color = path.get("color")
            if not _is_cut_contour(color):
                continue

            rect = path["rect"]

            # Skip degenerate paths with no real area
            if rect.width < 1 or rect.height < 1:
                continue

            width_in  = rect.width  / 72.0
            height_in = rect.height / 72.0

            shapes.append(Shape(
                width_in        = width_in,
                height_in       = height_in,
                source_rect     = rect,
                source_page     = page_index,
                contour_polygon = _path_to_polygon(path, rect),
            ))

    doc.close()
    return shapes