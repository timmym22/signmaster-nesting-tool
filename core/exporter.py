# core/exporter.py
# Responsible for one thing only: writing the nested layout to a PDF file.
# Takes the sheets produced by the nester and copies real artwork from
# the source PDF into the correct positions on each output page.
# Nothing in this file knows about the UI or the nesting algorithm.

import fitz  # PyMuPDF
from core.nester import SHEET_W_IN, SHEET_H_IN

PTS_PER_IN = 72.0


def export_pdf(source_pdf_path, sheets, output_path):
    """
    Write a print-ready PDF to output_path.

    Each sheet in the nested layout becomes one page at 48x96 inches.
    Artwork is copied from the source PDF using show_pdf_page() so the
    output is full vector quality, not a rasterized image.

    Args:
        source_pdf_path : path to the original CorelDRAW-exported PDF
        sheets          : list of sheets from nest_shapes()
                          each sheet is a list of PlacedShape objects
        output_path     : where to save the output PDF

    Returns:
        (num_sheets, num_shapes) tuple for confirmation messaging

    Raises:
        RuntimeError: if the source PDF cannot be opened
        IOError:      if the output path cannot be written
    """
    try:
        src_doc = fitz.open(source_pdf_path)
    except Exception as e:
        raise RuntimeError(f"Could not open source PDF: {e}")

    out_doc = fitz.open()  # new empty PDF in memory

    page_w_pts = SHEET_W_IN * PTS_PER_IN
    page_h_pts = SHEET_H_IN * PTS_PER_IN

    total_shapes = 0

    for sheet in sheets:
        # Add a blank page at the correct sheet size
        out_page = out_doc.new_page(
            width=page_w_pts,
            height=page_h_pts,
        )

        for ps in sheet:
            shape    = ps.shape
            src_rect = shape.source_rect
            src_page = src_doc[shape.source_page]

            # Destination rectangle in output page points
            dst_x0 = ps.x_in * PTS_PER_IN
            dst_y0 = ps.y_in * PTS_PER_IN
            dst_x1 = dst_x0 + shape.width_in  * PTS_PER_IN
            dst_y1 = dst_y0 + shape.height_in * PTS_PER_IN
            dst_rect = fitz.Rect(dst_x0, dst_y0, dst_x1, dst_y1)

            # Copy artwork from source, cropped to the shape bounding box
            out_page.show_pdf_page(
                dst_rect,
                src_doc,
                src_page.number,
                clip=src_rect,
            )

            total_shapes += 1

    try:
        out_doc.save(output_path)
    except Exception as e:
        raise IOError(f"Could not save output PDF: {e}")
    finally:
        out_doc.close()
        src_doc.close()

    return len(sheets), total_shapes