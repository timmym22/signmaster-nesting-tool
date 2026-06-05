# ui/canvas.py
# Responsible for one thing only: drawing the sheet preview.
# Takes a list of PlacedShape objects and renders them onto a
# Tkinter canvas. Nothing in this file knows about PDF reading,
# nesting, or exporting.

from PIL import Image, ImageDraw, ImageTk

# ── Visual constants ──────────────────────────────────────────────────────────

SHEET_BG      = "#ffffff"
SHAPE_FILL    = "#ffe0f4"
SHAPE_OUTLINE = "#e01489"
LABEL_COLOR   = "#a0006a"
CANVAS_BG     = "#888888"
SHEET_BORDER  = "#000000"


def render_sheet(placed_shapes, sheet_w_in, sheet_h_in, scale):
    img_w = max(1, int(sheet_w_in * scale))
    img_h = max(1, int(sheet_h_in * scale))

    img  = Image.new("RGB", (img_w, img_h), SHEET_BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle(
        [0, 0, img_w - 1, img_h - 1],
        outline=SHEET_BORDER,
        width=3,
    )

    for ps in placed_shapes:
        x0 = int(ps.x_in * scale)
        y0 = int(ps.y_in * scale)
        x1 = int((ps.x_in + ps.shape.width_in)  * scale)
        y1 = int((ps.y_in + ps.shape.height_in) * scale)

        draw.rectangle(
            [x0, y0, x1, y1],
            fill=SHAPE_FILL,
            outline=SHAPE_OUTLINE,
            width=2,
        )

        label = f'{ps.shape.width_in:.1f}" x {ps.shape.height_in:.1f}"'
        draw.text((x0 + 6, y0 + 6), label, fill=LABEL_COLOR)

    used_area  = sum(ps.shape.area() for ps in placed_shapes)
    sheet_area = sheet_w_in * sheet_h_in
    usage_pct  = (used_area / sheet_area * 100) if sheet_area > 0 else 0

    return img, usage_pct


def compute_fit_scale(canvas_widget, sheet_w_in, sheet_h_in):
    canvas_widget.update_idletasks()
    canvas_w = canvas_widget.winfo_width()  - 20
    canvas_h = canvas_widget.winfo_height() - 20

    if canvas_w < 10 or canvas_h < 10:
        canvas_w, canvas_h = 900, 700

    scale_w = canvas_w / sheet_w_in
    scale_h = canvas_h / sheet_h_in

    return max(2.0, min(scale_w, scale_h))


def display_image_on_canvas(canvas_widget, pil_image, tk_image_ref):
    photo = ImageTk.PhotoImage(pil_image)
    tk_image_ref[0] = photo

    canvas_widget.delete("all")
    canvas_widget.update_idletasks()

    canvas_w = canvas_widget.winfo_width()
    canvas_h = canvas_widget.winfo_height()
    img_w    = pil_image.width
    img_h    = pil_image.height

    x_offset = max(10, (canvas_w - img_w) // 2)
    y_offset = max(10, (canvas_h - img_h) // 2)

    canvas_widget.create_image(
        x_offset, y_offset,
        anchor="nw",
        image=photo,
    )
    canvas_widget.configure(
        scrollregion=(
            0, 0,
            img_w + x_offset * 2,
            img_h + y_offset * 2,
        )
    )

    return tk_image_ref