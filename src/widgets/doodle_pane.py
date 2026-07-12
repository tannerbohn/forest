from rich.style import Style
from rich.text import Text
from textual.color import Color
from textual.widgets import Static

DOT_GLYPH = "╱"  # "￭"  # "●"


class DoodlePane(Static):
    DEFAULT_CSS = """
    DoodlePane {
        height: 100%;
        background: $background;
        background-tint: $panel 10%;
        visibility: hidden;
        layer: overlay;
        offset: 0 1;
        hatch: right $panel;
    }
    """

    ALLOW_SELECT = False

    CANVAS_HEIGHT = 60  # terminal rows; row 0 = color indicator, rows 1.. drawable
    COLOR_KEYS = ("foreground", "HL1", None)  # None = eraser
    OPACITY = 0.5
    ANCESTOR_OPACITY = 0.2
    ERASE_RADIUS_X = 2  # cells erased left/right from the cursor
    ERASE_RADIUS_Y = 1  # cells erased up/down from the cursor

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        # canvas[doodle_id] = {"cells": {(cell_dx_from_right, cell_y): color_idx}}
        self._canvases: dict[int, dict] = {}
        self._current_key: int | None = None
        self._current_node = None
        self._width: int = 30
        self._painting: bool = False
        self._last_cell: tuple[int, int] | None = None
        self._stroke_cells: set[tuple[int, int]] = set()
        self._color_idx: int = 0
        self._ancestor_cells: dict[tuple[int, int], int] = {}
        self.pane_visible: bool = False  # revealed together with the info panel
        self.can_focus = True
        self._dirty: bool = False
        # Snapshot of the current canvas cells at mouse-down, to detect no-op strokes.
        self._stroke_snapshot: dict[tuple[int, int], int] | None = None
        self._stroke_allocated_id: bool = False
        self._swallow_next_mousedown: bool = False

    def on_mount(self):
        # Coalesce paint refreshes to one per frame instead of one per mouse event.
        self.set_interval(1 / 10, self._flush_if_dirty)

    def _flush_if_dirty(self):
        if self._dirty:
            self._dirty = False
            self._refresh_render()

    # Layout / lifecycle --------------------------------------------------

    def apply_layout(self, side: str, width: int):
        self.styles.dock = side
        self.styles.width = width
        self._side = side
        self._apply_border()
        self._width = max(width - 1, 0)
        self._refresh_render()

    def _apply_border(self, focused: bool | None = None):
        if focused is None:
            focused = self.has_focus
        tv = self.app.theme_variables
        panel = Color.parse(tv.get("panel", "#000000"))
        active_color = Color.parse(tv.get("HL1", "#ffffff")) if focused else panel
        border = ("vkey", active_color)
        no_border = ("none", panel)
        if getattr(self, "_side", "right") == "left":
            self.styles.border_right = border
            self.styles.border_left = no_border
        else:
            self.styles.border_left = border
            self.styles.border_right = no_border

    def set_visible(self, visible: bool):
        # The pane keeps its real width at all times (its margin is permanently
        # reserved); `visibility` is the open/closed switch, mirroring InfoSidebar.
        # `hidden` paints nothing, so no strip lingers when closed.
        self.pane_visible = visible
        self.styles.visibility = "visible" if visible else "hidden"
        if visible:
            self._apply_border()
            self._refresh_render()

    def set_context(self, node):
        self._current_node = node
        key = node.doodle_id if node is not None else None
        self._current_key = key
        self._painting = False
        self._last_cell = None
        self._stroke_cells = set()
        self._rebuild_ancestor_composite(node)
        self._refresh_render()

    def _rebuild_ancestor_composite(self, node):
        self._ancestor_cells = {}
        if node is None or node.parent is None:
            return
        chain = []
        cur = node.parent
        while cur is not None:
            chain.append(cur)
            cur = cur.parent
        chain.reverse()  # root-first, so closer ancestors overwrite
        for anc in chain:
            if anc.doodle_id is None:
                continue
            canvas = self._canvases.get(anc.doodle_id)
            if not canvas:
                continue
            for key, color_idx in canvas["cells"].items():
                self._ancestor_cells[key] = color_idx

    def clear_current(self):
        node = self._current_node
        if node is None or node.doodle_id is None:
            return
        self._canvases.pop(node.doodle_id, None)
        node.doodle_id = None
        self._current_key = None
        self._painting = False
        self._last_cell = None
        self._stroke_cells = set()
        try:
            self.app.note_tree.has_unsaved_operations = True
            self.app.status_bar.needs_saving = True
        except Exception:
            pass
        self._refresh_render()

    def load_from_sidecar(self, canvases_by_id: dict[int, dict]):
        self._canvases = {}
        for cid, payload in canvases_by_id.items():
            cell_list = payload.get("cells", [])
            self._canvases[cid] = {
                "cells": {(int(cdx), int(cy)): int(ci) for cdx, cy, ci in cell_list},
            }
        self._rebuild_ancestor_composite(self._current_node)
        self._refresh_render()

    def to_sidecar_payload(self) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for cid, canvas in self._canvases.items():
            cells = canvas.get("cells") or {}
            if not cells:
                continue
            out[cid] = {
                "cells": [(cdx, cy, ci) for (cdx, cy), ci in cells.items()],
            }
        return out

    def cycle_color(self):
        self._color_idx = (self._color_idx + 1) % len(self.COLOR_KEYS)
        self._refresh_render()

    # Coord helpers -------------------------------------------------------

    def _current_canvas(self) -> dict:
        if self._current_key is None:
            return {"cells": {}}
        canvas = self._canvases.get(self._current_key)
        if canvas is None:
            canvas = {"cells": {}}
            self._canvases[self._current_key] = canvas
        return canvas

    def _cell_to_storage(self, cell_x: int, cell_y: int) -> tuple[int, int]:
        return (self._width - 1 - cell_x, cell_y)

    def _cell_from_storage(self, cell_dx: int, cell_y: int) -> tuple[int, int]:
        return (self._width - 1 - cell_dx, cell_y)

    def _event_to_cell(self, event_x: int, event_y: int) -> tuple[int, int] | None:
        if event_y < 1:
            return None
        cell_x = event_x
        cell_y = event_y - 1
        if cell_x < 0 or cell_x >= self._width:
            return None
        if cell_y < 0 or cell_y >= self.CANVAS_HEIGHT - 1:
            return None
        return (cell_x, cell_y)

    # Paint ---------------------------------------------------------------

    def _ensure_doodle_id(self) -> bool:
        if self._current_key is not None:
            return True
        node = self._current_node
        if node is None:
            return False
        try:
            new_id = self.app._allocate_doodle_id()
        except AttributeError:
            return False
        node.doodle_id = new_id
        self._current_key = new_id
        self._stroke_allocated_id = True
        return True

    def _is_eraser(self) -> bool:
        return self.COLOR_KEYS[self._color_idx] is None

    def _erase_cell(self, cell_x: int, cell_y: int):
        if cell_x < 0 or cell_x >= self._width:
            return
        if cell_y < 0 or cell_y >= self.CANVAS_HEIGHT - 1:
            return
        if self._current_key is None:
            return
        canvas = self._canvases.get(self._current_key)
        if not canvas:
            return
        canvas["cells"].pop(self._cell_to_storage(cell_x, cell_y), None)

    def _paint_dot(self, cell_x: int, cell_y: int):
        if cell_x < 0 or cell_x >= self._width:
            return
        if cell_y < 0 or cell_y >= self.CANVAS_HEIGHT - 1:
            return
        key = self._cell_to_storage(cell_x, cell_y)
        if key in self._stroke_cells:
            return
        self._stroke_cells.add(key)

        if self._is_eraser():
            for dy in range(-self.ERASE_RADIUS_Y, self.ERASE_RADIUS_Y + 1):
                for dx in range(-self.ERASE_RADIUS_X, self.ERASE_RADIUS_X + 1):
                    self._erase_cell(cell_x + dx, cell_y + dy)
            return

        if not self._ensure_doodle_id():
            return
        canvas = self._current_canvas()
        canvas["cells"][key] = self._color_idx

    def _paint_line(self, x0: int, y0: int, x1: int, y1: int):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            self._paint_dot(x, y)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    # Rendering -----------------------------------------------------------

    def _palette_color(self, color_idx: int) -> Color | None:
        name = self.COLOR_KEYS[color_idx]
        if name is None:
            return None
        tv = self.app.theme_variables
        return Color.parse(tv.get(name, "#ffffff"))

    def _bg_color(self) -> Color:
        return Color.parse(self.app.theme_variables.get("panel", "#000000"))

    def _low_opacity_hex(self, color: Color, opacity: float | None = None) -> str:
        return (
            self._bg_color()
            .blend(color, self.OPACITY if opacity is None else opacity)
            .hex
        )

    def _refresh_render(self):
        canvas = self._current_canvas()
        own_cells: dict[tuple[int, int], int] = canvas["cells"]
        width = self._width
        draw_rows = self.CANVAS_HEIGHT - 1

        tv = self.app.theme_variables
        fg_hex = self._low_opacity_hex(Color.parse(tv.get("foreground", "#ffffff")))
        # Cache palette hex per color_idx so we don't re-parse/blend per cell.
        palette_hex: dict[int, str | None] = {}
        ancestor_hex: dict[int, str | None] = {}
        for idx, name in enumerate(self.COLOR_KEYS):
            if name is None:
                palette_hex[idx] = None
                ancestor_hex[idx] = None
            else:
                base = Color.parse(tv.get(name, "#ffffff"))
                palette_hex[idx] = self._low_opacity_hex(base)
                ancestor_hex[idx] = self._low_opacity_hex(base, self.ANCESTOR_OPACITY)
        fg_style = Style(color=fg_hex)
        dot_styles: dict[int, Style] = {
            idx: Style(color=hex_)
            for idx, hex_ in palette_hex.items()
            if hex_ is not None
        }
        ancestor_styles: dict[int, Style] = {
            idx: Style(color=hex_)
            for idx, hex_ in ancestor_hex.items()
            if hex_ is not None
        }

        text = Text()
        text.append("[M]ode: ", style=fg_style)
        cur_hex = palette_hex.get(self._color_idx)
        if cur_hex is None:
            text.append("erase", style=fg_style)
        else:
            text.append(DOT_GLYPH, style=dot_styles[self._color_idx])
        text.append("\n")

        # Bucket painted cells by row so empty rows/segments emit as bulk whitespace.
        rows: list[dict[int, tuple[int, bool]]] = [{} for _ in range(draw_rows)]
        w_minus_1 = width - 1
        for (cdx, cy), ci in own_cells.items():
            if 0 <= cy < draw_rows:
                cx = w_minus_1 - cdx
                if 0 <= cx < width:
                    rows[cy][cx] = (ci, False)
        for (cdx, cy), ci in self._ancestor_cells.items():
            if 0 <= cy < draw_rows:
                cx = w_minus_1 - cdx
                if 0 <= cx < width and cx not in rows[cy]:
                    rows[cy][cx] = (ci, True)

        for draw_y in range(draw_rows):
            painted = rows[draw_y]
            if painted:
                prev_x = 0
                for cx in sorted(painted):
                    ci, is_ancestor = painted[cx]
                    style = (ancestor_styles if is_ancestor else dot_styles).get(ci)
                    if style is None:
                        continue
                    if cx > prev_x:
                        text.append(" " * (cx - prev_x))
                    text.append(DOT_GLYPH, style=style)
                    prev_x = cx + 1
                if prev_x < width:
                    text.append(" " * (width - prev_x))
            else:
                text.append(" " * width)
            if draw_y < draw_rows - 1:
                text.append("\n")
        self.update(text)

    # Mouse handlers ------------------------------------------------------

    def _begin_stroke(self):
        self._painting = True
        self._stroke_cells = set()
        self._stroke_allocated_id = False
        if self._current_key is not None:
            existing = self._canvases.get(self._current_key)
            self._stroke_snapshot = dict(existing["cells"]) if existing else {}
        else:
            self._stroke_snapshot = None

    def _end_stroke(self):
        if not self._painting:
            return
        self._painting = False
        self._last_cell = None
        self._stroke_cells = set()

        node = self._current_node
        key = self._current_key
        canvas = self._canvases.get(key) if key is not None else None
        cur_cells = canvas["cells"] if canvas is not None else {}

        # If we allocated a new doodle_id during this stroke but ended with no
        # cells (e.g. drew then erased), roll it back so we don't pollute state.
        if self._stroke_allocated_id and not cur_cells:
            if key is not None:
                self._canvases.pop(key, None)
            if node is not None:
                node.doodle_id = None
            self._current_key = None
            changed = False
        else:
            snapshot = self._stroke_snapshot
            if snapshot is None:
                changed = bool(cur_cells)
            else:
                changed = snapshot != cur_cells
            # If a pre-existing canvas was fully erased, drop it so the node
            # no longer references an empty canvas.
            if changed and not cur_cells and key is not None and node is not None:
                self._canvases.pop(key, None)
                node.doodle_id = None
                self._current_key = None

        self._stroke_snapshot = None
        self._stroke_allocated_id = False

        if changed:
            self.app.note_tree.has_unsaved_operations = True
            self.app.status_bar.needs_saving = True
        # Always flush one render so the displayed canvas matches final state.
        # self._dirty = True

        try:
            self.release_mouse()
        except Exception:
            pass

    def on_mouse_down(self, event):
        if self._swallow_next_mousedown:
            self._swallow_next_mousedown = False
            return
        if not self.has_focus:
            self.focus()
            return
        self.capture_mouse()
        self._begin_stroke()
        cell = self._event_to_cell(event.x, event.y)
        if cell is not None:
            self._paint_dot(*cell)
        self._last_cell = cell
        self._dirty = True

    def on_mouse_move(self, event):
        if not self._painting:
            return
        cell = self._event_to_cell(event.x, event.y)
        if cell is None:
            self._last_cell = None
            return
        if self._last_cell is None:
            self._paint_dot(*cell)
        else:
            self._paint_line(self._last_cell[0], self._last_cell[1], cell[0], cell[1])
        self._last_cell = cell
        self._dirty = True

    def on_mouse_up(self, event):
        self._end_stroke()

    def on_focus(self, event):
        self._swallow_next_mousedown = True
        if self.pane_visible:
            self._apply_border(focused=True)

    def on_blur(self, event):
        self._end_stroke()
        if self.pane_visible:
            self._apply_border(focused=False)

    def on_key(self, event):
        if event.key == "M":
            event.stop()
            self.cycle_color()
        elif event.key == "s":
            event.stop()
            try:
                self.app.note_tree_widget.action_save()
            except Exception:
                pass
        elif event.key == "escape":
            event.stop()
            try:
                self.app.note_tree_widget.focus()
            except Exception:
                pass
