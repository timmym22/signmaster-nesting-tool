# models/shape.py
# Defines the Shape data model used throughout the application.
# This is the single source of truth for what a shape is.


class Shape:
    """Represents a single die-cut shape extracted from the source PDF."""

    def __init__(self, width_in, height_in, source_rect, source_page, contour_polygon=None):
        self.width_in    = width_in
        self.height_in   = height_in
        self.source_rect = source_rect
        self.source_page = source_page
        self.contour_polygon = contour_polygon

    def area(self):
        return self.width_in * self.height_in

    def __repr__(self):
        return f"Shape({self.width_in:.2f}\" x {self.height_in:.2f}\")"


class PlacedShape:
    """Represents a Shape assigned a position on a sheet."""

    def __init__(self, shape, x_in, y_in, sheet_index, rotated=False, rotation_deg=0.0):
        self.shape       = shape
        self.x_in        = x_in
        self.y_in        = y_in
        self.sheet_index = sheet_index
        self.rotated     = rotated     # True if shape was rotated 90°
        self.rotation_deg = rotation_deg

    @property
    def placed_width(self):
        """Actual width on sheet accounting for rotation."""
        if self.rotated:
            return self.shape.height_in
        return self.shape.width_in

    @property
    def placed_height(self):
        """Actual height on sheet accounting for rotation."""
        if self.rotated:
            return self.shape.width_in
        return self.shape.height_in

    def right(self):
        return self.x_in + self.placed_width

    def bottom(self):
        return self.y_in + self.placed_height

    def __repr__(self):
        rot = " [rotated]" if self.rotated else ""
        return (f"PlacedShape({self.shape}{rot} @ "
                f"{self.x_in:.2f}\", {self.y_in:.2f}\" "
                f"sheet {self.sheet_index})")