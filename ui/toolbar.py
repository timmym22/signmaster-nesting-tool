# ui/toolbar.py
# Responsible for one thing only: building the toolbar and controls.
# Returns references to all interactive widgets so the main app
# can wire up the commands. Nothing in this file knows about
# PDF reading, nesting, or exporting.

import tkinter as tk
from tkinter import ttk

# ── Colour palette ────────────────────────────────────────────────────────────

BG          = "#f0f0f0"

# Sign Master brand palette
BRAND_ORANGE = "#F06020"
BRAND_ORANGE_DK = "#D9541C"   # hover
BRAND_GRAY   = "#686870"
BRAND_GRAY_DK = "#565660"     # hover
HEADER_BG    = "#1A1A1C"

PANEL_BG    = "#f4f5f6"
NEUTRAL     = "#e3e4e6"
NEUTRAL_DK  = "#d2d3d6"
TEXT_DARK   = "#2b2b2e"
STATUS_BG   = "#1A1A1C"
STATUS_FG   = "#e8e8ea"

UI_FONT       = ("Segoe UI", 10)
UI_FONT_BOLD  = ("Segoe UI", 10, "bold")
LABEL_FONT    = ("Segoe UI", 9)
GROUP_FONT    = ("Segoe UI", 8, "bold")


def _button(parent, text, color, command=None, fg="white",
            hover=None, font=UI_FONT_BOLD, padx=14, pady=7):
    """A flat brand-styled button with a hover color."""
    btn = tk.Button(
        parent, text=text, bg=color, fg=fg,
        activebackground=hover or color, activeforeground=fg,
        padx=padx, pady=pady, relief="flat", cursor="hand2",
        font=font, borderwidth=0, command=command,
    )
    if hover:
        btn.bind("<Enter>", lambda e: btn.config(bg=hover))
        btn.bind("<Leave>", lambda e: btn.config(bg=color))
    return btn


def _group(parent, title):
    """A titled, lightly-bordered section frame for grouping controls."""
    outer = tk.LabelFrame(
        parent, text=title.upper(), bg=PANEL_BG, fg=BRAND_GRAY,
        font=GROUP_FONT, bd=1, relief="solid",
        labelanchor="nw", padx=8, pady=6,
    )
    return outer


def build_toolbar(root, callbacks, defaults):
    """
    Build the full toolbar UI and attach it to root.

    Returns:
        refs : dict of widget references the app needs to read or update:
                 spacing_var, padding_var, rotation_var, method_var,
                 status_var, sheet_label, usage_label
    """
    refs = {}

    # ── Control bar (grouped, labeled sections) ─────────────────────────────────
    bar = tk.Frame(root, bg=BG, pady=10)
    bar.pack(fill="x", padx=12)

    # File group
    g_file = _group(bar, "File")
    g_file.pack(side="left", padx=(0, 10), fill="y")
    _button(g_file, "Load PDF", BRAND_GRAY, callbacks.get("load_pdf"),
            hover=BRAND_GRAY_DK).pack(side="left", padx=3)
    _button(g_file, "Export PDF", BRAND_GRAY, callbacks.get("export_pdf"),
            hover=BRAND_GRAY_DK).pack(side="left", padx=3)

    # Nesting group
    g_nest = _group(bar, "Nesting")
    g_nest.pack(side="left", padx=(0, 10), fill="y")

    tk.Label(g_nest, text="Method", bg=PANEL_BG, fg=TEXT_DARK,
             font=LABEL_FONT).pack(side="left", padx=(0, 4))
    method_var = tk.StringVar(value="nfp")
    ttk.Combobox(g_nest, textvariable=method_var,
                 values=["nfp", "contour", "bounding box"],
                 state="readonly", width=11, font=LABEL_FONT
                 ).pack(side="left", padx=(0, 10))
    refs["method_var"] = method_var

    tk.Label(g_nest, text="Rotation", bg=PANEL_BG, fg=TEXT_DARK,
             font=LABEL_FONT).pack(side="left", padx=(0, 4))
    rotation_var = tk.StringVar(value=defaults.get("rotation", "0/180"))
    ttk.Combobox(g_nest, textvariable=rotation_var,
                 values=["0/180", "90°", "180°", "270°", "free"],
                 state="readonly", width=7, font=LABEL_FONT
                 ).pack(side="left", padx=(0, 10))
    refs["rotation_var"] = rotation_var

    _button(g_nest, "Nest Shapes", BRAND_ORANGE, callbacks.get("nest_shapes"),
            hover=BRAND_ORANGE_DK).pack(side="left", padx=3)

    # Spacing group
    g_space = _group(bar, "Spacing (in)")
    g_space.pack(side="left", padx=(0, 10), fill="y")

    tk.Label(g_space, text="Gap", bg=PANEL_BG, fg=TEXT_DARK,
             font=LABEL_FONT).pack(side="left", padx=(0, 4))
    spacing_var = tk.StringVar(value=str(defaults.get("spacing", 0.1969)))
    tk.Entry(g_space, textvariable=spacing_var, width=7,
             font=LABEL_FONT, relief="solid", bd=1
             ).pack(side="left", padx=(0, 10))
    refs["spacing_var"] = spacing_var

    tk.Label(g_space, text="Edge", bg=PANEL_BG, fg=TEXT_DARK,
             font=LABEL_FONT).pack(side="left", padx=(0, 4))
    padding_var = tk.StringVar(value=str(defaults.get("padding", 0.25)))
    tk.Entry(g_space, textvariable=padding_var, width=7,
             font=LABEL_FONT, relief="solid", bd=1
             ).pack(side="left", padx=(0, 2))
    refs["padding_var"] = padding_var

    # Sheet group
    g_sheet = _group(bar, "Sheet (in)")
    g_sheet.pack(side="left", padx=(0, 10), fill="y")

    tk.Label(g_sheet, text="W", bg=PANEL_BG, fg=TEXT_DARK,
             font=LABEL_FONT).pack(side="left", padx=(0, 4))
    sheet_w_var = tk.StringVar(value=str(defaults.get("sheet_w", 48.0)))
    tk.Entry(g_sheet, textvariable=sheet_w_var, width=6,
             font=LABEL_FONT, relief="solid", bd=1
             ).pack(side="left", padx=(0, 8))
    refs["sheet_w_var"] = sheet_w_var

    tk.Label(g_sheet, text="H", bg=PANEL_BG, fg=TEXT_DARK,
             font=LABEL_FONT).pack(side="left", padx=(0, 4))
    sheet_h_var = tk.StringVar(value=str(defaults.get("sheet_h", 96.0)))
    tk.Entry(g_sheet, textvariable=sheet_h_var, width=6,
             font=LABEL_FONT, relief="solid", bd=1
             ).pack(side="left", padx=(0, 2))
    refs["sheet_h_var"] = sheet_h_var

    # View group
    g_view = _group(bar, "View")
    g_view.pack(side="left", fill="y")
    _button(g_view, "−", NEUTRAL, callbacks.get("zoom_out"), fg=TEXT_DARK,
            hover=NEUTRAL_DK, padx=12).pack(side="left", padx=2)
    _button(g_view, "+", NEUTRAL, callbacks.get("zoom_in"), fg=TEXT_DARK,
            hover=NEUTRAL_DK, padx=12).pack(side="left", padx=2)
    _button(g_view, "Fit", NEUTRAL, callbacks.get("zoom_fit"), fg=TEXT_DARK,
            hover=NEUTRAL_DK).pack(side="left", padx=2)

    # Rotation legend (subtle, full-width line under the bar)
    tk.Label(root, text="0/180 = flute-safe for Coroplast",
             bg=BG, fg="#999999", font=("Segoe UI", 8)
             ).pack(anchor="w", padx=16)

    # ── Sheet navigation row ──────────────────────────────────────────────────
    nav = tk.Frame(root, bg=BG, pady=6)
    nav.pack(fill="x", padx=12)

    _button(nav, "◀ Prev Sheet", BRAND_GRAY, callbacks.get("prev_sheet"),
            hover=BRAND_GRAY_DK, font=UI_FONT, padx=12, pady=5
            ).pack(side="left", padx=3)
    _button(nav, "Next Sheet ▶", BRAND_GRAY, callbacks.get("next_sheet"),
            hover=BRAND_GRAY_DK, font=UI_FONT, padx=12, pady=5
            ).pack(side="left", padx=3)

    sheet_label = tk.StringVar(value="")
    tk.Label(nav, textvariable=sheet_label, bg=BG, fg=TEXT_DARK,
             font=("Segoe UI", 11, "bold")).pack(side="left", padx=14)
    refs["sheet_label"] = sheet_label

    usage_label = tk.StringVar(value="")
    tk.Label(nav, textvariable=usage_label, bg=BG, fg=BRAND_GRAY,
             font=UI_FONT).pack(side="right", padx=8)
    refs["usage_label"] = usage_label

    # ── Status bar (dark, brand) ────────────────────────────────────────────────
    status_var = tk.StringVar(value="Load a PDF to begin.")
    tk.Frame(root, bg=BRAND_ORANGE, height=2).pack(fill="x")  # accent line
    tk.Label(root, textvariable=status_var, bg=STATUS_BG, fg=STATUS_FG,
             anchor="w", padx=12, pady=5, font=LABEL_FONT
             ).pack(fill="x")
    refs["status_var"] = status_var

    return refs
