# ui/toolbar.py
# Responsible for one thing only: building the toolbar and controls.
# Returns references to all interactive widgets so the main app
# can wire up the commands. Nothing in this file knows about
# PDF reading, nesting, or exporting.

import tkinter as tk


# ── Colour palette ────────────────────────────────────────────────────────────

BTN_BLUE    = "#1a73e8"
BTN_GREEN   = "#34a853"
BTN_GRAY    = "#757575"
BTN_NEUTRAL = "#dddddd"
BG          = "#f0f0f0"
STATUS_BG   = "#e8e8e8"


def _button(parent, text, color, command=None, fg="white"):
    return tk.Button(
        parent,
        text=text,
        bg=color,
        fg=fg,
        activebackground=color,
        activeforeground=fg,
        padx=12,
        pady=6,
        relief="flat",
        cursor="hand2",
        command=command,
    )


def build_toolbar(root, callbacks, defaults):
    """
    Build the full toolbar UI and attach it to root.

    Args:
        root      : the Tk root window
        callbacks : dict of command functions keyed by name:
                      load_pdf, nest_shapes, zoom_in, zoom_out,
                      zoom_fit, prev_sheet, next_sheet, export_pdf
        defaults  : dict of default values:
                      spacing, padding

    Returns:
        refs : dict of widget references the app needs to read or update:
                 spacing_var, padding_var, status_var,
                 sheet_label, usage_label
    """
    refs = {}

    # ── Top button row ────────────────────────────────────────────────────────
    top = tk.Frame(root, bg=BG, pady=8)
    top.pack(fill="x", padx=12)

    _button(top, "Load PDF",     BTN_BLUE,  callbacks.get("load_pdf")
            ).pack(side="left", padx=4)
    _button(top, "Nest Shapes",  BTN_GREEN, callbacks.get("nest_shapes")
            ).pack(side="left", padx=4)
    _button(top, "Export PDF",   BTN_GREEN, callbacks.get("export_pdf")
            ).pack(side="left", padx=4)

    # ── Settings row ──────────────────────────────────────────────────────────
    settings = tk.Frame(root, bg=BG)
    settings.pack(fill="x", padx=12, pady=4)

    tk.Label(settings, text="Spacing (in):",
             bg=BG).pack(side="left")
    spacing_var = tk.StringVar(value=str(defaults.get("spacing", 0.1969)))
    tk.Entry(settings, textvariable=spacing_var,
             width=8).pack(side="left", padx=4)
    refs["spacing_var"] = spacing_var

    tk.Label(settings, text="Edge Padding (in):",
             bg=BG).pack(side="left", padx=(12, 0))
    padding_var = tk.StringVar(value=str(defaults.get("padding", 0.25)))
    tk.Entry(settings, textvariable=padding_var,
             width=8).pack(side="left", padx=4)
    refs["padding_var"] = padding_var

    tk.Label(settings, text="Zoom:",
             bg=BG).pack(side="left", padx=(20, 4))
    _button(settings, "−", BTN_NEUTRAL, callbacks.get("zoom_out"),
            fg="black").pack(side="left", padx=2)
    _button(settings, "+", BTN_NEUTRAL, callbacks.get("zoom_in"),
            fg="black").pack(side="left", padx=2)
    _button(settings, "Fit", BTN_NEUTRAL, callbacks.get("zoom_fit"),
            fg="black").pack(side="left", padx=2)

    # ── Status bar ────────────────────────────────────────────────────────────
    status_var = tk.StringVar(value="Load a PDF to begin.")
    tk.Label(root, textvariable=status_var,
             bg=STATUS_BG, anchor="w",
             padx=8, pady=4).pack(fill="x", padx=12)
    refs["status_var"] = status_var

    # ── Sheet navigation row ──────────────────────────────────────────────────
    nav = tk.Frame(root, bg=BG, pady=4)
    nav.pack(fill="x", padx=12)

    _button(nav, "◀ Prev Sheet", BTN_GRAY,
            callbacks.get("prev_sheet")).pack(side="left", padx=4)

    sheet_label = tk.StringVar(value="")
    tk.Label(nav, textvariable=sheet_label,
             bg=BG, font=("Arial", 10, "bold")).pack(side="left", padx=8)
    refs["sheet_label"] = sheet_label

    _button(nav, "Next Sheet ▶", BTN_GRAY,
            callbacks.get("next_sheet")).pack(side="left", padx=4)

    usage_label = tk.StringVar(value="")
    tk.Label(nav, textvariable=usage_label,
             bg=BG, fg="#444444").pack(side="left", padx=16)
    refs["usage_label"] = usage_label

    return refs