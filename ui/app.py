# ui/app.py
# The main application window. Wires everything together.
# Knows about all the other modules but does not contain
# any PDF reading, nesting, or drawing logic itself.

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

from core.extractor import extract_shapes
from core.nester    import nest_shapes, SHEET_W_IN, SHEET_H_IN
from core.exporter  import export_pdf
from ui.toolbar     import build_toolbar
from ui.canvas      import (render_sheet, compute_fit_scale, CANVAS_BG,
                            render_pdf_page, pdf_page_count, pdf_page_size_in)

ZOOM_MIN = 2.0
ZOOM_MAX = 40.0


class NestingApp:
    """Main application controller."""

    def __init__(self, root):
        self.root = root
        self.root.title("SignMaster Nesting Tool")
        self.root.geometry("1200x850")
        self.root.configure(bg="#f0f0f0")

        # Window icon (SM mark) — optional, skip gracefully if missing
        try:
            _icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "assets", "icon.png")
            self._icon_img = ImageTk.PhotoImage(Image.open(_icon_path))
            self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

        # ── Application state ─────────────────────────────────────────────────
        self.source_pdf        = None
        self.shapes            = []
        self.sheets            = []
        self.current_sheet     = 0
        self.scale             = 8.0
        self.tk_image_ref      = [None]
        self.mode              = None    # "preview" (source pages) or "nested"
        self.source_page_count = 0

        # canvas display / interaction state
        self._img_w           = 0
        self._img_h           = 0
        self._img_ox          = 0
        self._img_oy          = 0
        self._pending_zoom    = None
        self._zoom_focus      = None

        # ── Build UI ──────────────────────────────────────────────────────────
        self.refs = build_toolbar(
            root=self.root,
            callbacks={
                "load_pdf":    self.load_pdf,
                "nest_shapes": self.run_nest,
                "export_pdf":  self.export_pdf,
                "zoom_in":     self.zoom_in,
                "zoom_out":    self.zoom_out,
                "zoom_fit":    self.zoom_fit,
                "prev_sheet":  self.prev_sheet,
                "next_sheet":  self.next_sheet,
            },
            defaults={
                "spacing":  0.1969,
                "padding":  0.25,
                "rotation": "0/180",
            },
        )

        self._build_canvas()
        self.root.bind("<Configure>", self._on_resize)

    # ── Canvas setup ──────────────────────────────────────────────────────────

    def _build_canvas(self):
        frame = tk.Frame(self.root)
        frame.pack(fill="both", expand=True, padx=12, pady=8)

        self.canvas = tk.Canvas(frame, bg=CANVAS_BG, cursor="crosshair")
        vbar = tk.Scrollbar(frame, orient="vertical",
                            command=self.canvas.yview)
        hbar = tk.Scrollbar(frame, orient="horizontal",
                            command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set,
                              xscrollcommand=hbar.set)

        vbar.pack(side="right",  fill="y")
        hbar.pack(side="bottom", fill="x")
        self.canvas.pack(fill="both", expand=True)

        # Pan with left-click drag
        self.canvas.bind("<ButtonPress-1>", self._pan_start)
        self.canvas.bind("<B1-Motion>",     self._pan_move)
        self.canvas.bind("<ButtonRelease-1>", self._pan_end)
        # Zoom with mouse wheel (Windows / macOS deliver <MouseWheel>)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        # Linux delivers wheel as Button-4/5
        self.canvas.bind("<Button-4>", self._on_wheel)
        self.canvas.bind("<Button-5>", self._on_wheel)

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def status_var(self):
        return self.refs["status_var"]

    @property
    def sheet_label(self):
        return self.refs["sheet_label"]

    @property
    def usage_label(self):
        return self.refs["usage_label"]

    def _spacing(self):
        try:
            return float(self.refs["spacing_var"].get())
        except ValueError:
            return 0.1969

    def _padding(self):
        try:
            return float(self.refs["padding_var"].get())
        except ValueError:
            return 0.25

    def _view_count(self):
        if self.mode == "nested":
            return len(self.sheets)
        if self.mode == "preview":
            return self.source_page_count
        return 0

    # ── Actions ───────────────────────────────────────────────────────────────

    def load_pdf(self):
        path = filedialog.askopenfilename(
            title="Open CorelDRAW PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not path:
            return

        self.status_var.set("Reading shapes from PDF…")
        self.root.update_idletasks()

        try:
            self.shapes = extract_shapes(path)
        except RuntimeError as e:
            messagebox.showerror("Error", str(e))
            self.status_var.set("Failed to load PDF.")
            return

        if not self.shapes:
            messagebox.showwarning(
                "No shapes found",
                "No pink cut-contour paths were detected.\n"
                "Check that the PDF was exported with cut-contour lines visible.",
            )
            self.status_var.set("No shapes found.")
            return

        self.source_pdf        = path
        self.sheets            = []
        self.mode              = "preview"
        self.source_page_count = max(1, pdf_page_count(path))
        self.current_sheet     = 0
        self.usage_label.set("")

        self._fit_current()
        self._render_current()

        pages = self.source_page_count
        self.status_var.set(
            f"Loaded {len(self.shapes)} shapes from "
            f"{pages} page{'s' if pages != 1 else ''}.  "
            f"Previewing source — click 'Nest Shapes' to arrange."
        )

    def run_nest(self):
        if not self.shapes:
            self.status_var.set("No shapes loaded. Load a PDF first.")
            return

        self.status_var.set("Nesting shapes…")
        self.root.update_idletasks()

        rotation_display = self.refs["rotation_var"].get()
        # UI shows "0/180"; the nester's internal mode name is "none/180".
        rotation_mode = "none/180" if rotation_display == "0/180" else rotation_display
        method = self.refs["method_var"].get()

        self.sheets = nest_shapes(
            self.shapes,
            sheet_w       = SHEET_W_IN,
            sheet_h       = SHEET_H_IN,
            padding       = self._padding(),
            spacing       = self._spacing(),
            rotation_mode = rotation_mode,
            method        = method,
        )

        self.mode          = "nested"
        self.current_sheet = 0
        total        = len(self.sheets)
        total_shapes = sum(len(s) for s in self.sheets)

        self.status_var.set(
            f"{total_shapes} shapes arranged across "
            f"{total} sheet{'s' if total != 1 else ''}  ·  "
            f"Rotation: {rotation_display}  ·  Method: {method}"
        )

        self._fit_current()
        self._render_current()

    def export_pdf(self):
        if not self.sheets:
            messagebox.showwarning(
                "Nothing to export",
                "Nest the shapes first before exporting.",
            )
            return

        out_path = filedialog.asksaveasfilename(
            title="Save Nested PDF",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            initialfile="nested_output.pdf",
        )
        if not out_path:
            return

        self.status_var.set("Exporting PDF… please wait.")
        self.root.update_idletasks()

        try:
            num_sheets, num_shapes = export_pdf(
                source_pdf_path = self.source_pdf,
                sheets          = self.sheets,
                output_path     = out_path,
            )
        except (RuntimeError, IOError) as e:
            messagebox.showerror("Export failed", str(e))
            self.status_var.set("Export failed.")
            return

        self.status_var.set(
            f"✓ Exported {num_shapes} shapes across "
            f"{num_sheets} sheet{'s' if num_sheets != 1 else ''}  →  {out_path}"
        )
        messagebox.showinfo(
            "Export complete",
            f"Saved {num_sheets} sheet{'s' if num_sheets != 1 else ''} "
            f"({num_shapes} shapes) to:\n\n{out_path}",
        )

    # ── Sheet / page navigation ────────────────────────────────────────────────

    def prev_sheet(self):
        if self._view_count() and self.current_sheet > 0:
            self.current_sheet -= 1
            self._fit_current()
            self._render_current()

    def next_sheet(self):
        if self._view_count() and self.current_sheet < self._view_count() - 1:
            self.current_sheet += 1
            self._fit_current()
            self._render_current()

    # ── Zoom (buttons) ──────────────────────────────────────────────────────────

    def zoom_in(self):
        self.scale = min(self.scale + 1, ZOOM_MAX)
        self._render_current()

    def zoom_out(self):
        self.scale = max(self.scale - 1, ZOOM_MIN)
        self._render_current()

    def zoom_fit(self):
        self._fit_current()
        self._render_current()

    # ── Mouse wheel zoom (toward cursor, debounced) ─────────────────────────────

    def _on_wheel(self, event):
        if not self.mode:
            return
        if self._img_w and self._img_h:
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
            fx = min(max((cx - self._img_ox) / self._img_w, 0.0), 1.0)
            fy = min(max((cy - self._img_oy) / self._img_h, 0.0), 1.0)
            self._zoom_focus = (event.x, event.y, fx, fy)

        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            factor = 1.15
        else:
            factor = 1.0 / 1.15
        self.scale = min(max(self.scale * factor, ZOOM_MIN), ZOOM_MAX)

        if self._pending_zoom is not None:
            self.root.after_cancel(self._pending_zoom)
        self._pending_zoom = self.root.after(120, self._do_zoom_render)
        return "break"

    def _do_zoom_render(self):
        self._pending_zoom = None
        focus = self._zoom_focus
        self._zoom_focus = None
        self._render_current(focus=focus)

    # ── Pan (left-click drag) ──────────────────────────────────────────────────

    def _pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)
        self.canvas.config(cursor="fleur")

    def _pan_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _pan_end(self, event):
        self.canvas.config(cursor="crosshair")

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _fit_current(self):
        """Set self.scale to fit the current view (nested sheet or source page)."""
        if self.mode == "preview" and self.source_pdf:
            w_in, h_in = pdf_page_size_in(self.source_pdf, self.current_sheet)
            self.scale = compute_fit_scale(self.canvas, w_in, h_in)
        else:
            self.scale = compute_fit_scale(self.canvas, SHEET_W_IN, SHEET_H_IN)

    def _display(self, img, focus=None):
        """Place a PIL image on the canvas, centered when it is smaller than the
        viewport (via a draw offset) and scrollable when larger. If
        focus=(vx,vy,fx,fy), scroll so image fraction (fx,fy) sits under viewport
        point (vx,vy) — zoom-to-cursor."""
        photo = ImageTk.PhotoImage(img)
        self.tk_image_ref[0] = photo          # keep a reference alive
        self.canvas.delete("all")
        self.canvas.update_idletasks()

        vw = self.canvas.winfo_width()
        vh = self.canvas.winfo_height()
        if vw <= 1:
            vw = 1170          # window not laid out yet — sensible fallback
        if vh <= 1:
            vh = 760

        w, h = img.width, img.height
        ox = max((vw - w) // 2, 10)           # center small images; 10px margin if larger
        oy = max((vh - h) // 2, 10)
        self.canvas.create_image(ox, oy, anchor="nw", image=photo)

        region_w = w + 2 * ox
        region_h = h + 2 * oy
        self.canvas.configure(scrollregion=(0, 0, region_w, region_h))
        self._img_w, self._img_h = w, h
        self._img_ox, self._img_oy = ox, oy

        if focus is not None and region_w and region_h:
            vx, vy, fx, fy = focus
            target_cx = ox + fx * w
            target_cy = oy + fy * h
            self.canvas.xview_moveto(min(max((target_cx - vx) / region_w, 0.0), 1.0))
            self.canvas.yview_moveto(min(max((target_cy - vy) / region_h, 0.0), 1.0))

    def _render_current(self, focus=None):
        if self.mode == "nested":
            self._render_nested(focus)
        elif self.mode == "preview":
            self._render_preview(focus)

    def _render_nested(self, focus=None):
        if not self.sheets:
            return
        placed = self.sheets[self.current_sheet]
        total  = len(self.sheets)

        img, usage = render_sheet(
            placed_shapes = placed,
            sheet_w_in    = SHEET_W_IN,
            sheet_h_in    = SHEET_H_IN,
            scale         = self.scale,
            source_pdf    = self.source_pdf,
        )
        self._display(img, focus)
        self.sheet_label.set(f"Sheet {self.current_sheet + 1} of {total}")
        self.usage_label.set(f"{len(placed)} shapes  |  {usage:.1f}% usage")

    def _render_preview(self, focus=None):
        if not self.source_pdf:
            return
        total = self.source_page_count
        img, _ = render_pdf_page(self.source_pdf, self.current_sheet, self.scale)
        self._display(img, focus)
        self.sheet_label.set(f"Source page {self.current_sheet + 1} of {total}")
        self.usage_label.set(f"{len(self.shapes)} shapes loaded")

    def _on_resize(self, event):
        if self.mode:
            self._fit_current()
            self._render_current()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app  = NestingApp(root)
    root.mainloop()
