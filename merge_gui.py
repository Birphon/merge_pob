#!/usr/bin/env python3
"""
merge_gui.py - PoB Build Merger user interface.

Purely presentation: every bit of merging logic lives in merge_pob.py.
Run with:  python merge_gui.py

Layout of this file
    1. Theme            - every colour, font and metric in one place
    2. Drawing helpers  - rounded rectangles, icons, app icon, platform tweaks
    3. Widgets          - RoundedSurface, Button, TextField (reusable)
    4. Panels           - HeaderBar, InputPanel, OutputPanel, StatusBar, AboutDialog
    5. App              - wires panels to merge_pob and runs the worker thread
"""
from __future__ import annotations

import math
import queue
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable, Optional

from merge_pob import MergeError, merge_sources, prepare_sources

APP_NAME = "PoB Build Merger"
APP_VERSION = "1.0.0"


# ============================================================================
# 1. THEME
# ============================================================================

class Theme:
    """Single source of truth for colours, fonts and metrics."""

    # --- surfaces -----------------------------------------------------------
    BG = "#15161b"            # window background
    PANEL = "#1d1e25"         # cards / panels
    PANEL_BORDER = "#2b2d38"
    INPUT_BG = "#14151a"      # text fields (darker than their panel)
    INPUT_BORDER = "#323544"
    OUTPUT_BG = "#121318"
    STATUS_BG = "#111216"
    SEPARATOR = "#262833"

    # --- text ---------------------------------------------------------------
    TEXT = "#e7e8ee"
    TEXT_MUTED = "#8c8fa0"
    TEXT_PLACEHOLDER = "#6f7287"
    CODE_TEXT = "#c3c6dc"

    # --- accent (restrained indigo/purple) ----------------------------------
    ACCENT = "#7c6cf0"
    ACCENT_HOVER = "#8f81f5"
    ACCENT_PRESSED = "#6a5ae0"
    ACCENT_DIM = "#4b4296"    # used for the "busy" pulse

    # --- secondary / danger buttons -----------------------------------------
    BTN = "#272933"
    BTN_HOVER = "#2f3140"
    BTN_PRESSED = "#222430"
    BTN_BORDER = "#3a3d4e"
    BTN_BORDER_HOVER = "#4a4e63"
    DANGER_TEXT = "#f0848d"
    DANGER_BG = "#3a2429"
    DANGER_BG_PRESSED = "#321f23"
    DANGER_BORDER = "#7a3d46"
    DISABLED_BG = "#22232c"
    DISABLED_FG = "#666a7c"

    # --- status -------------------------------------------------------------
    STATUS_IDLE = "#5d6073"
    STATUS_OK = "#4cc38a"
    STATUS_ERROR = "#f0707a"

    # --- metrics (design pixels at 96 DPI; always pass through px()) --------
    RADIUS_PANEL = 10
    RADIUS_CONTROL = 6
    WINDOW_PAD = 24
    PANEL_PAD_X = 18
    PANEL_PAD_Y = 16
    GAP = 14                  # vertical gap between panels
    FIELD_PAD_X = 10
    FIELD_PAD_Y = 6
    BUTTON_HEIGHT = 34

    # --- runtime state (filled by setup) ------------------------------------
    scale = 1.0
    fonts: dict[str, tkfont.Font] = {}

    @classmethod
    def px(cls, value: float) -> int:
        """Scale a design pixel value for the current display DPI."""
        if value == 0:
            return 0
        return max(1, int(round(value * cls.scale)))

    @classmethod
    def setup(cls, root: tk.Tk) -> None:
        cls.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)

        installed = set(tkfont.families(root))

        def pick(candidates: list[str], fallback: str) -> str:
            return next((f for f in candidates if f in installed), fallback)

        sans = pick(["Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text",
                     "Helvetica Neue", "Noto Sans", "DejaVu Sans", "Arial"], "TkDefaultFont")
        mono = pick(["Cascadia Mono", "Consolas", "JetBrains Mono", "SF Mono", "Menlo",
                     "DejaVu Sans Mono", "Courier New"], "TkFixedFont")

        def make(family: str, size: int, weight: str = "normal") -> tkfont.Font:
            return tkfont.Font(root=root, family=family, size=size, weight=weight)

        cls.fonts = {
            "body": make(sans, 10),
            "small": make(sans, 9),
            "label": make(sans, 9, "bold"),
            "bold": make(sans, 10, "bold"),
            "brand": make(sans, 11, "bold"),
            "heading": make(sans, 20, "bold"),
            "button": make(sans, 10),
            "button_bold": make(sans, 10, "bold"),
            "mono": make(mono, 10),
        }


px = Theme.px

SCROLLBAR_STYLE = "Dark.Vertical.TScrollbar"
SCROLLBAR_HIDDEN_STYLE = "DarkHidden.Vertical.TScrollbar"


# ============================================================================
# 2. DRAWING HELPERS
# ============================================================================

def parent_bg(widget: tk.Misc) -> str:
    try:
        return widget.cget("bg")
    except tk.TclError:
        return Theme.BG


def round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
               radius: float, **kw) -> int:
    """Rounded rectangle as a smoothed polygon (straight edges, curved corners)."""
    r = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1,
           x2, y1 + r, x2, y1 + r, x2, y2 - r, x2, y2 - r, x2, y2,
           x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2, x1, y2,
           x1, y2 - r, x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def draw_icon(canvas: tk.Canvas, name: str, cx: float, cy: float, size: float,
              color: str, width: float) -> None:
    """Small line icons drawn with canvas primitives (crisp, font-independent)."""
    s = size
    line = dict(fill=color, width=width, capstyle="round", joinstyle="round")
    if name == "plus":
        canvas.create_line(cx - .42 * s, cy, cx + .42 * s, cy, **line)
        canvas.create_line(cx, cy - .42 * s, cx, cy + .42 * s, **line)
    elif name == "close":
        d = .34 * s
        canvas.create_line(cx - d, cy - d, cx + d, cy + d, **line)
        canvas.create_line(cx - d, cy + d, cx + d, cy - d, **line)
    elif name == "check":
        canvas.create_line(cx - .42 * s, cy + .02 * s, cx - .12 * s, cy + .32 * s,
                           cx + .44 * s, cy - .32 * s, **line)
    elif name == "trash":
        canvas.create_line(cx - .5 * s, cy - .26 * s, cx + .5 * s, cy - .26 * s, **line)
        canvas.create_line(cx - .18 * s, cy - .26 * s, cx - .18 * s, cy - .45 * s,
                           cx + .18 * s, cy - .45 * s, cx + .18 * s, cy - .26 * s, **line)
        canvas.create_polygon(cx - .36 * s, cy - .12 * s, cx + .36 * s, cy - .12 * s,
                              cx + .28 * s, cy + .5 * s, cx - .28 * s, cy + .5 * s,
                              outline=color, fill="", width=width, joinstyle="round")
        canvas.create_line(cx, cy + .02 * s, cx, cy + .34 * s, **line)
    elif name == "copy":
        canvas.create_line(cx - .2 * s, cy - .2 * s, cx - .2 * s, cy - .5 * s,
                           cx + .5 * s, cy - .5 * s, cx + .5 * s, cy + .2 * s,
                           cx + .2 * s, cy + .2 * s, **line)
        canvas.create_rectangle(cx - .5 * s, cy - .2 * s, cx + .2 * s, cy + .5 * s,
                                outline=color, width=width)


def _seg_dist(px_: float, py_: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px_ - ax) * dx + (py_ - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px_ - (ax + t * dx), py_ - (ay + t * dy))


def make_app_icon(size: int) -> tk.PhotoImage:
    """Rounded accent square with a 'merge' glyph (two lines joining into one)."""
    img = tk.PhotoImage(width=size, height=size)
    accent = tuple(int(Theme.ACCENT[i:i + 2], 16) for i in (1, 3, 5))
    strokes = [(.29, .26, .5, .53), (.71, .26, .5, .53), (.5, .53, .5, .77)]
    half_w, corner, samples = .068, .24, 3

    def in_square(x: float, y: float) -> bool:
        dx = max(abs(x - .5) - (.5 - corner), 0.0)
        dy = max(abs(y - .5) - (.5 - corner), 0.0)
        return dx * dx + dy * dy <= corner * corner

    for y in range(size):
        row = []
        for x in range(size):
            inside = glyph = 0
            for sy in range(samples):
                for sx in range(samples):
                    u = (x + (sx + .5) / samples) / size
                    v = (y + (sy + .5) / samples) / size
                    if in_square(u, v):
                        inside += 1
                        if any(_seg_dist(u, v, *s) <= half_w for s in strokes):
                            glyph += 1
            if inside == 0:
                row.append("#000000")
                continue
            mix = glyph / inside
            rgb = tuple(int(a + (255 - a) * mix) for a in accent)
            row.append("#%02x%02x%02x" % rgb)
        img.put("{" + " ".join(row) + "}", to=(0, y))
        for x in range(size):  # hard transparency outside the rounded square
            u, v = (x + .5) / size, (y + .5) / size
            if not in_square(u, v):
                img.transparency_set(x, y, True)
    return img


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def enable_dark_titlebar(win: tk.Tk) -> None:
    """Dark native title bar on Windows 10/11 (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old id)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def apply_ttk_styles(root: tk.Tk) -> None:
    """Only the scrollbar is a ttk widget; style it to match the theme."""
    style = ttk.Style(root)
    style.theme_use("clam")
    layout = [("Vertical.Scrollbar.trough", {
        "sticky": "ns",
        "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
    })]
    for name, thumb, thumb_active in (
            (SCROLLBAR_STYLE, "#3a3d4e", "#555a70"),
            (SCROLLBAR_HIDDEN_STYLE, Theme.OUTPUT_BG, Theme.OUTPUT_BG)):
        style.layout(name, layout)
        style.configure(name, background=thumb, troughcolor=Theme.OUTPUT_BG,
                        bordercolor=Theme.OUTPUT_BG, lightcolor=thumb, darkcolor=thumb,
                        gripcount=0, relief="flat", arrowsize=px(10), width=px(10))
        style.map(name, background=[("active", thumb_active), ("pressed", thumb_active)],
                  lightcolor=[("active", thumb_active)], darkcolor=[("active", thumb_active)])


# ============================================================================
# 3. REUSABLE WIDGETS
# ============================================================================

class RoundedSurface(tk.Frame):
    """A rounded, bordered container. Put children inside `.body`.

    A canvas draws the rounded background behind `.body`; `.body` is packed with
    an inset, so Tk's normal geometry management sizes the whole surface (it
    shrinks to fit its content, or expands when the parent gives it room).
    """

    def __init__(self, master: tk.Misc, *, fill: str, border: str,
                 radius: float = Theme.RADIUS_PANEL, pad: tuple[float, float] = (0, 0)):
        outer = parent_bg(master)
        super().__init__(master, bg=outer, bd=0, highlightthickness=0)
        self.fill_color = fill
        self.border_color = border
        self.corner = px(radius)
        self.background = tk.Canvas(self, bg=outer, highlightthickness=0, bd=0)
        self.background.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=fill)
        self.body.pack(fill="both", expand=True, padx=px(pad[0]), pady=px(pad[1]))
        self.background.bind("<Configure>", lambda _e: self._redraw())
        self.background.bind("<Button-1>", self.on_background_click)

    def on_background_click(self, _event: tk.Event) -> None:
        """Hook for subclasses (e.g. focus the field when its border is clicked)."""

    def set_border(self, color: str) -> None:
        self.border_color = color
        self._redraw()

    def _redraw(self) -> None:
        canvas = self.background
        canvas.delete("shape")
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w < 4 or h < 4:
            return
        round_rect(canvas, .5, .5, w - 1.5, h - 1.5, self.corner,
                   fill=self.fill_color, outline=self.border_color, width=1, tags="shape")


class Button(tk.Canvas):
    """Flat rounded button with hover / pressed / disabled states and optional icon.

    variant: primary | secondary | danger | ghost | ghost_danger
    """

    def __init__(self, master: tk.Misc, text: str = "", command: Optional[Callable[[], None]] = None,
                 variant: str = "secondary", icon: Optional[str] = None,
                 height: int = Theme.BUTTON_HEIGHT, padx: int = 14):
        bg = parent_bg(master)
        T = Theme
        styles = {
            "primary": dict(fill=T.ACCENT, hover=T.ACCENT_HOVER, press=T.ACCENT_PRESSED,
                            border=T.ACCENT, border_hover=T.ACCENT_HOVER,
                            fg="#ffffff", fg_hover="#ffffff", font="button_bold"),
            "secondary": dict(fill=T.BTN, hover=T.BTN_HOVER, press=T.BTN_PRESSED,
                              border=T.BTN_BORDER, border_hover=T.BTN_BORDER_HOVER,
                              fg=T.TEXT, fg_hover=T.TEXT, font="button"),
            "danger": dict(fill=T.BTN, hover=T.DANGER_BG, press=T.DANGER_BG_PRESSED,
                           border=T.BTN_BORDER, border_hover=T.DANGER_BORDER,
                           fg=T.DANGER_TEXT, fg_hover=T.DANGER_TEXT, font="button"),
            "ghost": dict(fill=bg, hover=T.BTN, press=T.BTN_PRESSED, border=bg,
                          border_hover=T.BTN, fg=T.TEXT_MUTED, fg_hover=T.TEXT, font="button"),
            "ghost_danger": dict(fill=bg, hover=T.DANGER_BG, press=T.DANGER_BG_PRESSED,
                                 border=bg, border_hover=T.DANGER_BG,
                                 fg=T.TEXT_MUTED, fg_hover=T.DANGER_TEXT, font="button"),
        }
        self.style = styles[variant]
        self.label_font = Theme.fonts[self.style["font"]]
        self.label = text
        self.icon = icon
        self.command = command
        self.btn_height = px(height)
        self.btn_padx = px(padx)
        self.icon_size = px(14)
        self.icon_gap = px(8)
        self.btn_state = "normal"
        self.btn_enabled = True
        super().__init__(master, bg=bg, highlightthickness=0, bd=0,
                         height=self.btn_height, width=self._natural_width(), cursor="hand2")
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", lambda _e: self._set_state("hover"))
        self.bind("<Leave>", lambda _e: self._set_state("normal"))
        self.bind("<ButtonPress-1>", lambda _e: self._set_state("press"))
        self.bind("<ButtonRelease-1>", self._on_release)

    # ---- public API --------------------------------------------------------
    def set_text(self, text: str) -> None:
        self.label = text
        self.configure(width=self._natural_width())
        self._redraw()

    def set_icon(self, icon: Optional[str]) -> None:
        self.icon = icon
        self.configure(width=self._natural_width())
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self.btn_enabled = enabled
        self.btn_state = "normal"
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    # ---- internals ---------------------------------------------------------
    def _content_width(self) -> int:
        parts = []
        if self.icon:
            parts.append(self.icon_size)
        if self.label:
            parts.append(self.label_font.measure(self.label))
        return sum(parts) + (self.icon_gap if len(parts) == 2 else 0)

    def _natural_width(self) -> int:
        if not self.label and self.icon:
            return self.btn_height  # square icon button
        return self._content_width() + 2 * self.btn_padx

    def _set_state(self, state: str) -> None:
        if self.btn_enabled:
            self.btn_state = state
            self._redraw()

    def _on_release(self, event: tk.Event) -> None:
        if not self.btn_enabled:
            return
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self.btn_state = "hover" if inside else "normal"
        self._redraw()
        if inside and self.command:
            self.command()

    def _colors(self) -> tuple[str, str, str]:
        s = self.style
        if not self.btn_enabled:
            return Theme.DISABLED_BG, Theme.DISABLED_BG, Theme.DISABLED_FG
        if self.btn_state == "press":
            return s["press"], s["border_hover"], s["fg_hover"]
        if self.btn_state == "hover":
            return s["hover"], s["border_hover"], s["fg_hover"]
        return s["fill"], s["border"], s["fg"]

    def _redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            w, h = int(float(self.cget("width"))), int(float(self.cget("height")))
        fill, border, fg = self._colors()
        round_rect(self, .5, .5, w - 1.5, h - 1.5, px(Theme.RADIUS_CONTROL),
                   fill=fill, outline=border, width=1)
        x = (w - self._content_width()) / 2
        cy = h / 2
        if self.icon:
            draw_icon(self, self.icon, x + self.icon_size / 2, cy, self.icon_size,
                      fg, 1.5 * Theme.scale)
            x += self.icon_size + (self.icon_gap if self.label else 0)
        if self.label:
            self.create_text(x, cy, text=self.label, font=self.label_font, fill=fg, anchor="w")


class TextField(RoundedSurface):
    """Single-line input with placeholder, focus ring and a right-click menu."""

    def __init__(self, master: tk.Misc, placeholder: str):
        super().__init__(master, fill=Theme.INPUT_BG, border=Theme.INPUT_BORDER,
                         radius=Theme.RADIUS_CONTROL,
                         pad=(Theme.FIELD_PAD_X, Theme.FIELD_PAD_Y))
        self.placeholder = placeholder
        self.showing_placeholder = False
        self.var = tk.StringVar()
        self.entry = tk.Entry(self.body, textvariable=self.var, font=Theme.fonts["body"],
                              bg=Theme.INPUT_BG, fg=Theme.TEXT, insertbackground=Theme.TEXT,
                              selectbackground=Theme.ACCENT, selectforeground="#ffffff",
                              relief="flat", bd=0, highlightthickness=0, exportselection=False)
        self.entry.pack(fill="x")

        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<Control-a>", self._select_all)
        self.entry.bind("<Button-3>", self._popup_menu)
        self.menu = tk.Menu(self, tearoff=0, bg=Theme.PANEL, fg=Theme.TEXT,
                            activebackground=Theme.ACCENT, activeforeground="#ffffff",
                            bd=0, relief="flat")
        for label, event in (("Cut", "<<Cut>>"), ("Copy", "<<Copy>>"), ("Paste", "<<Paste>>")):
            self.menu.add_command(label=label,
                                  command=lambda ev=event: self.entry.event_generate(ev))
        self._show_placeholder()

    def on_background_click(self, _event: tk.Event) -> None:
        self.entry.focus_set()

    def value(self) -> str:
        return "" if self.showing_placeholder else self.var.get().strip()

    def reset(self) -> None:
        self.showing_placeholder = False
        self.var.set("")
        self.entry.configure(fg=Theme.TEXT)
        if self.focus_get() is not self.entry:
            self._show_placeholder()

    def _show_placeholder(self) -> None:
        if not self.showing_placeholder and not self.var.get():
            self.showing_placeholder = True
            self.var.set(self.placeholder)
            self.entry.configure(fg=Theme.TEXT_PLACEHOLDER)

    def _on_focus_in(self, _event: tk.Event) -> None:
        if self.showing_placeholder:
            self.showing_placeholder = False
            self.var.set("")
            self.entry.configure(fg=Theme.TEXT)
        self.set_border(Theme.ACCENT)

    def _on_focus_out(self, _event: tk.Event) -> None:
        self._show_placeholder()
        self.set_border(Theme.INPUT_BORDER)

    def _select_all(self, _event: tk.Event) -> str:
        self.entry.select_range(0, "end")
        self.entry.icursor("end")
        return "break"

    def _popup_menu(self, event: tk.Event) -> None:
        self.entry.focus_set()
        self.menu.tk_popup(event.x_root, event.y_root)


# ============================================================================
# 4. PANELS
# ============================================================================

class HeaderBar(tk.Frame):
    """App Name + About, then the heading and description."""

    def __init__(self, master: tk.Misc, on_about: Callable[[], None]):
        super().__init__(master, bg=Theme.BG)
        top = tk.Frame(self, bg=Theme.BG)
        tk.Label(self, text="Combine builds into one PoB code", font=Theme.fonts["heading"],
                 bg=Theme.BG, fg=Theme.TEXT, anchor="w").pack(fill="x", pady=(px(22), 0))
        tk.Label(self, text="Merge multiple pobb.in, Pastebin, PoEDB.tw, PoE.Ninja, PoB.codes, "
                            "Maxroll, or raw PoB codes.",
                 font=Theme.fonts["body"], bg=Theme.BG, fg=Theme.TEXT_MUTED,
                 anchor="w", justify="left").pack(fill="x", pady=(px(4), 0))


class BuildRow:
    """One input row: number, name, link/code, remove."""

    def __init__(self, host: tk.Frame, on_remove: Callable[["BuildRow"], None]):
        self.number = tk.Label(host, bg=Theme.PANEL, fg=Theme.TEXT_MUTED,
                               font=Theme.fonts["small"], anchor="center")
        self.name = TextField(host, "Name (e.g. Leveling)")
        self.source = TextField(host, "Paste a link or PoB code")
        self.remove_btn = Button(host, command=lambda: on_remove(self), variant="ghost_danger",
                                 icon="close", height=30)

    def place(self, index: int) -> None:
        self.number.configure(text=str(index))
        row = index  # grid row 0 is the column header
        self.number.grid(row=row, column=0, padx=(0, px(6)), pady=px(3))
        self.name.grid(row=row, column=1, sticky="ew", padx=(0, px(10)), pady=px(3))
        self.source.grid(row=row, column=2, sticky="ew", padx=(0, px(10)), pady=px(3))
        self.remove_btn.grid(row=row, column=3, pady=px(3))

    def destroy(self) -> None:
        for widget in (self.number, self.name, self.source, self.remove_btn):
            widget.destroy()

    def values(self) -> tuple[str, str]:
        return self.name.value(), self.source.value()

    def reset(self) -> None:
        self.name.reset()
        self.source.reset()


class InputPanel(RoundedSurface):
    INITIAL_ROWS = 5

    def __init__(self, master: tk.Misc, on_merge: Callable[[], None],
                 on_clear: Callable[[], None], on_layout_change: Callable[[], None]):
        super().__init__(master, fill=Theme.PANEL, border=Theme.PANEL_BORDER,
                         pad=(Theme.PANEL_PAD_X, Theme.PANEL_PAD_Y))
        self.on_clear = on_clear
        self.on_layout_change = on_layout_change
        self.rows: list[BuildRow] = []

        grid = self.grid_host = tk.Frame(self.body, bg=Theme.PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(0, minsize=px(30))
        grid.columnconfigure(1, weight=1, minsize=px(170))
        grid.columnconfigure(2, weight=3, minsize=px(280))
        grid.columnconfigure(3, minsize=px(34))
        header_font = Theme.fonts["label"]
        for column, text in ((0, "#"), (1, "NAME"), (2, "LINK OR CODE")):
            tk.Label(grid, text=text, font=header_font, bg=Theme.PANEL, fg=Theme.TEXT_MUTED,
                     anchor="center" if column == 0 else "w").grid(
                row=0, column=column, sticky="ew", pady=(0, px(4)),
                padx=(0, px(6)) if column == 0 else (px(2), 0))

        bar = tk.Frame(self.body, bg=Theme.PANEL)
        bar.pack(fill="x", pady=(px(16), 0))
        self.add_btn = Button(bar, "Add row", self.add_row, variant="secondary", icon="plus")
        self.add_btn.pack(side="left")
        self.clear_btn = Button(bar, "Clear", self._clear, variant="danger", icon="trash")
        self.clear_btn.pack(side="left", padx=(px(8), 0))
        self.merge_btn = Button(bar, "Merge", on_merge, variant="primary", height=38, padx=28)
        self.merge_btn.pack(side="right")
        tk.Label(bar, text="Row 1 sets class & level", font=Theme.fonts["small"],
                 bg=Theme.PANEL, fg=Theme.TEXT_MUTED).pack(side="right", padx=(0, px(16)))

        for _ in range(self.INITIAL_ROWS):
            self._append_row()
        self._render_rows()

    # ---- public API --------------------------------------------------------
    def get_rows(self) -> list[tuple[str, str]]:
        return [row.values() for row in self.rows]

    def clear_rows(self) -> None:
        for row in self.rows:
            row.reset()

    def set_busy(self, busy: bool) -> None:
        self.merge_btn.set_text("Merging…" if busy else "Merge")
        for button in (self.merge_btn, self.add_btn, self.clear_btn):
            button.set_enabled(not busy)

    def add_row(self) -> None:
        self._append_row()
        self._render_rows()
        self.on_layout_change()

    # ---- internals ---------------------------------------------------------
    def _append_row(self) -> None:
        self.rows.append(BuildRow(self.grid_host, self._remove_row))

    def _render_rows(self) -> None:
        for index, row in enumerate(self.rows, 1):
            row.place(index)

    def _remove_row(self, row: BuildRow) -> None:
        if len(self.rows) <= 1:
            row.reset()
            return
        self.rows.remove(row)
        row.destroy()
        self._render_rows()
        self.on_layout_change()

    def _clear(self) -> None:
        self.clear_rows()
        self.on_clear()


class OutputPanel(RoundedSurface):
    PLACEHOLDER = "Your merged PoB code will appear here"

    def __init__(self, master: tk.Misc):
        super().__init__(master, fill=Theme.PANEL, border=Theme.PANEL_BORDER,
                         pad=(Theme.PANEL_PAD_X, Theme.PANEL_PAD_Y))
        self.code = ""
        self.flash_job: Optional[str] = None

        header = tk.Frame(self.body, bg=Theme.PANEL)
        header.pack(fill="x", pady=(0, px(10)))
        tk.Label(header, text="Merged code", font=Theme.fonts["bold"], bg=Theme.PANEL,
                 fg=Theme.TEXT).pack(side="left")
        self.copy_btn = Button(header, "Copy", self.copy_to_clipboard, variant="secondary",
                               icon="copy", height=30, padx=12)
        self.copy_btn.pack(side="right")
        self.copy_btn.set_enabled(False)
        self.meta = tk.Label(header, text="", font=Theme.fonts["small"], bg=Theme.PANEL,
                             fg=Theme.TEXT_MUTED)
        self.meta.pack(side="right", padx=(0, px(12)))

        editor = RoundedSurface(self.body, fill=Theme.OUTPUT_BG, border=Theme.INPUT_BORDER,
                                radius=Theme.RADIUS_CONTROL, pad=(3, 3))
        editor.pack(fill="both", expand=True)
        self.scroll = ttk.Scrollbar(editor.body, orient="vertical",
                                    style=SCROLLBAR_HIDDEN_STYLE)
        self.text = tk.Text(editor.body, wrap="char", height=6, font=Theme.fonts["mono"],
                            bg=Theme.OUTPUT_BG, fg=Theme.CODE_TEXT, insertbackground=Theme.TEXT,
                            selectbackground=Theme.ACCENT, selectforeground="#ffffff",
                            relief="flat", bd=0, highlightthickness=0,
                            padx=px(10), pady=px(8), yscrollcommand=self._on_yscroll)
        self.scroll.configure(command=self.text.yview)
        self.scroll.pack(side="right", fill="y", padx=(0, px(3)), pady=px(3))
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("error", foreground=Theme.STATUS_ERROR)
        self.text.bind("<Key>", self._block_edit)
        self.text.bind("<Control-a>", self._select_all)
        self.text.bind("<<Paste>>", lambda _e: "break")
        self.text.bind("<<Cut>>", lambda _e: "break")

        self.hint = tk.Label(self.text, text=self.PLACEHOLDER, font=Theme.fonts["body"],
                             bg=Theme.OUTPUT_BG, fg=Theme.TEXT_PLACEHOLDER)
        self.hint.place(relx=0.5, rely=0.5, anchor="center")
        self.hint.bind("<Button-1>", lambda _e: self.text.focus_set())

    # ---- public API --------------------------------------------------------
    def clear(self) -> None:
        self.code = ""
        self.text.delete("1.0", "end")
        self.hint.place(relx=0.5, rely=0.5, anchor="center")
        self.meta.configure(text="")
        self.copy_btn.set_enabled(False)

    def show_code(self, code: str, build_count: int) -> None:
        self.clear()
        self.code = code
        self.hint.place_forget()
        self.text.insert("1.0", code)
        noun = "build" if build_count == 1 else "builds"
        self.meta.configure(text=f"{build_count} {noun} · {len(code):,} characters")
        self.copy_btn.set_enabled(True)

    def show_error(self, message: str) -> None:
        self.clear()
        self.hint.place_forget()
        self.text.insert("1.0", message, "error")

    def copy_to_clipboard(self) -> bool:
        if not self.code:
            return False
        self.clipboard_clear()
        self.clipboard_append(self.code)
        self.copy_btn.set_text("Copied")
        self.copy_btn.set_icon("check")
        if self.flash_job:
            self.after_cancel(self.flash_job)
        self.flash_job = self.after(1600, self._reset_copy_button)
        return True

    # ---- internals ---------------------------------------------------------
    def _reset_copy_button(self) -> None:
        self.flash_job = None
        self.copy_btn.set_text("Copy")
        self.copy_btn.set_icon("copy")

    def _on_yscroll(self, first: str, last: str) -> None:
        """Show the scrollbar thumb only when the content actually overflows."""
        self.scroll.set(first, last)
        fits = float(first) <= 0.0 and float(last) >= 1.0
        self.scroll.configure(style=SCROLLBAR_HIDDEN_STYLE if fits else SCROLLBAR_STYLE)

    def _block_edit(self, event: tk.Event) -> Optional[str]:
        if event.state & 0x4 and event.keysym.lower() == "c":
            return None
        if event.keysym in ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next"):
            return None
        return "break"

    def _select_all(self, _event: tk.Event) -> str:
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"


class StatusBar(tk.Frame):
    KINDS = {"ready": Theme.STATUS_IDLE, "busy": Theme.ACCENT,
             "ok": Theme.STATUS_OK, "error": Theme.STATUS_ERROR}

    def __init__(self, master: tk.Misc):
        super().__init__(master, bg=Theme.STATUS_BG)
        tk.Frame(self, bg=Theme.SEPARATOR, height=1).pack(side="top", fill="x")
        inner = tk.Frame(self, bg=Theme.STATUS_BG)
        inner.pack(fill="x", padx=px(Theme.WINDOW_PAD), pady=px(6))
        size = px(10)
        self.dot = tk.Canvas(inner, width=size, height=size, bg=Theme.STATUS_BG,
                             highlightthickness=0, bd=0)
        self.dot.pack(side="left")
        self.dot_item = self.dot.create_oval(1, 1, size - 1, size - 1, fill=Theme.STATUS_IDLE,
                                             outline="")
        self.label = tk.Label(inner, text="", font=Theme.fonts["small"], bg=Theme.STATUS_BG,
                              fg=Theme.TEXT_MUTED, anchor="w")
        self.label.pack(side="left", padx=(px(8), 0))
        tk.Label(inner, text=f"v{APP_VERSION}", font=Theme.fonts["small"],
                 bg=Theme.STATUS_BG, fg=Theme.TEXT_PLACEHOLDER).pack(side="right")
        self.blink_job: Optional[str] = None
        self.blink_on = True
        self.set("ready", "Ready.")

    def set(self, kind: str, text: str) -> None:
        self._stop_blink()
        self.dot.itemconfigure(self.dot_item, fill=self.KINDS[kind])
        self.label.configure(text=text, fg=Theme.STATUS_ERROR if kind == "error" else Theme.TEXT_MUTED)
        if kind == "busy":
            self._blink()

    def _blink(self) -> None:
        self.blink_on = not self.blink_on
        self.dot.itemconfigure(self.dot_item,
                               fill=Theme.ACCENT if self.blink_on else Theme.ACCENT_DIM)
        self.blink_job = self.after(450, self._blink)

    def _stop_blink(self) -> None:
        if self.blink_job:
            self.after_cancel(self.blink_job)
            self.blink_job = None


class AboutDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk):
        super().__init__(parent, bg=Theme.PANEL)
        self.withdraw()
        self.title(f"About {APP_NAME}")
        self.resizable(False, False)
        self.transient(parent)

        wrap = px(380)
        body = tk.Frame(self, bg=Theme.PANEL)
        body.pack(padx=px(28), pady=px(24))

        head = tk.Frame(body, bg=Theme.PANEL)
        head.pack(fill="x")
        self.icon_image = make_app_icon(px(44))
        tk.Label(head, image=self.icon_image, bg=Theme.PANEL).pack(side="left")
        titles = tk.Frame(head, bg=Theme.PANEL)
        titles.pack(side="left", padx=(px(14), 0))
        tk.Label(titles, text=APP_NAME, font=Theme.fonts["brand"], bg=Theme.PANEL,
                 fg=Theme.TEXT, anchor="w").pack(fill="x")
        tk.Label(titles, text=f"Version {APP_VERSION}", font=Theme.fonts["small"],
                 bg=Theme.PANEL, fg=Theme.TEXT_MUTED, anchor="w").pack(fill="x")

        paragraphs = (
            "Combines several Path of Building builds into a single share code. Each build "
            "becomes its own passive tree, skill set, item set and config set, named after "
            "the row it came from. Switch between them with PoB's normal dropdowns.",
            "The first row decides the class and level of the merged build.",
            "Supported sources: pobb.in, Pastebin, PoEDB.tw, PoE.Ninja, PoB.codes, "
            "Maxroll (pob links), or a raw PoB code.",
        )
        for text in paragraphs:
            tk.Label(body, text=text, font=Theme.fonts["body"], bg=Theme.PANEL,
                     fg=Theme.TEXT_MUTED, wraplength=wrap, justify="left",
                     anchor="w").pack(fill="x", pady=(px(14), 0))

        Button(body, "Close", self.destroy, variant="primary", padx=26).pack(
            anchor="e", pady=(px(20), 0))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        enable_dark_titlebar(self)
        self.deiconify()
        self.grab_set()


# ============================================================================
# 5. APPLICATION
# ============================================================================

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.results: queue.Queue = queue.Queue()

        root.title(APP_NAME)
        root.configure(bg=Theme.BG)
        self.min_width = px(780)
        root.minsize(self.min_width, px(600))
        root.geometry(f"{px(940)}x{px(720)}")
        self.window_icon = make_app_icon(px(64))
        root.iconphoto(True, self.window_icon)
        apply_ttk_styles(root)

        pad = px(Theme.WINDOW_PAD)
        self.status = StatusBar(root)
        self.status.pack(side="bottom", fill="x")

        HeaderBar(root, self.show_about).pack(side="top", fill="x", padx=pad, pady=(px(18), 0))
        tk.Frame(root, bg=Theme.SEPARATOR, height=1).pack(
            side="top", fill="x", padx=pad, pady=(px(18), px(Theme.GAP)))

        content = tk.Frame(root, bg=Theme.BG)
        content.pack(side="top", fill="both", expand=True, padx=pad, pady=(0, px(Theme.GAP)))
        self.input = InputPanel(content, on_merge=self.start_merge, on_clear=self.on_clear,
                                on_layout_change=self.ensure_fit)
        self.input.pack(side="top", fill="x")
        self.output = OutputPanel(content)
        self.output.pack(side="top", fill="both", expand=True, pady=(px(Theme.GAP), 0))

        root.bind("<Control-Return>", lambda _e: self.start_merge())
        root.after(100, self.poll)

        # Minimum height = what the content needs, so the output never gets squashed.
        root.update_idletasks()
        needed = root.winfo_reqheight()
        root.minsize(self.min_width, needed)
        self.window_size = (px(940), max(px(720), needed))
        root.geometry("%dx%d" % self.window_size)

    # ---- window ------------------------------------------------------------
    def show_about(self) -> None:
        AboutDialog(self.root)

    def ensure_fit(self) -> None:
        """Keep the minimum size in step with the rows; grow the window if it must."""
        def grow() -> None:
            self.root.update_idletasks()
            needed = self.root.winfo_reqheight()
            self.root.minsize(self.min_width, needed)
            if needed > self.root.winfo_height():
                self.root.geometry(f"{self.root.winfo_width()}x{needed}")
        self.root.after(60, grow)

    # ---- actions -----------------------------------------------------------
    def on_clear(self) -> None:
        self.output.clear()
        self.status.set("ready", "Ready.")

    def start_merge(self) -> None:
        if not self.input.merge_btn.btn_enabled:
            return
        sources = prepare_sources(self.input.get_rows())
        if not sources:
            self.status.set("error", "Add at least one link or code.")
            return
        self.input.set_busy(True)
        self.output.clear()
        self.status.set("busy", "Merging builds…")
        threading.Thread(target=self._worker, args=(sources,), daemon=True).start()

    def _worker(self, sources) -> None:
        try:
            result = merge_sources(
                sources, on_progress=lambda i, n, name: self.results.put(("progress", i, n, name)))
            self.results.put(("done", result))
        except MergeError as exc:
            self.results.put(("error", str(exc)))
        except Exception as exc:  # never let the worker die silently
            self.results.put(("error", f"Unexpected error: {exc}"))

    def poll(self) -> None:
        try:
            while True:
                message = self.results.get_nowait()
                kind = message[0]
                if kind == "progress":
                    _, index, total, name = message
                    self.status.set("busy", f"Merging builds… ({index}/{total}: {name})")
                elif kind == "done":
                    result = message[1]
                    self.output.show_code(result.code, result.build_count)
                    self.output.copy_to_clipboard()
                    self.input.set_busy(False)
                    self.status.set("ok", f"Merge completed — {result.build_count} builds, "
                                          f"{len(result.code):,} characters. Copied to clipboard.")
                elif kind == "error":
                    detail = message[1]
                    self.output.show_error(detail)
                    self.input.set_busy(False)
                    self.status.set("error", "Error: " + detail.splitlines()[0])
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def center_on_screen(root: tk.Tk, width: int, height: int) -> None:
    x = max((root.winfo_screenwidth() - width) // 2, 0)
    y = max((root.winfo_screenheight() - height) // 3, 0)
    root.geometry(f"{width}x{height}+{x}+{y}")


def main() -> None:
    enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    Theme.setup(root)
    app = App(root)
    center_on_screen(root, *app.window_size)
    enable_dark_titlebar(root)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()