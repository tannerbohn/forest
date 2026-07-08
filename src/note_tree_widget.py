import math
import random
import re
import textwrap
from dataclasses import dataclass

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.color import Gradient
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

from clipboard import copy_to_clipboard
from note_tree import NoteTree
from subtrees import SUBTREES
from themes import TEXT_COLOR_REGEX_LIST
from utils import (add_subtree, extract_path_references, node_subtree_as_text,
                   play_sound_effect)

logging = None

# Horizontal layout of a rendered row:
#   [age column: 4 cells] [indent: GUIDE_DEPTH * (depth+1)] [arrow+space] [text]
# The age column carries the age-gradient bar plus the bookmark/copy glyph.
GUIDE_DEPTH = 4
# Cells reserved on the left of the text: age column (4) + arrow + space (2).
_TEXT_LEFT_PAD = 4 + 2


def _truncate_link_segment(text: str, max_chars: int = 30, max_words: int = 5) -> str:
    text = text.strip()
    if not text:
        return text
    words = text.split()
    if len(words) > max_words:
        words = words[:max_words]
    truncated = " ".join(words)
    if len(truncated) > max_chars:
        cut = truncated[:max_chars].rsplit(" ", 1)[0] or truncated[:max_chars]
        truncated = cut
    return truncated


@dataclass
class VisualRow:
    """One screen row. Wrapping is resolved here (one row per wrap segment),
    so there is no paired first/last-widget machinery."""

    node: object  # the logical Node this row belongs to
    depth: int  # indentation depth relative to the context node (0 = direct child)
    seg_index: int  # 0 = first (arrow-bearing) segment; >0 = wrap continuation
    seg_count: int  # total wrap segments for this node
    text: str  # the wrapped text slice for this row
    is_spacer: bool = False  # blank spacer row inserted between top-level children


class NoteTreeWidget(ScrollView):

    DEFAULT_CSS = """
    NoteTreeWidget {
        scrollbar-gutter: stable;
    }
    """

    can_focus = True

    BINDINGS = [
        Binding("up", "cursor_up()", "Up", show=False),
        Binding("down", "cursor_down()", "Down", show=False),
        Binding("s", "save()", "Save", show=True),
        Binding("left", "zoom_out()", "Zoom out", show=True),
        Binding("right", "zoom_in()", "Zoom in", show=True),
        Binding("space", "toggle_node()", "Toggle", show=False),
        Binding("h", "cycle_highlight()", "Cycle highlight", show=True),
        Binding("x", "toggle_done()", "Toggle #DONE", show=True),
        Binding("X", "toggle_hide_done()", "Toggle hiding #DONE", show=True),
        Binding("tab", "indent()", "Indent", show=False),
        Binding("shift+tab", "deindent()", "Deindent", show=False),
        Binding("delete", "delete_node()", "Delete", show=False),
        Binding("u", "move_node('up')", "Move up", show=False),
        Binding("d", "move_node('down')", "Move down", show=False),
        Binding("z", "undo()", "Undo", show=False),
        Binding("Z", "redo()", "Redo", show=False),
        Binding("c", "toggle_copy()", "Copy", show=True),
        Binding("C", "cycle_copy()", "Cycle copy target", show=False),
        Binding("v", "paste_node()", "Paste", show=False),
        Binding("V", "jump_to_copy()", "Move to next copied note", show=False),
        Binding("l", "paste_link()", "Paste link to copied note", show=False),
        Binding("y", "yank_node()", "Yank to clipboard", show=False),
        Binding("Y", "yank_subtree()", "Yank subtree to clipboard", show=False),
        Binding("r", "renew_expiry()", "Renew expiry", show=False),
    ]

    def __init__(self, note_tree: NoteTree, id: str):
        super().__init__(id=id)
        self.note_tree = note_tree

        # Flat render model (source of truth), rebuilt by _build_rows().
        self.rows: list[VisualRow] = []
        self.node_first_row: dict[int, int] = {}  # id(node) -> first row index
        self.cursor_row = 0

        self.age_gradient = Gradient((0, "red"), (1, "black"))
        self._line_cache: dict = {}
        # id(node) -> (text, available_width, wrapped_parts); see _build_rows.
        self._wrap_cache: dict[int, tuple[str, int, list[str]]] = {}

        # Defer the first build to on_resize: self.size.width isn't known yet,
        # which would wrap against the full app width (ignoring our margin).
        self._initial_render_done = False

        global logging
        logging = self.app.logging

    # ------------------------------------------------------------- cursor api

    @property
    def cursor_node(self):
        """The logical Node under the cursor (or None)."""
        if 0 <= self.cursor_row < len(self.rows):
            return self.rows[self.cursor_row].node
        return None

    def _is_navigable(self, index: int) -> bool:
        if not (0 <= index < len(self.rows)):
            return False
        row = self.rows[index]
        return not row.is_spacer and row.seg_index == 0

    def _set_cursor(self, index: int) -> None:
        if not self._is_navigable(index):
            return
        old = self.cursor_row
        self.cursor_row = index
        # is_cursor is part of the line cache key: invalidate the two rows.
        self._line_cache = {
            k: v for k, v in self._line_cache.items() if k[0] not in (old, index)
        }
        self._update_progress()
        self._scroll_cursor_into_margin()
        self.refresh()

    def _ensure_cursor_valid(self) -> None:
        """After a rebuild, snap cursor to the nearest navigable row."""
        n = len(self.rows)
        if n == 0:
            self.cursor_row = 0
            return
        start = self.cursor_row if 0 <= self.cursor_row < n else 0
        for off in range(n):
            j = (start + off) % n
            if self._is_navigable(j):
                self.cursor_row = j
                return
        self.cursor_row = 0

    def move_cursor_to_line(self, line: int) -> None:
        """Move the cursor to the first navigable row at or after `line`."""
        n = len(self.rows)
        if n == 0:
            self.cursor_row = 0
            return
        for i in range(max(0, line), n):
            if self._is_navigable(i):
                self._set_cursor(i)
                return
        for i in range(n):
            if self._is_navigable(i):
                self._set_cursor(i)
                return

    def _fix_cursor_position(self, target_node) -> None:
        if not target_node:
            return
        idx = self.node_first_row.get(id(target_node))
        if idx is not None:
            self._set_cursor(idx)

    # ------------------------------------------------------------- build rows

    def _build_rows(self) -> None:
        self.rows = []
        self.node_first_row = {}
        ctx = self.note_tree.context_node
        width = self.size.width or self.app.size.width

        # Re-wrapping every visible node with textwrap dominates a full rebuild
        # (~1.6s for 9k nodes). Only the changed node's wrap actually differs,
        # so memoize parts per node keyed by (text, available width). Rebuilding
        # a fresh dict each pass prunes it to exactly the current visible set, so
        # it stays bounded regardless of tree size or edit churn.
        old_wrap_cache = self._wrap_cache
        new_wrap_cache: dict[int, tuple[str, int, list[str]]] = {}

        seen_top_level = False
        for node in self.note_tree.visible_node_list[1:]:  # [0] is the context node
            depth = max(0, node.depth - ctx.depth - 1)

            if depth == 0:
                if seen_top_level:
                    # blank spacer between top-level children (matches old layout)
                    self.rows.append(VisualRow(node, 0, 0, 1, "", is_spacer=True))
                seen_top_level = True

            available = max(1, width - (GUIDE_DEPTH * depth + _TEXT_LEFT_PAD))
            text = node.get_text()
            cached = old_wrap_cache.get(id(node))
            if cached is not None and cached[0] == text and cached[1] == available:
                parts = cached[2]
            else:
                parts = textwrap.wrap(text, width=available) or [""]
            new_wrap_cache[id(node)] = (text, available, parts)

            seg_count = len(parts)
            self.node_first_row[id(node)] = len(self.rows)
            for i, part in enumerate(parts):
                self.rows.append(VisualRow(node, depth, i, seg_count, part))

        self._wrap_cache = new_wrap_cache

    def render(self) -> None:
        """Rebuild the flat render model from the note tree.

        (Overrides ScrollView.render, which is unused because we paint via the
        Line API in render_line.)"""
        tvars = self.app.get_theme_variable_defaults()
        if "age-color-0" in tvars:
            self.age_gradient = Gradient(
                (0, tvars["age-color-0"]),
                (0.5, tvars["age-color-1"]),
                (1, tvars["age-color-2"]),
            )

        self.note_tree.update_visible_node_list()
        self._build_rows()
        self.virtual_size = Size(self.size.width, len(self.rows))
        self._line_cache.clear()
        self._ensure_cursor_valid()

        self.app.status_bar.context_node = self.note_tree.context_node
        doodle = getattr(self.app, "doodle_pane", None)
        if doodle is not None:
            doodle.set_context(self.note_tree.context_node)
        self.app.status_bar.needs_saving = self.note_tree.has_unsaved_operations

        self.refresh()

    def _restyle_node(self, node) -> bool:
        """Repaint after a styling-only change (highlight / done / copy /
        bookmark) without rebuilding the whole row list.

        Such changes don't restructure the tree, so the flat row list is
        unchanged except for `node`'s own text (a hashtag toggle can shift its
        wrap). We re-wrap just this node in place; if its line count changed we
        return False so the caller falls back to a full render(). The line cache
        is cleared wholesale (it only holds ~viewport entries) so dependent
        rows repaint too — done-dimming of descendants, or a bookmark glyph
        displaced by LRU replacement on another visible node."""
        idx = self.node_first_row.get(id(node))
        if idx is None or idx >= len(self.rows) or self.rows[idx].node is not node:
            return False
        row0 = self.rows[idx]
        width = self.size.width or self.app.size.width
        available = max(1, width - (GUIDE_DEPTH * row0.depth + _TEXT_LEFT_PAD))
        text = node.get_text()
        parts = textwrap.wrap(text, width=available) or [""]
        if len(parts) != row0.seg_count:
            return False
        for i, part in enumerate(parts):
            self.rows[idx + i] = VisualRow(node, row0.depth, i, len(parts), part)
        self._wrap_cache[id(node)] = (text, available, parts)
        self._line_cache.clear()
        self.app.status_bar.needs_saving = self.note_tree.has_unsaved_operations
        self.refresh()
        return True

    def update_location(self, context_node, line_node):
        self.note_tree.update_context(context_node)
        self.render()
        self._fix_cursor_position(line_node)

    # ------------------------------------------------------------- rendering

    def _label_markup(self, row: VisualRow, is_cursor: bool) -> str:
        """Build the console-markup string for a row's label (arrow + text)."""
        if row.is_spacer:
            return ""
        node = row.node
        tvars = self.app.get_theme_variable_defaults()
        is_first = row.seg_index == 0
        is_last = row.seg_index == row.seg_count - 1

        arrow_str = ""
        if is_first:
            if node.is_collapsed:
                arrow_char = "⟫"
            elif is_cursor:
                arrow_char = "❯"
            else:
                arrow_char = "›"
            tag = tvars.get("cursor-arrow" if is_cursor else "default-arrow") or "white"
            if node.is_collapsed:
                arrow_str = f"[bold {tag}]{arrow_char}[/bold {tag}]"
            else:
                arrow_str = f"[{tag}]{arrow_char}[/{tag}]"
            body = " " + row.text  # aligns text one cell past the arrow
        else:
            body = "  " + row.text  # continuation lines align under the text

        # An expired note reads as expired even if also done/highlighted, so it
        # takes precedence over both.
        is_expired_owner = node.expiry_datetime is not None and node.is_expired()
        if is_expired_owner:
            red = tvars.get("HL3") or "red"
            body = f"[dim {red}]{body}[/dim {red}]"
        elif node.is_done():
            tag = tvars.get("dim-text") or "dim"
            body = f"[{tag}]{body}[/{tag}]"
        else:
            for pattern, formatting in TEXT_COLOR_REGEX_LIST:
                try:
                    body = re.sub(pattern, f"[{formatting}]\\g<0>[/{formatting}]", body)
                except re.error as e:
                    logging.error(f"Invalid regex pattern '{pattern}': {e}")
            if node.is_highlighted():
                hashtag = node.get_highlight_hashtag()
                hl_fallback = {"HL1": "green", "HL2": "yellow", "HL3": "red"}
                hl = tvars.get(hashtag) or hl_fallback.get(hashtag)
                if hl:
                    body = f"[{hl}]{body}[/{hl}]"

        if node.depth == self.note_tree.context_node.depth + 1:
            body = f"[bold]{body}[/bold]"

        if node.is_collapsed and node.children and is_last:
            descendants = (
                len(
                    node.get_node_list(
                        only_visible=False,
                        hide_done=False,
                        hide_archive=self.note_tree.hide_archive,
                    )
                )
                - 1
            )
            if descendants > 0:
                dot_count = min(4, max(1, int(2 * math.log10(descendants + 1))))
                if node.is_done():
                    body += f" [dim]{'•' * dot_count}[/dim]"
                else:
                    body += f" {'•' * dot_count}"

        # Inline time-left / expired readout on the owner note's last segment.
        if node.expiry_datetime is not None and is_last:
            status = node.expiry_status()
            if status is not None:
                expired, label = status
                loop = " ↺" if node.expiry_recurring else ""
                if expired:
                    red = tvars.get("HL3") or "red"
                    body += f" [dim {red}]⌛{label} ago{loop}[/dim {red}]"
                else:
                    amber = tvars.get("HL2") or "yellow"
                    body += f" [{amber}]⏳{label}{loop}[/{amber}]"

        return arrow_str + body

    def _gutter_segments(self, row: VisualRow) -> list[Segment]:
        # [age bar ▎] + [2-cell glyph slot]. The glyph is bookmark > copied >
        # expiring-T > blank; the T carries its own expiry color while the rest
        # of the gutter stays age-colored.
        node = row.node
        tvars = self.app.get_theme_variable_defaults()
        age_days = node.get_days_old()
        age_color = self.age_gradient.get_color(min(1, age_days / 365)).hex
        age_bg = tvars.get("age-column-bg", "#1f170d")
        age_style = Style(color=age_color, bgcolor=age_bg)
        bar = Segment("▎", age_style)

        glyph, glyph_style = "   ", age_style
        if row.text.strip():
            if self.note_tree.determine_if_bookmarked(node):
                glyph = "💠 "
            elif node in self.note_tree.copied_nodes:
                glyph = "🔹 "
            elif node.expiry_datetime is not None:
                glyph = "T  "
                if node.is_expired():
                    color = tvars.get("HL3") or "red"
                    glyph_style = Style(color=color, bgcolor=age_bg, bold=True)
                else:
                    color = tvars.get("HL2") or "yellow"
                    glyph_style = Style(color=color, bgcolor=age_bg)
        return [bar, Segment(glyph, glyph_style)]

    def _build_strip(self, index: int, width: int) -> Strip:
        row = self.rows[index]
        is_cursor = index == self.cursor_row

        line_text = Text(no_wrap=True, end="")
        line_text.append(" " * (GUIDE_DEPTH * (row.depth + 0)))

        try:
            label = Text.from_markup(self._label_markup(row, is_cursor))
        except Exception as e:
            logging.error(f"Text.from_markup failed: {e}")
            label = Text("ERROR")

        line_text.append(label)

        # Base style carries the theme background so blank cells (indent, right
        # pad) match the surface; the age column and colored text keep their own
        # colors because apply_style layers the base *underneath* segment styles.
        base = self.rich_style
        segments = self._gutter_segments(row) + list(line_text.render(self.app.console))
        strip = Strip(segments).apply_style(base)
        return strip.adjust_cell_length(max(self.virtual_size.width, width), base)

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        scroll_x, scroll_y = self.scroll_offset
        index = y + scroll_y

        if index < 0 or index >= len(self.rows):
            return Strip.blank(width, self.rich_style)

        cache_key = (index, width, index == self.cursor_row)
        if cache_key in self._line_cache:
            strip = self._line_cache[cache_key]
        else:
            strip = self._build_strip(index, width)
            self._line_cache[cache_key] = strip

        return strip.crop(scroll_x, scroll_x + width)

    # --------------------------------------------------------------- actions

    def action_cycle_highlight(self):
        node = self.cursor_node
        if not node:
            return
        # Only node.text changes, so snapshot node (not its parent subtree).
        self.note_tree.push_undo(node)
        node.cycle_highlight()
        if not self._restyle_node(node):
            self.render()
            self._fix_cursor_position(node)

    def action_toggle_done(self):
        node = self.cursor_node
        if not node:
            return
        # Only node.text changes, so snapshot node (not its parent subtree).
        self.note_tree.push_undo(node)
        node.toggle_done()
        self.note_tree.has_unsaved_operations = True
        if not self._restyle_node(node):
            self.render()
            self._fix_cursor_position(node)

    def action_renew_expiry(self):
        node = self.cursor_node
        if not node or not node.expiry_duration:
            if node and node.expiry_datetime is not None:
                self.app.notify("This timer has no stored duration to renew")
            return
        # Only node.text changes, so snapshot node (not its parent subtree).
        self.note_tree.push_undo(node)
        node.reset_expiry()
        self.note_tree.has_unsaved_operations = True
        self.app.status_bar.show_renew_hint = False
        if not self._restyle_node(node):
            self.render()
            self._fix_cursor_position(node)
        if self.app.info_sidebar.is_showing_bookmarks():
            self.app.info_sidebar.update_data()

    def action_toggle_hide_done(self):
        node = self.cursor_node
        self.note_tree.hide_done = not self.note_tree.hide_done
        self.app.status_bar.hide_done = self.note_tree.hide_done
        self.render()
        if self.note_tree.hide_done and node and node.is_done():
            self.move_cursor_to_line(0)
        else:
            self._fix_cursor_position(node)

    def action_indent(self):
        node = self.cursor_node
        if not node:
            return
        self.note_tree.push_undo(node.parent)
        self.note_tree.indent(node)
        self.render()
        self._fix_cursor_position(node)

    def action_deindent(self):
        node = self.cursor_node
        if not node:
            return
        # Deindent moves node from parent to grandparent, so snapshot grandparent
        undo_target = (
            node.parent.parent if node.parent and node.parent.parent else node.parent
        )
        self.note_tree.push_undo(undo_target)
        self.note_tree.deindent(node)
        self.render()
        self._fix_cursor_position(node)

    def action_delete_node(self):
        node = self.cursor_node
        if not node:
            return
        if node in self.note_tree.copied_nodes:
            self.note_tree.copied_nodes.remove(node)
            self.note_tree.remove_bookmark_for(node)
        self.note_tree.push_undo(node.parent)
        self.note_tree.delete_focus_node(node)
        self.render()
        # Deleting may remove a copied/expiring note, so refresh the panel.
        if self.app.info_sidebar.is_showing_bookmarks():
            self.app.info_sidebar.update_data()

    def action_toggle_node(self):
        node = self.cursor_node
        if not node:
            return
        self.note_tree.toggle_collapse(node)
        self.render()
        self._fix_cursor_position(node)

    def action_add_note(self):
        focus_node = self.cursor_node or self.note_tree.context_node
        self.note_tree.push_undo(focus_node.parent or focus_node)
        _node = self.note_tree.contextual_add_new_note(focus_node)
        self.render()
        if _node:
            self._fix_cursor_position(_node)
            self.app.action_edit_note()

    def action_move_node(self, direction: str):
        node = self.cursor_node
        if not node:
            return
        self.note_tree.push_undo(node.parent)
        self.note_tree.move_line(node, direction=direction)
        self.render()
        self._fix_cursor_position(node)

    def action_toggle_copy(self):
        node = self.cursor_node
        if not node or not node.parent:
            return
        self.app.copied_toggle(node)
        if not self._restyle_node(node):
            self.render()
            self._fix_cursor_position(node)

    def action_jump_to_copy(self):
        self.app.copied_jump_to_next()

    def action_yank_node(self):
        node = self.cursor_node
        if not node:
            return
        if copy_to_clipboard(node.text):
            self.app.notify("Yanked note to clipboard")
        else:
            self.app.notify("Failed to copy to clipboard")

    def action_yank_subtree(self):
        node = self.cursor_node
        if not node:
            return
        text = node_subtree_as_text(node)
        if copy_to_clipboard(text):
            n = text.count("\n") + 1
            self.app.notify(
                f"Yanked subtree ({n} line{'s' if n != 1 else ''}) to clipboard"
            )
        else:
            self.app.notify("Failed to copy to clipboard")

    def action_cycle_copy(self):
        self.app.copied_cycle_target()

    def action_paste_node(self):
        node = self.cursor_node
        if not self.note_tree.copied_nodes or not node:
            return
        source = self.note_tree.copied_nodes[-1]
        destination = node
        if destination == source:
            return
        as_sibling = (
            destination.parent is not None
            and destination is not self.note_tree.context_node
            and (not destination.children or destination.is_collapsed)
        )
        self.note_tree.push_undo(source.parent)
        self.note_tree.push_undo(destination)
        if as_sibling:
            self.note_tree.push_undo(destination.parent)
        destination.paste_node_here(source, as_sibling=as_sibling)
        self.note_tree.index_nodes()
        self.note_tree.has_unsaved_operations = True
        self.note_tree.copied_nodes.pop()
        self.note_tree.remove_bookmark_for(source)
        if self.app.info_sidebar.display:
            self.app.info_sidebar.update_data()
        self.render()
        self._fix_cursor_position(source)

    def action_paste_link(self):
        node = self.cursor_node
        if not self.note_tree.copied_nodes or not node:
            return
        source = self.note_tree.copied_nodes[-1]
        destination = node
        if destination == source:
            return
        path_parts = source.get_path(include_self=True)[1:]
        if not path_parts:
            return
        link_text = f"[[{' > '.join(_truncate_link_segment(p) for p in path_parts)}]]"
        as_sibling = (
            destination.parent is not None
            and destination is not self.note_tree.context_node
            and (not destination.children or destination.is_collapsed)
        )
        if as_sibling:
            parent = destination.parent
            self.note_tree.push_undo(parent)
            sibling_index = parent.children.index(destination)
            new_node = parent.add_child(link_text, index=sibling_index + 1)
        else:
            self.note_tree.push_undo(destination)
            new_node = destination.add_child(link_text, top=True)
        self.note_tree.index_nodes()
        self.note_tree.has_unsaved_operations = True
        popped = self.note_tree.copied_nodes.pop()
        self.note_tree.remove_bookmark_for(popped)
        if self.app.info_sidebar.display:
            self.app.info_sidebar.update_data()
        self.render()
        self._fix_cursor_position(new_node)

    def on_mount(self) -> None:
        # Keep the inline time-left readout / expired styling current without a
        # full rebuild (repaints only viewport rows). See _tick_expiry.
        # A single tick walks the tree via iter_timer_nodes(); it's cheap
        # enough (tens of ms even on a 50k-node tree) to run on-demand rather
        # than maintaining a registry. 30s is ample given minute-granular
        # countdown labels.
        self.set_interval(30, self._tick_expiry)

    def _tick_expiry(self) -> None:
        # Walks the tree for timer nodes each tick, fires notifications for any
        # that crossed expiry (all timer nodes, not just visible ones), and
        # keeps the readout / sidebar current.
        nt = self.note_tree
        timer_nodes = nt.iter_timer_nodes()
        if not timer_nodes:
            return
        expired_nodes = nt.check_expirations(timer_nodes)
        if expired_nodes:
            play_sound_effect("timer")  # same cue as the :timer command
        for node in expired_nodes:
            text = node.get_text()  # timer token already stripped
            loop = " ↺" if node.expiry_recurring else ""
            if text.startswith("!"):
                node.run_command()
                self.app.notify(f"▶ Ran: {text[1:].strip()[:50]}{loop}")
            else:
                self.app.notify(f"⌛ Expired: {text[:50]}{loop}", severity="warning")
        node = self.cursor_node
        self.app.status_bar.show_renew_hint = bool(node and node.is_expired())
        # Repaint only when a timer note is actually on screen.
        if any(r.node.expiry_datetime is not None for r in self.rows):
            self._line_cache.clear()
            self.refresh()
        # Keep the Expiring section current (new/expired notes and drifting
        # labels), but only when it's the live view (never clobber search/help).
        # Hand it the list we already walked to avoid a second walk.
        if self.app.info_sidebar.is_showing_bookmarks():
            self.app.info_sidebar.update_data(timer_nodes=timer_nodes)

    def on_resize(self, event) -> None:
        self.render()
        if not self._initial_render_done:
            self._initial_render_done = True
            if self.rows:
                self.move_cursor_to_line(0)

    def action_zoom_in(self):
        node = self.cursor_node
        if not node:
            return
        if self.app.in_search_mode():
            return

        if not node.children:
            paths = extract_path_references(node.text)
            if not paths:
                return
            path_query = paths[0].replace(" › ", ">").replace(" > ", ">")
            matches = self.note_tree.find_by_path_beam(path_query)
            if not matches:
                self.app.notify(f"No path match for: {path_query}")
                return
            target = matches[0]
            self.update_location(
                context_node=target.parent if target.parent else target,
                line_node=target,
            )
            return

        self.note_tree.update_context(node)
        self.render()
        if self.note_tree.context_node.children:
            self._fix_cursor_position(self.note_tree.context_node.children[0])

    def action_zoom_out(self):
        if self.app.in_search_mode():
            return

        node = self.cursor_node
        if not node:
            self.note_tree.update_context(
                self.note_tree.context_node.parent, expand=True
            )
            self.render()
            self.move_cursor_to_line(0)
            return

        if not node.parent:
            return

        current_node_list = self.note_tree.context_node.get_node_list(
            only_visible=False,  # false in case the context node is collapsed
            hide_done=self.note_tree.hide_done,
            hide_archive=self.note_tree.hide_archive,
        )[1:]
        # if the parent is already visible in the current context, just move to it
        if node.parent in current_node_list:
            self._fix_cursor_position(node.parent)
        elif self.cursor_row != 0:
            self.move_cursor_to_line(0)
        else:
            if self.note_tree.context_node.depth > 0:
                _node = self.note_tree.context_node
                self.note_tree.update_context(self.note_tree.context_node.parent)
                self.render()
                self._fix_cursor_position(_node)

    def on_mouse_scroll_down(self, event):
        event.prevent_default()
        event.stop()
        self.action_cursor_down()

    def on_mouse_scroll_up(self, event):
        event.prevent_default()
        event.stop()
        self.action_cursor_up()

    def action_cursor_down(self):
        n = len(self.rows)
        if n == 0:
            return
        for off in range(1, n + 1):
            j = (self.cursor_row + off) % n
            if self._is_navigable(j):
                self._set_cursor(j)
                return

    def action_cursor_up(self):
        n = len(self.rows)
        if n == 0:
            return
        for off in range(1, n + 1):
            j = (self.cursor_row - off) % n
            if self._is_navigable(j):
                self._set_cursor(j)
                return

    def action_save(self):
        logging.info("SAVING")
        self.note_tree.save()
        self.app.status_bar.needs_saving = self.note_tree.has_unsaved_operations

    def action_undo(self):
        if self.note_tree.pop_undo():
            self.render()
            self.move_cursor_to_line(0)
            if self.app.info_sidebar.is_showing_bookmarks():
                self.app.info_sidebar.update_data()

    def action_redo(self):
        if self.note_tree.pop_redo():
            self.render()
            self.move_cursor_to_line(0)
            if self.app.info_sidebar.is_showing_bookmarks():
                self.app.info_sidebar.update_data()

    def add_journal_entry(self, text):
        new_node = self.note_tree.add_journal_entry(text)
        self.note_tree.context_node = new_node.parent
        self.render()
        self.move_cursor_to_line(0)

    def visit_bookmark(self, bookmark_index: int):
        _node = self.note_tree.jump_to_bookmark(bookmark_index)
        if _node:
            self.render()
            self.move_cursor_to_line(0)

    def jump_to_random(self, global_scope=False):
        if global_scope:
            nodes = self.note_tree.root.get_node_list(
                only_visible=False, hide_archive=self.note_tree.hide_archive
            )
        else:
            nodes = self.note_tree.context_node.get_node_list(
                only_visible=False, hide_archive=self.note_tree.hide_archive
            )
        nodes = [
            n
            for n in nodes
            if n.parent is not None and n is not self.note_tree.context_node
        ]
        if not nodes:
            self.app.notify("No notes to jump to")
            return
        target = random.choice(nodes)
        if global_scope:
            if target.parent:
                self.update_location(target.parent, target)
            else:
                self.update_location(target, target)
        else:
            # Expand collapsed ancestors to reveal the target
            node = target
            while node and node is not self.note_tree.context_node:
                if node.is_collapsed:
                    node.is_collapsed = False
                node = node.parent
            self.render()
            self._fix_cursor_position(target)

    def assign_bookmark(self, slot: int):
        node = self.cursor_node
        if not node or not node.parent:
            return
        self.note_tree.assign_bookmark(node, slot)
        if self.app.info_sidebar.display:
            self.app.info_sidebar.update_data()
        if not self._restyle_node(node):
            self.render()
            self._fix_cursor_position(node)

    def add_subtree(self, subtree_name: str):
        node = self.cursor_node
        if not node:
            return
        if subtree_name in SUBTREES:
            add_subtree(node, SUBTREES[subtree_name])
            self.render()

    # --------------------------------------------------------------- status

    def _update_progress(self):
        node = self.cursor_node
        self.app.status_bar.show_renew_hint = bool(node and node.is_expired())
        if not node:
            self.app.status_bar.progress = (0, 0)
            return
        try:
            self.app.status_bar.progress = (
                self.note_tree.visible_node_list.index(node),
                len(self.note_tree.visible_node_list) - 1,
            )
        except ValueError:
            logging.error(f"Node not in list: {node.text}")

    def _scroll_cursor_into_margin(self) -> None:
        line = self.cursor_row
        height = self.size.height
        if height <= 0 or line < 0:
            return
        margin = self.app.config.scroll_margin
        margin = min(margin, max(0, (height - 1) // 2))
        top = int(self.scroll_offset.y)
        bottom = top + height - 1
        if line < top + margin:
            self.scroll_to(y=max(0, line - margin), animate=False, force=True)
        elif line > bottom - margin:
            self.scroll_to(y=line - height + 1 + margin, animate=False, force=True)
