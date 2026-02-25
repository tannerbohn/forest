import re
import textwrap

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

STICKY_COLORS = [
    ("#000000", "#00b0ff"),  # ligh blue
    ("#000000", "#ff5722"),  # burnt orange
    ("#000000", "#ffc107"),  # yellow orange
    ("#000000", "#aaff00"),  # green
    ("#000000", "#ffff00"),  # yellow
    ("#000000", "#1ee6b4"),  # green-teal
    # ("#000000", "#ffffff")
]

# Strip hashtags like #HL1 #HL2 #HL3 #DONE from display text
_STRIP_TAGS_RE = re.compile(r"\s*#(?:HL[123]|DONE)\b")

NOTE_WIDTH = 20
NOTE_HEIGHT = 10
CELL_WIDTH = NOTE_WIDTH + 4  # padding + gutter


def _color_for_text(text: str):
    """Deterministic color based on text content."""
    return STICKY_COLORS[sum(ord(ch) for ch in text) % len(STICKY_COLORS)]


def _display_text(text: str) -> str:
    """Strip tag hashtags for cleaner display."""
    return _STRIP_TAGS_RE.sub("", text).strip()


def _wrap_and_truncate(text: str, content_width: int, content_height: int) -> str:
    """Wrap text and truncate with ellipsis if it overflows the given dimensions."""
    lines = textwrap.wrap(text, width=content_width, break_long_words=True)
    if len(lines) > content_height:
        lines = lines[:content_height]
        last = lines[-1]
        if len(last) > content_width - 1:
            last = last[: content_width - 1]
        lines[-1] = last.rstrip() + "…"
    return "\n".join(lines)


def _ancestor_list(node):
    """Return list of ancestor nodes from root down (excluding invisible root)."""
    ancestors = []
    cur = node.parent
    while cur and cur.parent is not None:
        ancestors.append(cur)
        cur = cur.parent
    return ancestors[::-1]


def _global_common_ancestor(nodes):
    """Find the deepest ancestor shared by all nodes."""
    if not nodes:
        return None
    paths = [_ancestor_list(n) for n in nodes]
    shortest = min(len(p) for p in paths)
    shared = None
    for depth in range(shortest):
        if len(set(id(p[depth]) for p in paths)) == 1:
            shared = paths[0][depth]
        else:
            break
    return shared


def _group_nodes_by_branch(nodes):
    """Group nodes by which child of their global common ancestor they descend from.

    Returns list of (branch_root_node_or_None, [nodes]).
    branch_root is the child of the global common ancestor that roots each group.
    """
    if len(nodes) <= 1:
        return [(None, nodes)]

    global_ancestor = _global_common_ancestor(nodes)
    global_depth = (len(_ancestor_list(global_ancestor)) + 1) if global_ancestor else 0

    # Bucket each node by the ancestor just below the global common ancestor
    buckets = {}  # branch_root_node_id -> (branch_root_node, [nodes])
    ungrouped = []
    for node in nodes:
        ancestors = _ancestor_list(node)
        if len(ancestors) > global_depth:
            branch_root = ancestors[global_depth]
            key = id(branch_root)
            if key not in buckets:
                buckets[key] = (branch_root, [])
            buckets[key][1].append(node)
        else:
            ungrouped.append(node)

    # Remove from ungrouped any node that is already a branch root
    # (those nodes will appear as BranchRootWidget, not StickyNoteWidget)
    branch_root_ids = {id(br) for br, _ in buckets.values()}
    ungrouped = [n for n in ungrouped if id(n) not in branch_root_ids]

    # If everything lands in one bucket, no grouping needed
    if len(buckets) <= 1 and not ungrouped:
        return [(None, nodes)]

    groups = list(buckets.values())
    if ungrouped:
        groups.append((None, ungrouped))
    return groups


class StickyNoteWidget(Static):
    can_focus = True

    def __init__(self, node, hl_colors=None, **kwargs):
        super().__init__(**kwargs)
        self.node = node
        if hl_colors and node.highlight_index is not None:
            bg = hl_colors[node.highlight_index]
            fg = "#000000"

            self.styles.background = bg
            self.styles.color = f"{fg} 90%"
        else:
            fg, bg = _color_for_text(node.text)

            self.styles.background = f"{bg} 85%"
            self.styles.color = f"{fg} 70%"

        # self.styles.background = bg
        # self.styles.color = f"{fg} 80%"
        self.styles.height = NOTE_HEIGHT
        self.styles.padding = (1, 2)
        self.styles.text_wrap = "wrap"
        if hl_colors and node.highlight_index is not None:
            self.styles.text_style = "bold"

    def compose(self) -> ComposeResult:
        return []

    def on_mount(self):
        display = _display_text(self.node.text)
        if self.node.highlight_index is not None:
            display = "★ " + display
        content_width = NOTE_WIDTH - 4  # padding: 2 left + 2 right
        content_height = NOTE_HEIGHT - 2  # padding: 1 top + 1 bottom
        self.update(_wrap_and_truncate(display, content_width, content_height))

    def on_click(self):
        self.screen.dismiss(self.node)


class BranchRootWidget(StickyNoteWidget):
    """A sticky note representing a branch's common ancestor."""

    def __init__(self, node, **kwargs):
        super().__init__(node, **kwargs)
        self.styles.background = "#333333"
        self.styles.color = f"#ffffff 70%"  # "#aaaaaa"
        self.styles.height = NOTE_HEIGHT
        self.styles.text_style = "bold"

    def on_mount(self):
        path_str = self.node.get_path_string(width=(NOTE_WIDTH - 2) * (NOTE_HEIGHT - 3))
        if not path_str:
            path_str = _display_text(self.node.text)
        # Account for border (1 col each side, 1 row each side) on top of padding
        content_width = NOTE_WIDTH - 2 - 4  # border: 2 + padding: 4
        content_height = NOTE_HEIGHT - 2 - 2  # border: 2 + padding: 2
        self.update(_wrap_and_truncate(path_str, content_width, content_height))


class StickyNotesScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss_screen", "Close"),
        Binding("q", "dismiss_screen", "Close"),
    ]

    CSS = """
    StickyNotesScreen {
        background: $background 95%;
        layout: vertical;
    }

    #sn-title {
        width: 100%;
        height: 1;
        text-align: center;
        text-style: bold;
        background: $panel;
        color: $foreground;
    }

    VerticalScroll {
        height: 1fr;
    }

    #sn-grid {
        grid-gutter: 1 2;
        grid-rows: 10;
        padding: 1 2;
        height: auto;
    }

    StickyNoteWidget {
        opacity: 0.85;
    }

    StickyNoteWidget:focus {
        opacity: 1.0;
    }

    BranchRootWidget {
        opacity: 0.85;
    }

    BranchRootWidget:focus {
        opacity: 0.9;
    }
    """

    def __init__(self, nodes, title_text="Sticky Notes", hl_colors=None, **kwargs):
        super().__init__(**kwargs)
        self.nodes = nodes
        self.title_text = title_text
        self.hl_colors = hl_colors or {}
        self._cols = 1
        self._cursor_index = 0

    def compose(self) -> ComposeResult:
        yield Static(self.title_text, id="sn-title")
        with VerticalScroll():
            with Grid(id="sn-grid"):
                groups = _group_nodes_by_branch(self.nodes)
                for ancestor, group_nodes in groups:
                    if ancestor is not None:
                        yield BranchRootWidget(ancestor)
                    for node in group_nodes:
                        yield StickyNoteWidget(node, hl_colors=self.hl_colors)

    def _build_title(self):
        """Build title string with count and common ancestor."""
        parts = [self.title_text, f"({len(self.nodes)})"]
        ancestor = _global_common_ancestor(self.nodes)
        if ancestor:
            path = ancestor.get_path_string(width=60)
            if path:
                parts.append(f"— {path}")
        return " ".join(parts)

    def on_mount(self):
        self._update_columns()
        self.query_one("#sn-title", Static).update(self._build_title())
        widgets = self.query("StickyNoteWidget, BranchRootWidget")
        if widgets:
            widgets[0].focus()

    def on_resize(self, event):
        self._update_columns()

    def _update_columns(self):
        grid = self.query_one("#sn-grid", Grid)
        self._cols = max(1, self.size.width // CELL_WIDTH)
        grid.styles.grid_size_columns = self._cols

    def on_key(self, event):
        widgets = list(self.query("StickyNoteWidget, BranchRootWidget"))
        if not widgets:
            return

        delta = None
        if event.key == "left":
            delta = -1
        elif event.key == "right":
            delta = 1
        elif event.key == "up":
            delta = -self._cols
        elif event.key == "down":
            delta = self._cols
        elif event.key == "enter":
            self.dismiss(widgets[self._cursor_index].node)
            event.prevent_default()
            event.stop()
            return

        if delta is not None:
            new_index = max(0, min(len(widgets) - 1, self._cursor_index + delta))
            self._cursor_index = new_index
            widget = widgets[self._cursor_index]
            widget.focus()
            vs = self.query_one(VerticalScroll)
            row = self._cursor_index // self._cols
            row_height = NOTE_HEIGHT + 1  # note height + grid gutter
            row_top = row * row_height + 1  # +1 for grid padding top
            row_bottom = row_top + NOTE_HEIGHT
            if row_top < vs.scroll_y:
                vs.scroll_to(y=row_top, animate=True)
            elif row_bottom > vs.scroll_y + vs.scrollable_content_region.height:
                vs.scroll_to(
                    y=row_bottom - vs.scrollable_content_region.height, animate=True
                )
            event.prevent_default()
            event.stop()

    def action_dismiss_screen(self):
        self.dismiss(None)
