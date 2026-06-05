# core/extractor.py
# Responsible for one thing only: reading a PDF and extracting
# the pink cut-contour shapes from it.
# Nothing in this file knows about the UI or the nesting algorithm.

import fitz  # PyMuPDF
from models.shape import Shape
from shapely.geometry import Polygon as ShapelyPolygon

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


def _path_to_polygon(path, rect):
    """
    Extract vertices from a PyMuPDF path dict and return a Shapely Polygon
    normalized to local inch coordinates with origin at (0, 0).
    Returns None if the path has fewer than 3 usable points.
    """
    origin_x = rect.x0
    origin_y = rect.y0
    scale    = 1.0 / 72.0

    points = []
    for item in path.get("items", []):
        kind = item[0]
        if kind == "l":
            points.append(((item[1].x - origin_x) * scale,
                           (item[1].y - origin_y) * scale))
            points.append(((item[2].x - origin_x) * scale,
                           (item[2].y - origin_y) * scale))
        elif kind == "c":
            points.append(((item[1].x - origin_x) * scale,
                           (item[1].y - origin_y) * scale))
            points.append(((item[4].x - origin_x) * scale,
                           (item[4].y - origin_y) * scale))
        elif kind == "re":
            r = item[1]
            points += [
                ((r.x0 - origin_x) * scale, (r.y0 - origin_y) * scale),
                ((r.x1 - origin_x) * scale, (r.y0 - origin_y) * scale),
                ((r.x1 - origin_x) * scale, (r.y1 - origin_y) * scale),
                ((r.x0 - origin_x) * scale, (r.y1 - origin_y) * scale),
            ]

    deduped = [points[0]] if points else []
    for p in points[1:]:
        if p != deduped[-1]:
            deduped.append(p)

    if len(deduped) < 3:
        return None

    try:
        poly = ShapelyPolygon(deduped)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if poly.is_valid else None
    except Exception:
        return None


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