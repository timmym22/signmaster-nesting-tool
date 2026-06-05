# models/shape.py
# Defines the Shape data model used throughout the application.
# This is the single source of truth for what a shape is.


class Shape:
    """Represents a single die-cut shape extracted from the source PDF."""

    def __init__(self, width_in, height_in, source_rect, source_page):
        self.width_in    = width_in      # bounding box width in inches
        self.height_in   = height_in     # bounding box height in inches
        self.source_rect = source_rect   # fitz.Rect in the source PDF (points)
        self.source_page = source_page   # page index in the source PDF

    def area(self):
        return self.width_in * self.height_in

    def __repr__(self):
        return f"Shape({self.width_in:.2f}\" x {self.height_in:.2f}\")"


class PlacedShape:
    """Represents a Shape that has been assigned a position on a sheet."""

    def __init__(self, shape, x_in, y_in, sheet_index):
        self.shape       = shape         # Shape instance
        self.x_in        = x_in          # left edge on sheet in inches
        self.y_in        = y_in          # top edge on sheet in inches
        self.sheet_index = sheet_index   # which sheet (0-based)

    def right(self):
        return self.x_in + self.shape.width_in

    def bottom(self):
        return self.y_in + self.shape.height_in

    def __repr__(self):
        return (f"PlacedShape({self.shape} @ "
                f"{self.x_in:.2f}\", {self.y_in:.2f}\" "
                f"sheet {self.sheet_index})")