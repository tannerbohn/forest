import argparse
import json
import logging
import os
import re
import textwrap
from dataclasses import dataclass
from datetime import datetime

os.environ["COLORTERM"] = "truecolor"

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.theme import Theme
from textual.widgets import Footer, Input, Markdown, ProgressBar, Tree

from config import Config
from node import Node
from note_tree import NoteTree
from note_tree_widget import NoteTreeWidget
from search_state import SearchState
from sticky_notes import StickyNotesScreen, _parse_flashcard
from themes import THEMES
from timer import Timer
from utils import (apply_input_substitutions, compose_clock_notify_contents,
                   extract_path_references)
from widgets.command_info_panel import CommandInfoPanel
from widgets.doodle_pane import DoodlePane
from widgets.info_sidebar import InfoSidebar
from widgets.status_bar import StatusBar
from widgets.suggesters import MultiPurposeSuggester

# Load configuration from config.json
config = Config()

# Shift+<digit> arrives as the shifted symbol character. Textual's event.key
# uses named aliases for many of these; event.character is the raw symbol.
# Accept both forms so layouts/terminals that deliver either still work.
SHIFT_DIGIT_TO_SLOT = {
    "!": 1,
    "@": 2,
    "#": 3,
    "$": 4,
    "%": 5,
    "^": 6,
    "&": 7,
    "*": 8,
    "(": 9,
    ")": 0,
    "exclamation_mark": 1,
    "at": 2,
    "number_sign": 3,
    "dollar_sign": 4,
    "percent_sign": 5,
    "circumflex_accent": 6,
    "ampersand": 7,
    "asterisk": 8,
    "left_parenthesis": 9,
    "right_parenthesis": 0,
}


def setup_logging(tree_filepath):
    """Configure per-instance logging based on the tree file being opened."""
    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    tree_name = os.path.splitext(os.path.basename(tree_filepath))[0]
    log_file = os.path.join(log_dir, f"{tree_name}.log")
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    logging.basicConfig(
        filename=log_file,
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        filemode="w",
        force=True,
    )
    logging.info("Application started for %s", tree_filepath)


@dataclass(frozen=True)
class Command:
    """A `:`-mode command. Matches when cmd_str equals one of `names`,
    or (if takes_args) starts with `<name> `."""

    names: tuple
    handler_attr: str
    takes_args: bool = False

    def match(self, cmd_str: str):
        """Return the matched name (str) if cmd_str matches, else None."""
        for n in self.names:
            if cmd_str == n:
                return n
            if self.takes_args and cmd_str.startswith(n + " "):
                return n
        return None


class ForestApp(App):
    # CSS_PATH = "forest.tcss"
    CSS = """
    Screen {
        layers: base overlay;
    }
    #input-box {
        display: none;
        layer: overlay;
        offset: 0 1;
        background: $background;
        border: $HL1 75%;
    }
    ScrollView {
        scrollbar-size: 0 0;
    }
    Tree {
        &:focus {
            background-tint: $foreground 0%;
        }
        & > .tree--cursor {
            color: blue;
        }
        & > .tree--highlight-line {
            background: $foreground 10%;
        }
        & > .tree--guides-selected {
            color: transparent;
        }
    }
    """

    BINDINGS = [
        Binding("backspace", "edit_note()", "Edit note", show=True),
        Binding(":", "command_mode()", "Command mode", show=True),
        Binding("grave_accent", "cycle_side_panel()", "Cycle side panel", show=True),
    ]

    _MIN_TREE_WIDTH = 50
    _DEFAULT_SIDEBAR_WIDTH = 40

    _DOODLE_WIDTH = 30

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.config = config  # Reference to global config

        # Register themes early so they're available before first render
        for theme in THEMES.values():
            self.register_theme(theme)
        self.theme = self.config.default_theme

        self.note_tree = NoteTree(
            self.file_path,
            undo_depth=self.config.undo_depth,
        )
        self._node_being_edited = None
        self._search = SearchState()

        self.timer = Timer(self)
        self._sticky_note_state = None

        self._command_history: list[str] = []
        self._history_index: int = -1
        self._history_draft: str = ""

        self.logging = logging

    def record_command(self, cmd_str: str) -> None:
        if cmd_str and (
            not self._command_history or self._command_history[-1] != cmd_str
        ):
            self._command_history.append(cmd_str)
        self._history_index = -1

    def history_up(self) -> bool:
        if not self._command_history:
            return False
        if self._history_index == -1:
            self._history_draft = self.input_widget.value
        if self._history_index < len(self._command_history) - 1:
            self._history_index += 1
        self.input_widget.value = self._command_history[-(self._history_index + 1)]
        return True

    def history_down(self) -> bool:
        if self._history_index > -1:
            self._history_index -= 1
        if self._history_index == -1:
            self.input_widget.value = self._history_draft
        else:
            self.input_widget.value = self._command_history[-(self._history_index + 1)]
        return True

    def reset_history_index(self) -> None:
        self._history_index = -1

    def on_mount(self):
        if self.config.auto_save and self.config.auto_save_interval > 0:
            self.set_interval(self.config.auto_save_interval, self._auto_save)

        self._apply_layout()

        next_id, canvases = self.note_tree.load_doodles_sidecar()
        self._doodle_next_id = next_id
        self.doodle_pane.load_from_sidecar(canvases)
        self.note_tree.register_doodle_payload_provider(
            lambda: (self._doodle_next_id, self.doodle_pane.to_sidecar_payload())
        )
        self.doodle_pane.set_context(self.note_tree.context_node)

        # Seed context history with the loaded position so the first navigation
        # has a valid "back" target.
        self.note_tree_widget.context_history.seed(
            self.note_tree.context_node, self.note_tree_widget.cursor_node
        )

    def _allocate_doodle_id(self) -> int:
        i = self._doodle_next_id
        self._doodle_next_id += 1
        return i

    def _apply_layout(self):
        # Fixed sides: info sidebar on the right, doodle pane on the left. Both
        # margins are reserved permanently (the panes toggle visibility within
        # the reserved strip); a margin is only dropped when it would shrink the
        # tree below its minimum width.
        width = self.config.margin_width
        screen_width = self.size.width
        doodle_w = self._DOODLE_WIDTH

        if width <= 0 or screen_width - width < self._MIN_TREE_WIDTH:
            sidebar_margin = 0
            sidebar_width = self._DEFAULT_SIDEBAR_WIDTH
        else:
            sidebar_margin = width
            sidebar_width = width

        remaining = screen_width - sidebar_margin - doodle_w
        doodle_margin = doodle_w if remaining >= self._MIN_TREE_WIDTH else 0

        # Keep a 1-col gap so the tree text doesn't butt against the sidebar's
        # divider (only when the sidebar actually reserves space).
        tree_sidebar_margin = sidebar_margin + 1 if sidebar_margin else 0

        self.note_tree_widget.styles.margin = (0, tree_sidebar_margin, 0, doodle_margin)

        self.info_sidebar.apply_layout("right", sidebar_width)
        self.doodle_pane.apply_layout("left", doodle_w)

    def on_resize(self, event):
        self.call_after_refresh(self._apply_layout)

    def _auto_save(self):
        if self.note_tree.has_unsaved_operations:
            self.note_tree.save()
            self.status_bar.needs_saving = False

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""

        logging.info(f"COMPOSING APP. SIZE: {self.size}")

        self.status_bar = StatusBar(id="status-bar")
        yield self.status_bar

        self.edit_suggester = MultiPurposeSuggester(mode="edit")
        self.command_suggester = MultiPurposeSuggester(mode="command")
        self.input_widget = Input(id="input-box", suggester=self.command_suggester)
        yield self.input_widget

        self.command_info_panel = CommandInfoPanel(id="command-info")
        yield self.command_info_panel

        self.note_tree_widget = NoteTreeWidget(note_tree=self.note_tree, id="note-tree")
        self.note_tree_widget.focus()
        self.info_sidebar = InfoSidebar(id="info-sidebar")
        self.doodle_pane = DoodlePane(id="doodle-pane")

        # Pre-apply the (constant) margins so the tree's initial render wraps at
        # the final width, avoiding a visible reflow when on_mount later calls
        # _apply_layout(). Both panes start hidden; their margins are reserved
        # regardless. Info sidebar right, doodle pane left.
        sidebar_margin = self.config.margin_width if self.config.margin_width > 0 else 0
        tree_sidebar_margin = sidebar_margin + 1 if sidebar_margin else 0
        doodle_margin = self._DOODLE_WIDTH
        self.note_tree_widget.styles.margin = (0, tree_sidebar_margin, 0, doodle_margin)

        yield self.note_tree_widget
        yield self.info_sidebar
        yield self.doodle_pane

    def get_theme_variable_defaults(self):
        # Return the variables for the current theme
        theme = THEMES.get(self.theme)
        if theme:
            return theme.variables
        return {}

    def jump_to_node(self, node):
        """Move the tree cursor to `node` and hand focus back to the tree.
        Shared by the sidebar's Enter-to-jump handler across all panels."""
        if node is None:
            return
        self.note_tree_widget.update_location(context_node=node.parent, line_node=node)
        self.note_tree_widget.focus()

    def accept_search(self, node):
        """Enter on a search result: commit to it and leave search mode."""
        self.status_bar.search_mode = False
        self._search.clear()
        self.info_sidebar.hide_search_results()
        if node is not None:
            self.note_tree_widget.update_location(
                context_node=node.parent, line_node=node
            )
        self.note_tree_widget.focus()

    def cancel_search(self):
        """Escape in search mode: restore the pre-search position."""
        self.status_bar.search_mode = False
        pos = self._search.pre_search_position
        self._search.clear()
        self.info_sidebar.hide_search_results()
        if pos and pos[0] is not None:
            self.note_tree_widget.update_location(context_node=pos[0], line_node=pos[1])
        self.note_tree_widget.focus()

    def hide_sidebar_focus_tree(self):
        """Escape in a non-search panel: hide the sidebar and doodle pane,
        refocus the tree."""
        self.info_sidebar.mode_index = 0
        self.info_sidebar.update_data()
        self.doodle_pane.set_visible(False)
        self.note_tree_widget.focus()

    def action_edit_note(self):
        # if the input widget already in use, stop
        if self.input_widget.display:
            return

        node = self.note_tree_widget.cursor_node

        if not node:
            return

        label_text = str(node.text)
        # Create an Input widget pre-filled with the current label
        self._node_being_edited = node
        # input_widget.id = f"input-{id(node)}"
        self.input_widget.suggester = self.edit_suggester
        self.input_widget.display = True
        self.input_widget.value = label_text
        self.input_widget.placeholder = ""
        self.input_widget.focus()
        self.input_widget.border_title = "Editing..."
        self.input_widget.border_subtitle = f" {compose_clock_notify_contents()[0]} "
        # The expiring/archived panel is command-mode only.
        self.command_info_panel.display = False

    def action_cycle_side_panel(self):
        logging.info("action_cycle_side_panel called")
        sidebar = self.info_sidebar
        if sidebar.is_open and self.focused is not sidebar:
            # Visible but the cursor is elsewhere: `` ` `` first hands focus back
            # to the panel without advancing the mode.
            sidebar.focus()
            return
        # Hidden -> reveal first mode; already focused -> rotate to the next
        # mode (which may hide the panel and return focus to the tree). The
        # doodle pane is revealed/hidden together with the sidebar.
        sidebar.cycle_mode()
        self.doodle_pane.set_visible(sidebar.is_open)
        if sidebar.is_open:
            sidebar.focus()
        else:
            self.note_tree_widget.focus()

    def _copied_refresh_sidebar(self) -> None:
        sidebar = getattr(self, "info_sidebar", None)
        if sidebar is None or not sidebar.is_open or sidebar._search_results:
            return
        sidebar.update_data()

    def resolve_paste_source(self):
        """The note v/l act on: the last quick-link entry the user focused in
        the bookmarks panel, if it's still copied, else the top of the copied
        stack. Returns None when nothing is available to paste."""
        nt = self.note_tree
        src = getattr(self, "_paste_source_node", None)
        if src is not None and src in nt.copied_nodes:
            return src
        return nt.copied_nodes[-1] if nt.copied_nodes else None

    def copied_toggle(self, node) -> None:
        nodes = self.note_tree.copied_nodes
        if node in nodes:
            nodes.remove(node)
            self.note_tree.remove_bookmark_for(node)
            if getattr(self, "_paste_source_node", None) is node:
                self._paste_source_node = None
        else:
            nodes.append(node)
            # A freshly copied note becomes the paste/link target (as if focused).
            self._paste_source_node = node
        self.note_tree.has_unsaved_operations = True
        self.status_bar.needs_saving = True
        self._copied_refresh_sidebar()

    def copied_move(self, node, up: bool) -> None:
        # Reorder a copied note within the non-bookmarked tail. The sidebar
        # renders copied_nodes reversed, so moving "up" (toward the paste-target
        # top) means a higher list index. Bookmarked copies stay slot-ordered
        # at the start of the list and aren't manually movable.
        nodes = self.note_tree.copied_nodes
        if node not in nodes:
            return
        k = self.note_tree.bookmark_split_index()
        i = nodes.index(node)
        if i < k:
            return
        j = i + 1 if up else i - 1
        if j < k or j >= len(nodes):
            return
        nodes[i], nodes[j] = nodes[j], nodes[i]
        self.note_tree.has_unsaved_operations = True
        self.status_bar.needs_saving = True
        self._copied_refresh_sidebar()

    def _toggle_archive_tag(self, node, add: bool) -> bool:
        has_tag = "#ARCHIVE" in node.text
        if add == has_tag:
            return False
        self.note_tree.push_undo(node.parent or node)
        if add:
            words = node.text.split()
            words.append("#ARCHIVE")
        else:
            words = [w for w in node.text.split() if w != "#ARCHIVE"]
        node.text = " ".join(words)
        node.post_text_update()
        self.note_tree.has_unsaved_operations = True
        self.note_tree.update_visible_node_list()
        self.note_tree_widget.render()
        return True

    @staticmethod
    def _filter_flashcard_answers(nodes):
        """Drop the first-child answer node of any child-answer flashcard."""
        answer_ids = set()
        for n in nodes:
            fc = _parse_flashcard(n)
            if fc and fc[2] and n.children:  # fc[2] = is_child_answer
                answer_ids.add(id(n.children[0]))
        return [n for n in nodes if id(n) not in answer_ids]

    def _open_sticky_screen(
        self,
        nodes,
        title,
        hl_colors,
        cursor_index=0,
        refresh_state_nodes_on_dismiss=False,
    ):
        self._sticky_note_state = {
            "nodes": nodes,
            "title": title,
            "hl_colors": hl_colors,
            "cursor_index": cursor_index,
        }
        self.status_bar.has_sticky_recovery = True
        screen = StickyNotesScreen(nodes, title_text=title, hl_colors=hl_colors)
        screen._cursor_index = min(cursor_index, max(0, len(nodes) - 1))

        def on_dismiss(node):
            self._sticky_note_state["cursor_index"] = screen._cursor_index
            if refresh_state_nodes_on_dismiss:
                self._sticky_note_state["nodes"] = nodes
            if node is not None:
                self.note_tree_widget.update_location(
                    context_node=node.parent if node.parent else node,
                    line_node=node,
                )

        self.push_screen(screen, callback=on_dismiss)

    def _cmd_journal(self, cmd_str, args_str):
        if not args_str:
            self.notify("Usage: j+ <text>")
            return
        self.note_tree.push_undo(self.note_tree.root)
        self.note_tree_widget.add_journal_entry(args_str)

    def _cmd_search(self, cmd_str, args_str):
        global_scope = cmd_str.startswith("?*") or cmd_str.startswith("??")
        query = cmd_str[2:].strip() if global_scope else cmd_str[1:].strip()
        query = query.replace(" › ", ">").replace(" > ", ">")

        if not query:
            cursor_node = self.note_tree_widget.cursor_node
            if not cursor_node:
                self.notify("No note selected.")
                return
            results = self.note_tree.find_by_similarity(cursor_node)
            results = [r for r in results if r[1] >= 0.10]
            if not global_scope:
                results = [r for r in results if r[3]]
            matching_nodes = [r[0] for r in results]
            display_query = ""
        else:
            matching_nodes = self.note_tree.find_by_query(
                query,
                global_scope=global_scope,
                match_path=">" in query,
                threshold=0.1,
            )[:20]
            display_query = query

        if not matching_nodes:
            self.notify("No search results found.")
            return

        self._search.query = query
        self._search.context_node = self.note_tree.context_node
        self._search.is_local = not global_scope
        self._search.matches = matching_nodes
        self.status_bar.search_mode = True
        cursor_node_obj = self.note_tree_widget.cursor_node
        self._search.pre_search_position = (
            self.note_tree.context_node,
            cursor_node_obj,
        )
        self.info_sidebar.show_search_results(matching_nodes, display_query)
        self._pending_sidebar_focus = True

    def _cmd_help(self, cmd_str, args_str):
        self.info_sidebar.show_help()
        self._pending_sidebar_focus = True

    def _cmd_doodle(self, cmd_str, args_str):
        sub = args_str.strip()
        if sub == "clear":
            self.doodle_pane.clear_current()
        else:
            self.notify("Usage: doodle clear")

    def _cmd_run(self, cmd_str, args_str):
        index = 0
        if args_str:
            try:
                index = int(args_str)
            except ValueError:
                self.notify("Usage: :run or :run <index>")
                return
        if not self.note_tree_widget.cursor_node:
            self.notify("No note selected")
            return
        node = self.note_tree_widget.cursor_node
        if node.text.startswith("!"):
            try:
                logging.info("Running command")
                node.run_command()
            except Exception as e:
                logging.error(f"Could not run command: {e}")
            return
        paths = extract_path_references(node.text)
        if not paths:
            self.notify("No ! command or [[path]] reference found")
            return
        if index >= len(paths):
            self.notify(f"Index {index} out of range (found {len(paths)} path(s))")
            return
        path_query = paths[index].replace(" › ", ">").replace(" > ", ">")
        matching_nodes = self.note_tree.find_by_path_beam(path_query)
        if not matching_nodes:
            self.notify(f"No path match for: {path_query}")
            return
        target = matching_nodes[0]
        self.note_tree_widget.update_location(
            context_node=target.parent if target.parent else target,
            line_node=target,
        )

    def _cmd_collapse(self, cmd_str, args_str):
        ctx = self.note_tree.context_node
        descendants = ctx.get_node_list(
            only_visible=False,
            hide_done=False,
            hide_archive=self.note_tree.hide_archive,
        )[1:]
        if not any(n.children for n in descendants):
            return
        self.note_tree.push_undo(ctx)
        for n in descendants:
            if n.children:
                n.is_collapsed = True
        self.note_tree.update_visible_node_list()
        self.note_tree.has_unsaved_operations = True
        self.note_tree_widget.render()

    def _cmd_insert(self, cmd_str, args_str):
        if not args_str:
            self.notify("Usage: insert <subtree name>")
            return
        self.note_tree_widget.add_subtree(args_str)

    def _cmd_random(self, cmd_str, args_str):
        self.note_tree_widget.jump_to_random(global_scope=cmd_str == "random*")

    def _cmd_timer_cancel(self, cmd_str, args_str):
        self.timer.cancel()

    def _cmd_timer(self, cmd_str, args_str):
        self.timer.start(args_str)

    def _cmd_sticky(self, cmd_str, args_str):
        global_scope = cmd_str.startswith("sn*")
        filter_arg = args_str
        scope_root = (
            self.note_tree.root if global_scope else self.note_tree.context_node
        )
        all_nodes = scope_root.get_node_list(
            only_visible=False,
            hide_done=True,
            hide_archive=self.note_tree.hide_archive,
        )
        all_nodes = [
            n
            for n in all_nodes
            if n.parent is not None and n is not self.note_tree.context_node
        ]

        if not filter_arg:
            matched = [n for n in all_nodes if n.highlight_index is not None]
            title = "#HL"
        elif filter_arg in ("#HL1", "#HL2", "#HL3"):
            hl_idx = int(filter_arg[-1]) - 1
            matched = [n for n in all_nodes if n.highlight_index == hl_idx]
            title = filter_arg
        else:
            try:
                pat = re.compile(filter_arg, re.IGNORECASE)
            except re.error:
                pat = re.compile(re.escape(filter_arg), re.IGNORECASE)
            matched = [n for n in all_nodes if pat.search(n.text)]
            title = f"/{filter_arg}/"

        matched = self._filter_flashcard_answers(matched)

        if not matched:
            self.notify("No matching notes found.")
            return

        hl_colors = {
            0: self.theme_variables.get("HL1", "#039ad7"),
            1: self.theme_variables.get("HL2", "#dca708"),
            2: self.theme_variables.get("HL3", "#c44f1f"),
        }
        self._open_sticky_screen(matched, title, hl_colors)

    def _cmd_snr(self, cmd_str, args_str):
        state = self._sticky_note_state
        if not state:
            self.notify("No sticky note board to recover.")
            return
        all_tree_ids = {
            id(n)
            for n in self.note_tree.root.get_node_list(
                only_visible=False,
                hide_done=False,
                hide_archive=self.note_tree.hide_archive,
            )
        }
        valid_nodes = [
            n for n in state["nodes"] if id(n) in all_tree_ids and not n.is_done()
        ]
        valid_nodes = self._filter_flashcard_answers(valid_nodes)
        if not valid_nodes:
            self.notify("All notes from that board have been removed.")
            self._sticky_note_state = None
            self.status_bar.has_sticky_recovery = False
            return
        self._open_sticky_screen(
            valid_nodes,
            state["title"],
            state["hl_colors"],
            cursor_index=state["cursor_index"],
            refresh_state_nodes_on_dismiss=True,
        )

    def _cmd_archive(self, cmd_str, args_str):
        sub = args_str.strip()
        if sub == "set":
            node = self.note_tree_widget.cursor_node
            if self._toggle_archive_tag(node, add=True) and self.note_tree.hide_archive:
                self.note_tree_widget.move_cursor_to_line(0)
        elif sub == "unset":
            self._toggle_archive_tag(self.note_tree_widget.cursor_node, add=False)
        elif sub == "show":
            self.note_tree.hide_archive = False
            self.status_bar.hide_archive = False
            self.note_tree.update_visible_node_list()
            self.note_tree_widget.render()
        elif sub == "hide":
            self.note_tree.hide_archive = True
            self.status_bar.hide_archive = True
            cursor_node = self.note_tree_widget.cursor_node
            self.note_tree.update_visible_node_list()
            self.note_tree_widget.render()
            if cursor_node and cursor_node.is_archived():
                self.note_tree_widget.move_cursor_to_line(0)
            elif cursor_node:
                self.note_tree_widget._fix_cursor_position(cursor_node)
        else:
            self.notify("Usage: archive set|unset|show|hide")
            return
        self.info_sidebar.update_data()

    # Order matters: more specific prefixes before shorter ones (e.g. "timer cancel" before "timer").
    _COMMAND_REGISTRY = (
        Command(("help",), "_cmd_help"),
        Command(("j+",), "_cmd_journal", takes_args=True),
        Command(("doodle",), "_cmd_doodle", takes_args=True),
        Command(("run",), "_cmd_run", takes_args=True),
        Command(("collapse",), "_cmd_collapse"),
        Command(("insert",), "_cmd_insert", takes_args=True),
        Command(("random", "random*"), "_cmd_random"),
        Command(("timer cancel",), "_cmd_timer_cancel"),
        Command(("timer",), "_cmd_timer", takes_args=True),
        Command(("sn", "sn*"), "_cmd_sticky", takes_args=True),
        Command(("snr",), "_cmd_snr"),
        Command(("archive",), "_cmd_archive", takes_args=True),
    )

    def _dispatch_command(self, cmd_str):
        # "?" is a marker prefix (no space before query) — it doesn't fit the
        # word-command shape, so handle it up front.
        if cmd_str.startswith("?"):
            self._cmd_search(cmd_str, "")
            return
        for cmd in self._COMMAND_REGISTRY:
            name = cmd.match(cmd_str)
            if name is not None:
                args_str = cmd_str[len(name) :].lstrip()
                getattr(self, cmd.handler_attr)(cmd_str, args_str)
                return

    def on_input_submitted(self, event):
        logging.info(f"INPUT SUBMITTED: {event}")
        if self._node_being_edited:
            new_text = event.value.strip()
            if new_text:
                new_text = apply_input_substitutions(new_text)
                node = self._node_being_edited
                self.note_tree.push_undo(node.parent)
                node.text = new_text
                node.post_text_update()
                self.note_tree.has_unsaved_operations = True
                self.note_tree_widget.render()
                self.note_tree_widget._fix_cursor_position(node)
                # Editing may add/remove/change a #T- timer.
                if self.info_sidebar.is_showing_bookmarks():
                    self.info_sidebar.update_data()
            self._node_being_edited = None
        else:
            cmd_str = event.value.strip()
            self.record_command(cmd_str)
            self._dispatch_command(cmd_str)

        self.input_widget.value = ""
        self.input_widget.display = False
        self.command_info_panel.display = False
        # A search/help command opens the sidebar and wants keyboard focus so
        # arrows navigate its entries; everything else keeps focus on the tree.
        if getattr(self, "_pending_sidebar_focus", False) and self.info_sidebar.is_open:
            self.info_sidebar.focus()
            self._pending_sidebar_focus = False
        else:
            self._pending_sidebar_focus = False
            self.note_tree_widget.focus()

    def action_command_mode(self):
        # if the input widget already in use, stop
        if self.input_widget.display:
            return

        self.input_widget.offset = (0, 1)

        self.input_widget.suggester = self.command_suggester
        self.input_widget.display = True
        self.input_widget.value = ""
        self.input_widget.placeholder = self.command_suggester.placeholder
        self.input_widget.focus()
        self.input_widget.border_title = None  # "Command mode"
        self.input_widget.border_subtitle = f" {compose_clock_notify_contents()[0]} "

        # Expiring / archived-in-context reference, shown only in command mode.
        if self.command_info_panel.refresh_content():
            self.command_info_panel.display = True
        else:
            self.command_info_panel.display = False

    def in_search_mode(self) -> bool:
        return self._search.active

    def on_key(self, event):
        # logging.info(f"KEY: {event.key}")

        if event.key == "enter" or event.key in "0123456789":
            logging.info(
                f"key={event.key} focused={self.focused!r} "
                f"input.display={self.input_widget.display} "
                f"node_being_edited={self._node_being_edited is not None} "
                f"search_matches={len(self._search.matches)}"
            )

        if event.key == "escape" and self.input_widget.display:
            self._node_being_edited = None
            self.reset_history_index()
            self.input_widget.value = ""
            self.input_widget.display = False
            self.command_info_panel.display = False
            self.note_tree_widget.focus()
        elif (
            self.input_widget.display
            and not self._node_being_edited
            and not self._search.active
        ):
            if event.key == "up":
                event.prevent_default()
                event.stop()
                self.history_up()
            elif event.key == "down":
                event.prevent_default()
                event.stop()
                self.history_down()
        elif self._node_being_edited:
            if event.key == "tab":
                self.note_tree_widget.action_indent()
                self.input_widget.focus()
            elif event.key == "shift+tab":
                self.note_tree_widget.action_deindent()
                self.input_widget.focus()
        elif event.key == "enter" and not self.input_widget.display:
            self.note_tree_widget.action_add_note()
        elif event.key in "0123456789":
            bookmark_node = self.note_tree.bookmarks.get(int(event.key))
            self.note_tree_widget.visit_bookmark(int(event.key))
            if bookmark_node:
                self.info_sidebar.update_data()
        else:
            slot = SHIFT_DIGIT_TO_SLOT.get(event.key)
            if slot is None:
                slot = SHIFT_DIGIT_TO_SLOT.get(getattr(event, "character", None))
            if slot is not None:
                logging.info(
                    f"shift-digit: key={event.key!r} char={getattr(event, 'character', None)!r} -> slot {slot}"
                )
                self.note_tree_widget.assign_bookmark(slot)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Run Note Interface")
    parser.add_argument("notes", help="a notes file (.txt)")
    args = parser.parse_args()
    notes_filename = args.notes

    setup_logging(notes_filename)

    app = ForestApp(notes_filename)
    app.run()
