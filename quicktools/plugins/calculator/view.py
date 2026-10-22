"""Tkinter UI for the QuickTools calculator plugin."""

from __future__ import annotations

import logging
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Callable

from quicktools import paths
from quicktools.ui_theme import (
    ACCENT,
    BG,
    BORDER,
    DANGER,
    MUTED,
    PANEL,
    ROW,
    ROW_ACTIVE,
    TEXT,
    FlatButton,
    Fonts,
    pick_fonts,
)
from quicktools.plugins.calculator.engine import (
    BASE_LABELS,
    SUPPORTED_BASES,
    ExpressionError,
    convert_bases,
    evaluate_live,
    filter_input,
    format_result,
    normalize_text,
)
from quicktools.plugins.calculator.scratchpad_store import (
    ScratchEntry,
    ScratchpadState,
    load_scratchpad,
    save_scratchpad,
)
from quicktools.plugins.calculator.settings import (
    load_max_records,
    load_result_group_size,
    load_scientific_mode,
    save_max_records,
    save_result_group_size,
    save_scientific_mode,
)

_PAD_X = 12
_SAVE_DEBOUNCE_MS = 400
_KEYPAD_PADY = (2, 12)
_KEYPAD_ROW_PAD = 14
_STATUS_HINT = "自动计算 · Enter 新建下一层 · 支持 0x / 0b / 0o 前缀"
_SIMPLE_STATUS_HINT = "自动计算 · Enter 新建下一层"
# The selected base tag is emphasized with color, weight and size.
_INACTIVE_TAG_SIZE = 9
_ACTIVE_TAG_SIZE = 11
_ACTIVE_VALUE_SIZE = 12
log = logging.getLogger(__name__)

# Light tints keep the keypad airy; the colored strokes come from generated
# icon assets so the symbols look cleaner than raw text glyphs.
_GOOGLE_OPERATOR_STYLES: dict[str, dict[str, str]] = {
    "+": {
        "bg": "#FDECEA",
        "hover": "#FAD2CF",
        "press": "#F6B7B3",
        "icon": "plus",
    },
    "-": {
        "bg": "#FFF7E0",
        "hover": "#FEECB3",
        "press": "#F8DF9C",
        "icon": "minus",
    },
    "*": {
        "bg": "#E6F4EA",
        "hover": "#CEEAD6",
        "press": "#B7DFC2",
        "icon": "multiply",
    },
    "/": {
        "bg": "#E8F0FE",
        "hover": "#D2E3FC",
        "press": "#BACEF9",
        "icon": "divide",
    },
}
_GOOGLE_EQUALS_STYLE = {
    "bg": "#D2E3FC",
    "hover": "#BACEF9",
    "press": "#AECBFA",
    "icon": "equals",
}
_WHITE_KEY_STYLE = {
    "bg": BG,
    "fg": TEXT,
    "highlightthickness": 1,
    "highlightbackground": BORDER,
    "highlightcolor": BORDER,
}


class ScratchRow(tk.Frame):
    """One editable calculation layer."""

    def __init__(
        self,
        view: "CalculatorView",
        row_index: int,
        height: int,
        fonts: Fonts,
    ) -> None:
        super().__init__(view.rows_frame, bg=ROW, height=height)
        self.view = view
        self.row_index = row_index
        self._fonts = fonts
        self._suppress = False
        self.result_value: int | float | None = None
        self.result_base: int | None = None
        self.evaluated_expression: str | None = None
        self.entry_base = 10
        self.memory_expression = ""
        self.active = False

        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)

        self.stripe = tk.Frame(self, bg=ROW, width=3)
        self.stripe.grid(row=0, column=0, sticky="nsw")

        content = tk.Frame(self, bg=ROW)
        content.grid(row=0, column=0, sticky="nsew", padx=(3, 0))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.content = content

        self.var = tk.StringVar(master=self)
        self.entry = tk.Entry(
            content,
            textvariable=self.var,
            bg=ROW,
            fg=TEXT,
            disabledbackground=ROW,
            disabledforeground=MUTED,
            insertbackground=TEXT,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=fonts.m(14),
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=(7, 5), pady=8)

        self.result_label = tk.Label(
            content,
            text="",
            bg=ROW,
            fg=MUTED,
            anchor="e",
            justify="right",
            width=22,
            font=fonts.m(12),
        )
        self.result_label.grid(row=0, column=1, sticky="e", padx=(3, 10))

        self.delete_button = FlatButton(
            content,
            "×",
            lambda: self.view.delete_row(self),
            fonts=fonts,
            font_size=12,
            padx=5,
            pady=2,
            bg=ROW,
            fg=DANGER,
            hover_bg="#FDE2E1",
            press_bg="#F7C9C6",
        )
        # Keep the row-delete affordance unmistakable: red and bold.
        self.delete_button.configure(font=fonts.u(12, "bold"))
        self.delete_button.grid(row=0, column=2, sticky="e", padx=(0, 6))

        self.separator = tk.Frame(self, bg=BORDER, height=1)
        self.separator.grid(row=1, column=0, sticky="ew")

        self.var.trace_add("write", self._on_write)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<KeyPress>", self._on_key)
        self.entry.bind("<Button-1>", lambda _e: self.view.activate_row(self))
        self.result_label.bind("<Button-1>", self._focus_end)
        self.stripe.bind("<Button-1>", self._focus_end)
        content.bind("<Button-1>", self._focus_end)
        view.bind_wheel(self)
        view.bind_wheel(self.entry)
        view.bind_wheel(self.result_label)
        view.bind_wheel(self.stripe)
        view.bind_wheel(content)
        view.bind_wheel(self.delete_button)

    @property
    def expression(self) -> str:
        return self.var.get()

    def set_active(self, active: bool) -> None:
        self.active = active
        bg = ROW_ACTIVE if active else ROW
        for widget in (self, self.content, self.entry):
            widget.configure(bg=bg)
        self.result_label.configure(bg=bg)
        self.delete_button.set_idle_colors(bg=bg)
        self.stripe.configure(bg=ACCENT if active else ROW)

    def restore_expression(self, expression: str) -> None:
        """Load saved text without applying the current base filter."""
        self._suppress = True
        try:
            self.var.set(expression)
            self.entry.icursor(tk.END)
        finally:
            self._suppress = False
        self.memory_expression = expression
        self.clear_result()

    def _on_focus_in(self, _event=None) -> None:
        self.view.activate_row(self)

    def _focus_end(self, _event=None) -> None:
        self.entry.focus_set()
        self.entry.icursor(tk.END)
        self.view.activate_row(self)

    def _on_write(self, *_args) -> None:
        if self._suppress:
            return
        raw = self.var.get()
        try:
            cursor = self.entry.index(tk.INSERT)
        except tk.TclError:
            cursor = len(raw)
        normalized = normalize_text(raw)
        filtered = filter_input(normalized, self.view.base)
        if filtered != raw:
            # Drop rejected characters before the caret so mid-string edits
            # keep the caret next to the text the user just typed.
            new_cursor = len(filter_input(normalized[:cursor], self.view.base))
            self._suppress = True
            try:
                self.var.set(filtered)
                self.entry.icursor(min(new_cursor, len(filtered)))
            finally:
                self._suppress = False
            raw = filtered
        self.entry_base = self.view.base
        self.memory_expression = raw
        if self.evaluated_expression is not None and raw != self.evaluated_expression:
            self.clear_result()
        self.view.on_row_text_changed(self)

    def _on_key(self, event: tk.Event) -> str | None:
        keysym = event.keysym
        if keysym in ("Return", "KP_Enter"):
            self.view.evaluate_row(self)
            return "break"
        if keysym in ("equal", "KP_Equal"):
            self.view.evaluate_row(self)
            return "break"
        if event.state & 0x4:  # do not steal Ctrl shortcuts
            return None
        numpad = {
            "KP_Add": "+",
            "KP_Subtract": "-",
            "KP_Multiply": "*",
            "KP_Divide": "/",
            "KP_Decimal": ".",
            "KP_0": "0",
            "KP_1": "1",
            "KP_2": "2",
            "KP_3": "3",
            "KP_4": "4",
            "KP_5": "5",
            "KP_6": "6",
            "KP_7": "7",
            "KP_8": "8",
            "KP_9": "9",
        }
        if keysym in numpad:
            self.view.insert_text(numpad[keysym])
            return "break"
        return None

    def set_result(self, value: int | float, base: int, formatted: str) -> None:
        self.result_value = value
        self.result_base = base
        self.evaluated_expression = self.var.get()
        self.result_label.configure(text=f"= {formatted}", fg=ACCENT)

    def set_error(self, message: str = "错误") -> None:
        self.result_value = None
        self.result_base = None
        self.evaluated_expression = None
        self.result_label.configure(text=message, fg=DANGER)

    def clear_result(self) -> None:
        self.result_value = None
        self.result_base = None
        self.evaluated_expression = None
        self.result_label.configure(text="", fg=MUTED)

    def clear_all(self) -> None:
        self._suppress = True
        try:
            self.var.set("")
            self.entry.icursor(0)
        finally:
            self._suppress = False
        self.clear_result()
        self.view.on_row_text_changed(self)

    def focus(self) -> None:
        try:
            self.entry.focus_set()
        except tk.TclError:
            pass


class CalculatorView(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        data_dir: Path | None = None,
        on_open_settings: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, bg=BG)
        self.fonts = pick_fonts(self.winfo_toplevel())
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self._on_open_settings = on_open_settings
        self.scientific_mode = load_scientific_mode(self.data_dir)
        self.max_records = load_max_records(self.data_dir)
        self.result_group_size = load_result_group_size(self.data_dir)
        self.base = 10
        self.rows: list[ScratchRow] = []
        self.active_row: ScratchRow | None = None
        self._scratchpad_state = ScratchpadState()
        self._save_job: str | None = None
        self._save_dirty = False
        self._destroyed = False
        self._digit_buttons: dict[str, FlatButton] = {}
        self._base_buttons: dict[int, FlatButton] = {}
        self.operator_buttons: list[FlatButton] = []
        self._keypad_icons: dict[str, tk.PhotoImage] = {}
        self._keypad_faces: dict[FlatButton, tuple[str, tk.PhotoImage]] = {}
        self._keypad_compact = False
        self._load_operator_icons()

        metrics_font = tkfont.Font(family=self.fonts.mono, size=14)
        self._row_height = max(44, metrics_font.metrics("linespace") + 18)
        self._paper_row_min = self._row_height + 2
        # Keep one key row usable at the smallest window height.  The icon
        # buttons fall back to text before the fixed-size operator PNGs would
        # be clipped.
        self._key_row_min = max(30, metrics_font.metrics("linespace") + 6)
        icon_height = max(
            (image.height() for image in self._keypad_icons.values()),
            default=0,
        )
        self._keypad_compact_threshold = icon_height + 10
        self._conversion_vars: dict[int, tk.StringVar] = {}
        self._base_tag_labels: dict[int, tk.Label] = {}
        self._conversion_cells: dict[int, tk.Frame] = {}
        self._conversion_entries: dict[int, tk.Entry] = {}
        self._scroll_job: str | None = None
        self._paper_layout_job: str | None = None
        self.bind("<Destroy>", self._on_destroy, add="+")

        # Grid (instead of pack) lets the paper and the keypad share window
        # height.  When the window shrinks, both rows shrink down to their
        # minsize instead of clipping the bottom keypad: the paper can reach
        # exactly one visible layer and the number keys get shorter.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=5, minsize=self._paper_row_min)
        self.grid_rowconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=0)
        self.grid_rowconfigure(4, weight=0)
        self.grid_rowconfigure(
            5,
            weight=1,
            minsize=self._keypad_min_height() + _KEYPAD_ROW_PAD,
        )

        self._build_header()
        self._build_paper()
        self._build_status()
        self._build_conversion_panel()
        self._build_base_selector()
        self._build_keypad()

        self._apply_scientific_mode(self.scientific_mode, persist=False)
        state = load_scratchpad(
            self.data_dir, max_records=self.max_records
        )
        self._restore_scratchpad(state)
        self._update_digit_states()
        self._refresh_conversion()
        self.set_status(self._default_hint())

    def _load_operator_icons(self) -> None:
        for name in ("plus", "minus", "multiply", "divide", "equals"):
            path = paths.assets_dir() / "keypad" / f"{name}.png"
            try:
                self._keypad_icons[name] = tk.PhotoImage(
                    master=self, file=str(path)
                )
            except Exception as exc:
                log.warning("运算符图标加载失败 %s：%s", path, exc)

    # ------------------------------------------------------------------ UI
    def _build_header(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.grid(
            row=0, column=0, sticky="ew", padx=_PAD_X, pady=(8, 6)
        )
        self._header = header
        self.scratchpad_title = tk.Label(
            header,
            text="草稿纸",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(13, "bold"),
        )
        self.scratchpad_title.pack(side="left")
        self.scientific_button = FlatButton(
            header,
            "科学模式：关",
            self.toggle_scientific_mode,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=5,
        )
        self.scientific_button.pack(side="right")

    def _build_paper(self) -> None:
        border = tk.Frame(self, bg=BORDER)
        border.grid(row=1, column=0, sticky="nsew", padx=_PAD_X)
        holder = tk.Frame(border, bg=ROW)
        holder.pack(fill="both", expand=True, padx=1, pady=1)

        self.canvas = tk.Canvas(
            holder,
            bg=ROW,
            highlightthickness=0,
            bd=0,
            height=self._row_height * 4,
        )
        self.scrollbar = tk.Scrollbar(
            holder,
            orient="vertical",
            command=self.canvas.yview,
            bg=BORDER,
            troughcolor=BG,
            activebackground=ACCENT,
            highlightbackground=BG,
            bd=0,
            relief="flat",
            width=12,
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.rows_frame = tk.Frame(self.canvas, bg=ROW)
        self.rows_frame.grid_columnconfigure(0, weight=1)
        self._syncing_paper = False
        self._canvas_window = self.canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw"
        )
        self.rows_frame.bind("<Configure>", self._on_rows_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind_wheel(self.canvas)

    def _build_status(self) -> None:
        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            self,
            textvariable=self.status_var,
            bg=BG,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(9),
            padx=_PAD_X,
            pady=3,
        )
        self.status_label.grid(row=2, column=0, sticky="ew")

    def _build_conversion_panel(self) -> None:
        outer = tk.Frame(self, bg=BORDER)
        outer.grid(
            row=3, column=0, sticky="ew", padx=_PAD_X, pady=(4, 6)
        )
        self._conversion_outer = outer
        panel = tk.Frame(outer, bg=PANEL)
        panel.pack(fill="x", padx=1, pady=1)
        panel.grid_columnconfigure(0, weight=1, uniform="conv")
        panel.grid_columnconfigure(1, weight=1, uniform="conv")

        # Reserve the height used by the enlarged active tag so switching
        # bases doesn't shift the panel (and the keypad below it).
        probe = tk.Label(panel, font=self.fonts.u(_ACTIVE_TAG_SIZE, "bold"))
        row_minsize = probe.winfo_reqheight() + 8  # cell grid pady (4 + 4)
        probe.destroy()
        panel.grid_rowconfigure(0, minsize=row_minsize)
        panel.grid_rowconfigure(1, minsize=row_minsize)

        # Grid reading order: BIN DEC / OCT HEX.
        for index, base in enumerate((2, 10, 8, 16)):
            cell = tk.Frame(panel, bg=PANEL)
            cell.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(10, 8),
                pady=4,
            )
            cell.grid_columnconfigure(1, weight=1)
            tag = tk.Label(
                cell,
                text=BASE_LABELS[base],
                width=4,
                anchor="w",
                bg=PANEL,
                fg=MUTED,
                font=self.fonts.u(_INACTIVE_TAG_SIZE),
            )
            tag.grid(row=0, column=0, sticky="w")
            var = tk.StringVar(value="—")
            value_entry = tk.Entry(
                cell,
                textvariable=var,
                state="readonly",
                readonlybackground=PANEL,
                bg=PANEL,
                fg=TEXT,
                relief="flat",
                bd=0,
                highlightthickness=0,
                font=self.fonts.m(11),
            )
            value_entry.grid(row=0, column=1, sticky="ew", padx=(4, 0))
            self._conversion_vars[base] = var
            self._base_tag_labels[base] = tag
            self._conversion_cells[base] = cell
            self._conversion_entries[base] = value_entry
            self.bind_wheel(value_entry)

    def _build_base_selector(self) -> None:
        row = tk.Frame(self, bg=BG)
        row.grid(
            row=4, column=0, sticky="ew", padx=_PAD_X, pady=(0, 5)
        )
        self._base_row = row
        tk.Label(
            row,
            text="进制",
            bg=BG,
            fg=MUTED,
            font=self.fonts.u(10),
        ).pack(side="left", padx=(0, 8))
        # Display order only; each button still selects its own base. Chinese
        # annotations make the abbreviation clear without moving any other UI.
        base_button_labels = {
            10: f"{BASE_LABELS[10]} 十进制",
            8: f"{BASE_LABELS[8]} 八进制",
            16: f"{BASE_LABELS[16]} 十六进制",
            2: f"{BASE_LABELS[2]} 二进制",
        }
        for base in (2, 8, 16, 10):
            button = FlatButton(
                row,
                base_button_labels[base],
                lambda b=base: self.set_base(b),
                fonts=self.fonts,
                font_size=10,
                padx=10,
                pady=6,
            )
            button.pack(side="left", padx=3)
            self._base_buttons[base] = button
        self._base_buttons[10].set_active(True)
        self._base_buttons[10].configure(font=self.fonts.u(10, "bold"))

    def _build_keypad(self) -> None:
        keypad = tk.Frame(self, bg=BG)
        keypad.grid(
            row=5,
            column=0,
            sticky="nsew",
            padx=_PAD_X,
            pady=_KEYPAD_PADY,
        )
        self._keypad = keypad
        keypad.grid_columnconfigure(0, weight=1)
        # Function row, A-F row and the four numeric rows share the keypad
        # height by weight, so every key shrinks/grows vertically with the
        # window instead of the bottom row being clipped.
        keypad.grid_rowconfigure(0, weight=1)
        keypad.grid_rowconfigure(1, weight=1)
        keypad.grid_rowconfigure(2, weight=4)
        keypad.bind("<Configure>", self._on_keypad_configure, add="+")

        function_row = tk.Frame(keypad, bg=BG)
        function_row.grid(row=0, column=0, sticky="nsew")
        function_row.grid_rowconfigure(0, weight=1)
        for column in range(6):
            function_row.grid_columnconfigure(column, weight=1, uniform="key")
        functions = [
            ("(", lambda: self.insert_text("(")),
            (")", lambda: self.insert_text(")")),
            ("^", lambda: self.insert_text("^")),
            ("%", lambda: self.insert_text("%")),
            ("C", self.clear_active),
            ("←", self.backspace),
        ]
        for col, (label, command) in enumerate(functions):
            button = FlatButton(
                function_row,
                label,
                command,
                fonts=self.fonts,
                font_size=12,
                pady=9,
            )
            button.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)

        hex_row = tk.Frame(keypad, bg=BG)
        hex_row.grid(row=1, column=0, sticky="nsew")
        hex_row.grid_rowconfigure(0, weight=1)
        self._hex_row = hex_row
        for col, letter in enumerate("ABCDEF"):
            hex_row.grid_columnconfigure(col, weight=1, uniform="hexkey")
            button = FlatButton(
                hex_row,
                letter,
                lambda value=letter: self.insert_text(value),
                fonts=self.fonts,
                font_size=12,
                pady=8,
                **_WHITE_KEY_STYLE,
            )
            button.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)
            self._digit_buttons[letter] = button

        numeric = tk.Frame(keypad, bg=BG)
        numeric.grid(row=2, column=0, sticky="nsew")
        self._numeric = numeric
        for column in range(4):
            numeric.grid_columnconfigure(column, weight=1, uniform="numkey")
        for row in range(4):
            numeric.grid_rowconfigure(row, weight=1)

        # The leftmost column is + - * / (top to bottom); digits occupy the
        # three columns to its right.
        key_rows: list[list[tuple[str, str | None]]] = [
            [("+", "+"), ("7", "7"), ("8", "8"), ("9", "9")],
            [("−", "-"), ("4", "4"), ("5", "5"), ("6", "6")],
            [("×", "*"), ("1", "1"), ("2", "2"), ("3", "3")],
            [("÷", "/"), ("0", "0"), (".", "."), ("=", None)],
        ]
        for row_index, row in enumerate(key_rows):
            for col_index, (label, value) in enumerate(row):
                if value is None:
                    style = _GOOGLE_EQUALS_STYLE
                    image = self._keypad_icons.get(style["icon"])
                    image_options = {"image": image} if image is not None else {}
                    button = FlatButton(
                        numeric,
                        "" if image is not None else label,
                        self.evaluate_active,
                        fonts=self.fonts,
                        font_size=13,
                        pady=2,
                        bg=style["bg"],
                        hover_bg=style["hover"],
                        press_bg=style["press"],
                        **image_options,
                    )
                    button.operator_value = "="
                    self.equal_button = button
                    if image is not None:
                        self._keypad_faces[button] = (label, image)
                elif col_index == 0:
                    style = _GOOGLE_OPERATOR_STYLES[value]
                    image = self._keypad_icons.get(style["icon"])
                    image_options = {"image": image} if image is not None else {}
                    button = FlatButton(
                        numeric,
                        "" if image is not None else label,
                        lambda text=value: self.insert_text(text),
                        fonts=self.fonts,
                        font_size=13,
                        pady=2,
                        bg=style["bg"],
                        hover_bg=style["hover"],
                        press_bg=style["press"],
                        **image_options,
                    )
                    button.operator_value = value
                    self._digit_buttons[value] = button
                    self.operator_buttons.append(button)
                    if image is not None:
                        self._keypad_faces[button] = (label, image)
                else:
                    button = FlatButton(
                        numeric,
                        label,
                        lambda text=value: self.insert_text(text),
                        fonts=self.fonts,
                        font_size=13,
                        pady=10,
                        **_WHITE_KEY_STYLE,
                    )
                    self._digit_buttons[value] = button
                button.grid(
                    row=row_index,
                    column=col_index,
                    sticky="nsew",
                    padx=2,
                    pady=2,
                )

        self.dot_button = self._digit_buttons["."]

    # ------------------------------------------------------- responsive size
    def _keypad_row_count(self) -> int:
        return 6 if self.scientific_mode else 5

    def _keypad_min_height(self) -> int:
        """Minimum keypad height for one comfortable row per key row."""
        return self._keypad_row_count() * self._key_row_min

    def minimum_content_height(self) -> int:
        """Height needed for one paper layer plus compact keypad rows."""
        height = self._header.winfo_reqheight() + 14  # grid pady (8 + 6)
        height += self._paper_row_min
        height += self.status_label.winfo_reqheight()
        if self.scientific_mode:
            height += self._conversion_outer.winfo_reqheight() + 10
            height += self._base_row.winfo_reqheight() + 5
        height += self._keypad_min_height() + _KEYPAD_ROW_PAD
        return height

    def minimum_window_height(self) -> int:
        """Content minimum plus the custom title bar, if this is a plugin."""
        window = self.winfo_toplevel()
        frame = getattr(window, "quicktools_frame", None)
        chrome = 0
        if frame is not None:
            try:
                chrome = frame.bar.winfo_reqheight() + 1
            except tk.TclError:
                chrome = 0
        return chrome + self.minimum_content_height()

    def _update_layout_minsizes(self) -> None:
        self.grid_rowconfigure(1, minsize=self._paper_row_min)
        self.grid_rowconfigure(
            5, minsize=self._keypad_min_height() + _KEYPAD_ROW_PAD
        )

    def _sync_window_minsize(self) -> None:
        """Keep the window from clipping content after switching modes."""
        window = self.winfo_toplevel()
        if getattr(window, "quicktools_frame", None) is None:
            return
        try:
            # Apply pending geometry first: a mode switch right after a resize
            # must not restore the window at the old (stale) width.
            self.update_idletasks()
            width = window.minsize()[0]
            height = self.minimum_window_height()
            window.minsize(width, height)
            if 1 < window.winfo_height() < height:
                window.geometry(f"{window.winfo_width()}x{height}")
        except tk.TclError:
            pass

    def _on_keypad_configure(self, event: tk.Event) -> None:
        if not self._keypad_faces or not self.winfo_ismapped():
            return
        row_height = event.height / self._keypad_row_count()
        self._set_keypad_compact(
            row_height < self._keypad_compact_threshold
        )

    def _set_keypad_compact(self, compact: bool) -> None:
        """Swap fixed-size operator icons for text when keys get short."""
        compact = bool(compact)
        if compact == self._keypad_compact:
            return
        self._keypad_compact = compact
        for button, (label, image) in self._keypad_faces.items():
            if compact:
                button.set_face(image=None, text=label)
            else:
                button.set_face(image=image, text="")

    # --------------------------------------------------------------- layout
    def _on_rows_configure(self, _event=None) -> None:
        self._schedule_paper_layout()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        # Update the embedded frame width immediately so the paper content
        # follows the window edge; the (more expensive) scrollregion and
        # bottom-alignment pass is coalesced for the next idle cycle.
        self.canvas.itemconfigure(self._canvas_window, width=event.width)
        self._schedule_paper_layout()

    def _schedule_paper_layout(self) -> None:
        if self._paper_layout_job is not None or self._destroyed:
            return
        try:
            self._paper_layout_job = self.after_idle(
                self._run_paper_layout
            )
        except tk.TclError:
            self._paper_layout_job = None

    def _run_paper_layout(self) -> None:
        self._paper_layout_job = None
        self._sync_paper_layout()

    def _sync_paper_layout(self, *, measure: bool = False) -> None:
        """Bottom-align short history while keeping long history scrollable.

        ``measure`` is only needed after rows are added/removed: during a
        window resize the row heights are fixed, so forcing Tk to run idle
        layout on every Configure would make the edges visibly lag behind
        the pointer.
        """
        if self._syncing_paper:
            return
        self._syncing_paper = True
        try:
            if measure:
                self.rows_frame.update_idletasks()
            content_height = self.rows_frame.winfo_reqheight()
            viewport = max(1, self.canvas.winfo_height())
            offset = max(0, viewport - content_height)
            total_height = max(viewport, content_height)
            width = max(1, self.canvas.winfo_width())
            layout = (offset, total_height, width)
            previous = getattr(self, "_paper_layout_value", None)
            if layout != previous:
                self._paper_layout_value = layout
                self.canvas.coords(self._canvas_window, 0, offset)
                self.canvas.configure(scrollregion=(0, 0, width, total_height))
                if content_height <= viewport:
                    self.canvas.yview_moveto(0.0)
        finally:
            self._syncing_paper = False

    def bind_wheel(self, widget: tk.Misc) -> None:
        widget.bind("<Button-4>", self._on_wheel, add="+")
        widget.bind("<Button-5>", self._on_wheel, add="+")
        widget.bind("<MouseWheel>", self._on_wheel, add="+")

    def _on_wheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            delta = getattr(event, "delta", 0)
            units = -3 if delta > 0 else 3
        self.canvas.yview_scroll(units, "units")
        return "break"

    def scroll_to_bottom(self) -> None:
        self._sync_paper_layout(measure=True)
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)

    # ---------------------------------------------------------------- rows
    @property
    def current_row(self) -> ScratchRow:
        if self.active_row is not None and self.active_row in self.rows:
            return self.active_row
        if not self.rows:
            self.add_row()
        if self.active_row is None:
            self.active_row = self.rows[-1]
            self.active_row.set_active(True)
        return self.active_row

    def add_row(
        self, *, focus: bool = False, schedule_scroll: bool = True
    ) -> ScratchRow:
        row = ScratchRow(self, len(self.rows) + 1, self._row_height, self.fonts)
        row.grid(row=len(self.rows), column=0, sticky="ew")
        self.rows.append(row)
        self.activate_row(row)
        if focus:
            self.after_idle(row.focus)
        if schedule_scroll:
            self._schedule_scroll_to_bottom()
        return row

    def _schedule_scroll_to_bottom(self) -> None:
        if self._scroll_job is not None:
            try:
                self.after_cancel(self._scroll_job)
            except tk.TclError:
                pass
        # Let Tk finish sizing the new row before moving the viewport.
        self._scroll_job = self.after(15, self._run_scheduled_scroll)

    def _run_scheduled_scroll(self) -> None:
        self._scroll_job = None
        try:
            self.scroll_to_bottom()
        except tk.TclError:
            pass

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        self._destroyed = True
        if self._scroll_job is not None:
            try:
                self.after_cancel(self._scroll_job)
            except tk.TclError:
                pass
            self._scroll_job = None
        if self._paper_layout_job is not None:
            try:
                self.after_cancel(self._paper_layout_job)
            except tk.TclError:
                pass
            self._paper_layout_job = None
        self._cancel_scratchpad_save()
        # Tk destroys children before the parent, so this must only use the
        # plain-data snapshot captured while the widgets were alive.
        self._flush_scratchpad()

    def activate_row(self, row: ScratchRow) -> None:
        if row not in self.rows:
            return
        if self.active_row is row:
            self._refresh_conversion()
            return
        for existing in self.rows:
            existing.set_active(existing is row)
        self.active_row = row
        self._refresh_conversion()

    def focus_active(self) -> None:
        try:
            row = self.current_row
            row.focus()
        except tk.TclError:
            pass

    def evaluate_active(self) -> None:
        self.evaluate_row(self.current_row)

    def evaluate_row(self, row: ScratchRow) -> None:
        text = row.expression
        if not text.strip():
            return
        row.entry_base = self.base
        try:
            value = evaluate_live(text, self.base)
        except ExpressionError as exc:
            row.set_error("错误")
            self.set_status(str(exc), error=True)
            self._refresh_conversion()
            self._request_scratchpad_save()
            return
        except Exception:
            row.set_error("错误")
            self.set_status("计算失败，请检查表达式", error=True)
            self._refresh_conversion()
            self._request_scratchpad_save()
            return

        formatted = format_result(
            value, self.base, self.result_group_size
        )
        row.set_result(value, self.base, formatted)
        self.set_status(self._default_hint(), error=False)
        self.activate_row(row)
        self._refresh_conversion()
        self._request_scratchpad_save()
        if row is self.rows[-1]:
            self.add_row(focus=True)

    def on_row_text_changed(self, row: ScratchRow) -> None:
        # Cache plain data here as well: clear_all() bypasses the trace.
        row.memory_expression = row.expression
        row.entry_base = self.base
        self._update_live_result(row)
        if row is self.active_row:
            self._refresh_conversion()
        self.set_status(self._default_hint(), error=False)
        self._request_scratchpad_save()

    def _update_live_result(self, row: ScratchRow) -> None:
        """Mirror the current input into the result label as it is typed.

        Incomplete-but-completable input (``1+``, ``1+2*``) shows the
        completed value; input that cannot be calculated shows nothing.
        """
        text = row.expression
        if not text.strip():
            row.clear_result()
            return
        try:
            value = evaluate_live(text, self.base)
        except Exception:
            row.clear_result()
            return
        row.set_result(
            value,
            self.base,
            format_result(value, self.base, self.result_group_size),
        )

    # ------------------------------------------------------------- editing
    def insert_text(self, text: str) -> None:
        row = self.current_row
        entry = row.entry
        try:
            if entry.selection_present():
                entry.delete("sel.first", "sel.last")
            entry.insert(tk.INSERT, text)
        except tk.TclError:
            pass
        entry.focus_set()
        self.activate_row(row)

    def backspace(self) -> None:
        row = self.current_row
        entry = row.entry
        try:
            if entry.selection_present():
                entry.delete("sel.first", "sel.last")
            else:
                cursor = entry.index(tk.INSERT)
                if cursor > 0:
                    entry.delete(cursor - 1, cursor)
        except tk.TclError:
            pass
        entry.focus_set()
        self.activate_row(row)

    def clear_active(self) -> None:
        row = self.current_row
        row.clear_all()
        row.focus()
        self.activate_row(row)
        self.set_status("", error=False)
        self._refresh_conversion()

    # ------------------------------------------------------- scientific mode
    def toggle_scientific_mode(self) -> None:
        self.set_scientific_mode(not self.scientific_mode)

    def set_scientific_mode(self, enabled: bool) -> None:
        self._apply_scientific_mode(enabled, persist=True)

    def _apply_scientific_mode(self, enabled: bool, *, persist: bool) -> None:
        enabled = bool(enabled)
        if not enabled and self.base != 10:
            # Leaving scientific mode must not keep a non-decimal input base
            # active behind a hidden selector.
            self.set_base(10)
        self.scientific_mode = enabled
        self.scientific_button.configure(
            text="科学模式：开" if enabled else "科学模式：关"
        )
        self.scientific_button.set_active(enabled)
        if enabled:
            if not self._conversion_outer.winfo_manager():
                self._conversion_outer.grid()
            if not self._base_row.winfo_manager():
                self._base_row.grid()
            if not self._hex_row.winfo_manager():
                self._hex_row.grid()
        else:
            self._conversion_outer.grid_remove()
            self._base_row.grid_remove()
            self._hex_row.grid_remove()
        self._update_layout_minsizes()
        self._update_digit_states()
        self._refresh_conversion()
        self.set_status(self._default_hint(), error=False)
        if persist:
            save_scientific_mode(self.data_dir, enabled)
            self._sync_window_minsize()

    def _default_hint(self) -> str:
        return _STATUS_HINT if self.scientific_mode else _SIMPLE_STATUS_HINT

    def set_base(self, base: int, *, schedule_save: bool = True) -> None:
        if base not in SUPPORTED_BASES:
            return
        if not self.scientific_mode and base != 10:
            return
        self.base = base
        for value, button in self._base_buttons.items():
            active = value == base
            button.set_active(active)
            button.configure(
                font=self.fonts.u(10, "bold" if active else "normal")
            )
        row = self.current_row
        row.entry_base = base
        self._update_digit_states()
        self._update_live_result(row)
        self._refresh_conversion()
        row.focus()
        if schedule_save:
            self._request_scratchpad_save()

    def _update_digit_states(self) -> None:
        valid_digits = {
            2: set("01"),
            8: set("01234567"),
            10: set("0123456789"),
            16: set("0123456789ABCDEF"),
        }[self.base]
        for label, button in self._digit_buttons.items():
            if label == ".":
                button.set_enabled(self.base == 10)
            elif len(label) == 1 and label in "0123456789ABCDEF":
                button.set_enabled(label in valid_digits)
            else:
                button.set_enabled(True)
        self.dot_button.set_enabled(self.base == 10)

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(message)
        self.status_label.configure(fg=DANGER if error else MUTED)

    # ---------------------------------------------------------- conversion
    def _refresh_conversion(self) -> None:
        value: int | float | None = None
        active = self.active_row
        if active is not None:
            text = active.expression.strip()
            if (
                active.result_value is not None
                and active.result_base == self.base
                and active.evaluated_expression == active.expression
            ):
                value = active.result_value
            elif text:
                try:
                    value = evaluate_live(text, self.base)
                except Exception:
                    value = None
            else:
                for candidate in reversed(self.rows):
                    if candidate.result_value is not None:
                        value = candidate.result_value
                        break

        converted = (
            convert_bases(value)
            if value is not None
            else {base: None for base in SUPPORTED_BASES}
        )
        # Highlight the whole active cell (not just the tag) so the current
        # base stands out at a glance.
        for base in SUPPORTED_BASES:
            active = base == self.base
            item = converted.get(base)
            var = self._conversion_vars.get(base)
            if var is not None:
                var.set(item if item is not None else "—")
            cell = self._conversion_cells.get(base)
            if cell is not None:
                cell.configure(bg=ROW_ACTIVE if active else PANEL)
            entry = self._conversion_entries.get(base)
            if entry is not None:
                entry.configure(
                    bg=ROW_ACTIVE if active else PANEL,
                    readonlybackground=ROW_ACTIVE if active else PANEL,
                    font=self.fonts.m(
                        _ACTIVE_VALUE_SIZE if active else 11,
                        "bold" if active else "normal",
                    ),
                )
            tag = self._base_tag_labels.get(base)
            if tag is not None:
                tag.configure(
                    bg=ROW_ACTIVE if active else PANEL,
                    fg=ACCENT if active else MUTED,
                    font=self.fonts.u(
                        _ACTIVE_TAG_SIZE if active else _INACTIVE_TAG_SIZE,
                        "bold" if active else "normal",
                    ),
                )

    # ------------------------------------------------------- scratchpad memory
    def scratchpad_record_count(self) -> int:
        return sum(
            1 for row in self.rows if row.memory_expression.strip()
        )

    def _restore_scratchpad(self, state: ScratchpadState) -> None:
        for entry in state.entries:
            row = self.add_row(schedule_scroll=False)
            row.entry_base = entry.base
            row.restore_expression(entry.expression)
            self._apply_saved_result(row, entry.base)
        # Always leave a fresh editable row at the bottom.
        self.add_row(focus=True)
        if self.scientific_mode and state.last_base in SUPPORTED_BASES:
            self.set_base(state.last_base, schedule_save=False)
        self._scratchpad_state = self._capture_scratchpad_state()
        self._save_dirty = False

    def _apply_saved_result(self, row: ScratchRow, base: int) -> None:
        text = row.expression
        if not text.strip():
            row.clear_result()
            return
        try:
            value = evaluate_live(text, base)
        except Exception:
            row.clear_result()
            return
        row.set_result(
            value,
            base,
            format_result(value, base, self.result_group_size),
        )

    def _capture_scratchpad_state(self) -> ScratchpadState:
        entries = [
            ScratchEntry(row.memory_expression, row.entry_base)
            for row in self.rows
            if row.memory_expression.strip()
        ]
        return ScratchpadState(
            entries=tuple(entries[-self.max_records :]),
            last_base=self.base,
        )

    def _request_scratchpad_save(self, *, immediate: bool = False) -> None:
        if self.data_dir is None or self._destroyed:
            return
        self._scratchpad_state = self._capture_scratchpad_state()
        self._save_dirty = True
        self._cancel_scratchpad_save()
        if immediate:
            self._flush_scratchpad()
        else:
            self._save_job = self.after(
                _SAVE_DEBOUNCE_MS, self._flush_scratchpad
            )

    def _cancel_scratchpad_save(self) -> None:
        if self._save_job is None:
            return
        try:
            self.after_cancel(self._save_job)
        except tk.TclError:
            pass
        self._save_job = None

    def _flush_scratchpad(self) -> None:
        self._cancel_scratchpad_save()
        if self.data_dir is None or not self._save_dirty:
            return
        try:
            save_scratchpad(
                self.data_dir,
                self._scratchpad_state,
                max_records=self.max_records,
            )
        except Exception:
            log.exception("保存草稿纸记忆失败")
            return
        self._save_dirty = False

    def delete_row(self, row: ScratchRow) -> None:
        if row not in self.rows:
            return
        index = self.rows.index(row)
        had_text = bool(row.memory_expression.strip())
        was_active = self.active_row is row
        self.rows.pop(index)
        if was_active:
            self.active_row = None
        try:
            row.destroy()
        except tk.TclError:
            pass
        if not self.rows:
            self.add_row(focus=True)
        else:
            self._regrid_rows()
            if was_active:
                target = self.rows[min(index, len(self.rows) - 1)]
                self.activate_row(target)
                target.focus()
            else:
                self._refresh_conversion()
        self._request_scratchpad_save(immediate=True)
        self.set_status(
            "已删除 1 条记录" if had_text else "已删除空行", error=False
        )

    def clear_scratchpad(self, *, focus: bool = True) -> int:
        count = self.scratchpad_record_count()
        for row in list(self.rows):
            try:
                row.destroy()
            except tk.TclError:
                pass
        self.rows.clear()
        self.active_row = None
        self.add_row(focus=focus)
        self._refresh_conversion()
        self._request_scratchpad_save(immediate=True)
        self.set_status("已清空草稿纸记忆", error=False)
        return count

    def apply_max_records(
        self, value: int, *, focus: bool = True
    ) -> int:
        normalized = save_max_records(self.data_dir, value)
        self.max_records = normalized
        removed = self._trim_rows_to_limit(focus=focus)
        self._request_scratchpad_save(immediate=True)
        if removed:
            self.set_status(
                f"已保留最近 {normalized} 条记录", error=False
            )
        else:
            self.set_status(f"最多保存 {normalized} 条记录", error=False)
        return removed

    def apply_result_group_size(self, value: int) -> int:
        normalized = save_result_group_size(self.data_dir, value)
        self.result_group_size = normalized
        for row in self.rows:
            if row.result_value is None or row.result_base is None:
                continue
            try:
                formatted = format_result(
                    row.result_value, row.result_base, normalized
                )
                row.result_label.configure(
                    text=f"= {formatted}", fg=ACCENT
                )
            except Exception:
                continue
        if normalized:
            self.set_status(
                f"结果每 {normalized} 位插入逗号", error=False
            )
        else:
            self.set_status("结果已关闭分隔符", error=False)
        return normalized

    def _trim_rows_to_limit(self, *, focus: bool = True) -> int:
        records = [
            row for row in self.rows if row.memory_expression.strip()
        ]
        excess = len(records) - self.max_records
        if excess <= 0:
            return 0
        active = self.active_row
        active_index = self.rows.index(active) if active in self.rows else 0
        for row in records[:excess]:
            if row not in self.rows:
                continue
            self.rows.remove(row)
            try:
                row.destroy()
            except tk.TclError:
                pass
        if not self.rows:
            self.active_row = None
            self.add_row()
        else:
            self._regrid_rows()
            if active is None or active not in self.rows:
                target_index = max(
                    0, min(active_index - excess, len(self.rows) - 1)
                )
                target = self.rows[target_index]
                self.active_row = None
                self.activate_row(target)
                if focus:
                    target.focus()
        self._refresh_conversion()
        return excess

    def _regrid_rows(self) -> None:
        for index, row in enumerate(self.rows):
            row.grid(row=index, column=0, sticky="ew")
            row.row_index = index + 1
        self._schedule_paper_layout()

    # ------------------------------------------------------------ settings UI
    def open_settings(self) -> None:
        """Open the shared plugin settings dialog through the plugin hook."""
        callback = self._on_open_settings
        if callback is None:
            return
        self._cancel_scratchpad_save()
        self._flush_scratchpad()
        callback()
