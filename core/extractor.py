# core/extractor.py
# Responsible for one thing only: reading a PDF and extracting
# the pink cut-contour shapes from it.
# Nothing in this file knows about the UI or the nesting algorithm.

import fitz  # PyMuPDF
from models.shape import Shape

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
                width_in    = width_in,
                height_in   = height_in,
                source_rect = rect,
                source_page = page_index,
            ))

    doc.close()
    return shapes