import argparse
import json
import logging
import os
import re
import textwrap
from datetime import datetime

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
from utils import (apply_input_substitutions, extract_path_references,
                   play_sound_effect)
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
        border: $HL1 50%;
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

        self.sound_effects_enabled = self.config.sound_effects_enabled
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
        # Play intro sound
        if self.sound_effects_enabled:
            play_sound_effect("intro")

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

    def _allocate_doodle_id(self) -> int:
        i = self._doodle_next_id
        self._doodle_next_id += 1
        return i

    _MIN_TREE_WIDTH = 50
    _DEFAULT_SIDEBAR_WIDTH = 40

    _DOODLE_WIDTH = 30

    def _apply_layout(self):
        side = self.config.margin_side
        width = self.config.margin_width
        screen_width = self.size.width
        opposite = "left" if side == "right" else "right"
        doodle_visible = (
            getattr(self, "doodle_pane", None) is not None
            and self.doodle_pane.pane_visible
        )
        doodle_w = self._DOODLE_WIDTH if doodle_visible else 0

        if width <= 0 or screen_width - width < self._MIN_TREE_WIDTH:
            sidebar_margin = 0
            sidebar_width = self._DEFAULT_SIDEBAR_WIDTH
        else:
            sidebar_margin = width
            sidebar_width = width

        remaining = screen_width - sidebar_margin - doodle_w
        doodle_margin = doodle_w if remaining >= self._MIN_TREE_WIDTH else 0

        if side == "left":
            self.note_tree_widget.styles.margin = (0, doodle_margin, 0, sidebar_margin)
        else:
            self.note_tree_widget.styles.margin = (0, sidebar_margin, 0, doodle_margin)

        self.info_sidebar.apply_layout(side, sidebar_width)
        self.doodle_pane.apply_layout(opposite, doodle_w)

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

        self.note_tree_widget = NoteTreeWidget(note_tree=self.note_tree, id="note-tree")
        self.note_tree_widget.focus()
        self.info_sidebar = InfoSidebar(id="info-sidebar")
        self.doodle_pane = DoodlePane(id="doodle-pane")

        # Pre-apply margin/visibility so the tree's initial render wraps at
        # the final width, avoiding a visible reflow when on_mount later
        # calls _apply_layout().
        doodle_visible = self.config.doodle_pane_visible
        self.doodle_pane.pane_visible = doodle_visible
        self.doodle_pane.styles.display = "block" if doodle_visible else "none"

        side = self.config.margin_side
        sidebar_margin = self.config.margin_width if self.config.margin_width > 0 else 0
        doodle_margin = self._DOODLE_WIDTH if doodle_visible else 0
        if side == "left":
            self.note_tree_widget.styles.margin = (0, doodle_margin, 0, sidebar_margin)
        else:
            self.note_tree_widget.styles.margin = (0, sidebar_margin, 0, doodle_margin)

        yield self.note_tree_widget
        yield self.info_sidebar
        yield self.doodle_pane

    def get_theme_variable_defaults(self):
        # Return the variables for the current theme
        theme = THEMES.get(self.theme)
        if theme:
            return theme.variables
        return {}

    def update_search_view(self):
        node = self._search.current_node
        self.status_bar.search_progress = (
            self._search.index,
            len(self._search.matches),
        )

        self.note_tree_widget.update_location(context_node=node.parent, line_node=node)
        self.info_sidebar.update_search_highlight(self._search.index)

    def action_edit_note(self):
        # if the input widget already in use, stop
        if self.input_widget.display:
            return

        node = self.note_tree_widget.cursor_node

        if not node:
            return

        label_text = str(node._node.text)
        # Create an Input widget pre-filled with the current label
        self._node_being_edited = node
        # input_widget.id = f"input-{id(node)}"
        self.input_widget.suggester = self.edit_suggester
        self.input_widget.display = True
        self.input_widget.value = label_text
        self.input_widget.placeholder = ""
        self.input_widget.focus()
        self.input_widget.border_title = "Editing..."

    def action_cycle_side_panel(self):
        logging.info("action_cycle_side_panel called")
        self.info_sidebar.cycle_mode()

    def _copied_refresh_sidebar(self) -> None:
        sidebar = getattr(self, "info_sidebar", None)
        if sidebar is None or not sidebar.display or sidebar._search_results:
            return
        sidebar.update_data()

    def copied_toggle(self, node) -> None:
        nodes = self.note_tree.copied_nodes
        if node in nodes:
            nodes.remove(node)
            self.note_tree.remove_bookmark_for(node)
        else:
            nodes.append(node)
        self.note_tree.has_unsaved_operations = True
        self.status_bar.needs_saving = True
        self._copied_refresh_sidebar()

    def _copied_prune(self) -> bool:
        nodes = self.note_tree.copied_nodes
        live_ids = {
            id(n) for n in self.note_tree.root.get_node_list(only_visible=False)
        }
        nodes[:] = [n for n in nodes if id(n) in live_ids]
        return bool(nodes)

    def _copied_rotate(self) -> None:
        # Only rotate the non-bookmarked tail; bookmarked nodes stay pinned
        # at the start of the list (= bottom of sidebar) in their order.
        nodes = self.note_tree.copied_nodes
        k = self.note_tree.bookmark_split_index()
        tail = nodes[k:]
        if len(tail) <= 1:
            return
        nodes[k:] = [tail[-1]] + tail[:-1]
        self.note_tree.has_unsaved_operations = True
        self.status_bar.needs_saving = True

    def copied_jump_to_next(self) -> None:
        if not self.note_tree.copied_nodes:
            self.notify("No copied notes.")
            return
        if not self._copied_prune():
            self._copied_refresh_sidebar()
            return
        target = self.note_tree.copied_nodes[-1]
        self._copied_rotate()
        self.note_tree_widget.update_location(
            context_node=target.parent if target.parent else target,
            line_node=target,
        )
        self._copied_refresh_sidebar()

    def copied_cycle_target(self) -> None:
        if not self.note_tree.copied_nodes:
            self.notify("No copied notes.")
            return
        if not self._copied_prune():
            self._copied_refresh_sidebar()
            return
        self._copied_rotate()
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

    def _cmd_journal(self, cmd_str):
        text = cmd_str[3:]
        self.note_tree.push_undo(self.note_tree.root)
        self.note_tree_widget.add_journal_entry(text)

    def _cmd_search(self, cmd_str):
        global_scope = cmd_str.startswith("?*") or cmd_str.startswith("??")
        query = cmd_str[2:].strip() if global_scope else cmd_str[1:].strip()
        query = query.replace(" › ", ">").replace(" > ", ">")

        if not query:
            cursor_node = self.note_tree_widget.cursor_node
            if not cursor_node:
                self.notify("No note selected.")
                return
            results = self.note_tree.find_by_similarity(cursor_node._node)
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
        try:
            cursor_node_obj = self.note_tree_widget.cursor_node._node
        except AttributeError:
            cursor_node_obj = None
        self._search.pre_search_position = (
            self.note_tree.context_node,
            cursor_node_obj,
        )
        self.info_sidebar.show_search_results(matching_nodes, display_query)
        self.update_search_view()

    def _cmd_help(self, cmd_str):
        self.info_sidebar.show_help()

    def _cmd_doodle(self, cmd_str):
        sub = cmd_str[len("doodle ") :].strip()
        if sub == "clear":
            self.doodle_pane.clear_current()
        elif sub == "show":
            self.doodle_pane.set_visible(True)
        elif sub == "hide":
            self.doodle_pane.set_visible(False)

    def _cmd_run(self, cmd_str):
        parts = cmd_str.split(maxsplit=1)
        index = 0
        if len(parts) > 1:
            try:
                index = int(parts[1])
            except ValueError:
                self.notify("Usage: :run or :run <index>")
                return
        if not self.note_tree_widget.cursor_node:
            self.notify("No note selected")
            return
        node = self.note_tree_widget.cursor_node._node
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

    def _cmd_collapse(self, cmd_str):
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

    def _cmd_insert(self, cmd_str):
        subtree_name = cmd_str.split(" ", 1)[-1]
        self.note_tree_widget.add_subtree(subtree_name)

    def _cmd_random(self, cmd_str):
        self.note_tree_widget.jump_to_random(global_scope=cmd_str == "random*")

    def _cmd_timer_cancel(self, cmd_str):
        self.timer.cancel()

    def _cmd_timer(self, cmd_str):
        self.timer.start(cmd_str[6:].strip())

    def _cmd_sticky(self, cmd_str):
        global_scope = cmd_str.startswith("sn*")
        if global_scope:
            filter_arg = cmd_str[3:].strip()
            scope_root = self.note_tree.root
        else:
            filter_arg = cmd_str[2:].strip()
            scope_root = self.note_tree.context_node
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

    def _cmd_snr(self, cmd_str):
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

    def _cmd_archive(self, cmd_str):
        parts = cmd_str.split(None, 1)
        sub = parts[1].strip() if len(parts) > 1 else ""
        if sub == "set":
            node = self.note_tree_widget.cursor_node._node
            if self._toggle_archive_tag(node, add=True) and self.note_tree.hide_archive:
                self.note_tree_widget.move_cursor_to_line(0)
        elif sub == "unset":
            self._toggle_archive_tag(self.note_tree_widget.cursor_node._node, add=False)
        elif sub == "show":
            self.note_tree.hide_archive = False
            self.status_bar.hide_archive = False
            self.note_tree.update_visible_node_list()
            self.note_tree_widget.render()
        elif sub == "hide":
            self.note_tree.hide_archive = True
            self.status_bar.hide_archive = True
            cursor = self.note_tree_widget.cursor_node
            cursor_node = cursor._node if cursor else None
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

    def _dispatch_command(self, cmd_str):
        # Order matters: longer/more specific prefixes before shorter ones.
        handlers = (
            (lambda c: c.startswith("j+ "), self._cmd_journal),
            (lambda c: c.startswith("?"), self._cmd_search),
            (lambda c: c == "help", self._cmd_help),
            (lambda c: c.startswith("doodle "), self._cmd_doodle),
            (lambda c: c == "run" or c.startswith("run "), self._cmd_run),
            (lambda c: c == "collapse", self._cmd_collapse),
            (lambda c: c.startswith("insert "), self._cmd_insert),
            (lambda c: c in ("random", "random*"), self._cmd_random),
            (lambda c: c == "timer cancel", self._cmd_timer_cancel),
            (lambda c: c.startswith("timer "), self._cmd_timer),
            (
                lambda c: c == "sn" or c.startswith("sn ") or c.startswith("sn*"),
                self._cmd_sticky,
            ),
            (lambda c: c == "snr", self._cmd_snr),
            (lambda c: c == "archive" or c.startswith("archive "), self._cmd_archive),
        )
        for matches, handler in handlers:
            if matches(cmd_str):
                handler(cmd_str)
                return

    def on_input_submitted(self, event):
        logging.info(f"INPUT SUBMITTED: {event}")
        if self._node_being_edited:
            new_text = event.value.strip()
            if new_text:
                new_text = apply_input_substitutions(new_text)
                node = self._node_being_edited._node
                self.note_tree.push_undo(node.parent)
                node.text = new_text
                node.post_text_update()
                self.note_tree.has_unsaved_operations = True
                self.note_tree_widget.render()
                self.note_tree_widget._fix_cursor_position(node)
            self._node_being_edited = None
        else:
            cmd_str = event.value.strip()
            self.record_command(cmd_str)
            self._dispatch_command(cmd_str)

        self.input_widget.value = ""
        self.input_widget.display = False
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
        elif self._search.active:
            if event.key == "up":
                event.prevent_default()
                event.stop()
                self._search.cycle(-1)
                self.update_search_view()
            elif event.key == "down":
                event.prevent_default()
                event.stop()
                self._search.cycle(1)
                self.update_search_view()
            elif event.key == "c":
                event.prevent_default()
                event.stop()
                node = self._search.current_node
                if node is not None and node.parent is not None:
                    self.copied_toggle(node)
                    self.info_sidebar.update_search_highlight(self._search.index)
                    self.note_tree_widget.render()
            elif event.key in ["enter", "escape"]:
                self.status_bar.search_mode = False
                if event.key == "escape":
                    self.note_tree_widget.update_location(
                        context_node=self._search.pre_search_position[0],
                        line_node=self._search.pre_search_position[1],
                    )
                self._search.clear()
                self.info_sidebar.hide_search_results()
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
