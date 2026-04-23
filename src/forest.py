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
from copied_list import CopiedList
from node import Node
from note_tree import NoteTree
from note_tree_widget import NoteTreeWidget
from search_state import SearchState
from sticky_notes import StickyNotesScreen, _parse_flashcard
from themes import THEMES
from timer import Timer
from utils import apply_input_substitutions, extract_path_references, play_sound_effect
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
        self.copied_list = CopiedList(self)
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

                self._node_being_edited = None
                self.input_widget.value = ""
                self.input_widget.display = False

                self.note_tree_widget.render()
            else:
                self._node_being_edited = None
                self.input_widget.value = ""
                self.input_widget.display = False
                self.note_tree_widget.focus()

        else:
            # we're in command mode
            cmd_str = event.value.strip()
            self.record_command(cmd_str)
            if cmd_str.startswith("j+ "):
                text = cmd_str[3:]
                self.note_tree.push_undo(self.note_tree.root)
                self.note_tree_widget.add_journal_entry(text)
            elif cmd_str.startswith("?"):
                global_scope = False
                if cmd_str.startswith("?*") or cmd_str.startswith("??"):
                    global_scope = True
                    query = cmd_str[2:].strip()
                else:
                    query = cmd_str[1:].strip()

                # Normalize path separators (handle both " › " and " > ")
                query = query.replace(" › ", ">").replace(" > ", ">")

                # Empty query: find similar notes
                if not query:
                    cursor_node = self.note_tree_widget.cursor_node
                    if not cursor_node:
                        self.notify("No note selected.")
                        self.input_widget.value = ""
                        self.input_widget.display = False
                        self.note_tree_widget.focus()
                        return
                    node = cursor_node._node
                    results = self.note_tree.find_by_similarity(node)
                    results = [
                        (n, sim, d, ctx) for n, sim, d, ctx in results if sim >= 0.10
                    ]
                    if not global_scope:
                        results = [
                            (n, sim, d, ctx) for n, sim, d, ctx in results if ctx
                        ]
                    matching_nodes = [n for n, sim, d, ctx in results]
                    display_query = ""
                else:
                    # Enable path matching if query contains ">"
                    match_path = ">" in query
                    matching_nodes = self.note_tree.find_by_query(
                        query,
                        global_scope=global_scope,
                        match_path=match_path,
                        threshold=0.1,
                    )[:20]
                    display_query = query

                if not matching_nodes:
                    self.notify("No search results found.")
                    self.input_widget.value = ""
                    self.input_widget.display = False
                    self.note_tree_widget.focus()
                    return

                self._search.query = query
                self._search.context_node = self.note_tree.context_node
                self._search.is_local = not global_scope
                self._search.matches = matching_nodes
                self.status_bar.search_mode = True
                try:
                    self._search.pre_search_position = (
                        self.note_tree.context_node,
                        self.note_tree_widget.cursor_node._node,
                    )
                except AttributeError:
                    self._search.pre_search_position = (
                        self.note_tree.context_node,
                        None,
                    )
                self.info_sidebar.show_search_results(matching_nodes, display_query)
                self.update_search_view()

            elif cmd_str == "help":
                self.info_sidebar.show_help()
            elif cmd_str == "doodle clear":
                self.doodle_pane.clear_current()
            elif cmd_str == "doodle show":
                self.doodle_pane.set_visible(True)
            elif cmd_str == "doodle hide":
                self.doodle_pane.set_visible(False)
            elif cmd_str == "run" or cmd_str.startswith("run "):
                parts = cmd_str.split(maxsplit=1)
                index = 0
                if len(parts) > 1:
                    try:
                        index = int(parts[1])
                    except ValueError:
                        self.notify("Usage: :run or :run <index>")
                        self.input_widget.value = ""
                        self.input_widget.display = False
                        self.note_tree_widget.focus()
                        return

                if not self.note_tree_widget.cursor_node:
                    self.notify("No note selected")
                else:
                    node = self.note_tree_widget.cursor_node._node
                    if node.text.startswith("!"):
                        try:
                            logging.info("Running command")
                            node.run_command()
                        except Exception as e:
                            logging.error(f"Could not run command: {e}")
                    else:
                        paths = extract_path_references(node.text)
                        if paths:
                            if index >= len(paths):
                                self.notify(
                                    f"Index {index} out of range (found {len(paths)} path(s))"
                                )
                            else:
                                path_query = paths[index]
                                path_query = path_query.replace(" › ", ">").replace(
                                    " > ", ">"
                                )
                                matching_nodes = self.note_tree.find_by_path_beam(
                                    path_query
                                )
                                if matching_nodes:
                                    target_node = matching_nodes[0]
                                    self.note_tree_widget.update_location(
                                        context_node=(
                                            target_node.parent
                                            if target_node.parent
                                            else target_node
                                        ),
                                        line_node=target_node,
                                    )
                                else:
                                    self.notify(f"No path match for: {path_query}")
                        else:
                            self.notify("No ! command or [[path]] reference found")
            elif cmd_str == "collapse":
                ctx = self.note_tree.context_node
                descendants = ctx.get_node_list(
                    only_visible=False,
                    hide_done=False,
                    hide_archive=self.note_tree.hide_archive,
                )[1:]
                if any(n.children for n in descendants):
                    self.note_tree.push_undo(ctx)
                    for n in descendants:
                        if n.children:
                            n.is_collapsed = True
                    self.note_tree.update_visible_node_list()
                    self.note_tree.has_unsaved_operations = True
                    self.note_tree_widget.render()
            elif cmd_str.startswith("insert "):
                subtree_name = cmd_str.split(" ", 1)[-1]
                self.note_tree_widget.add_subtree(subtree_name)
            elif cmd_str in ("random", "random*"):
                global_scope = cmd_str == "random*"
                self.note_tree_widget.jump_to_random(global_scope=global_scope)
            elif cmd_str == "timer cancel":
                self.timer.cancel()
            elif cmd_str.startswith("timer "):
                duration_str = cmd_str[6:].strip()
                self.timer.start(duration_str)
            elif (
                cmd_str.startswith("sn*")
                or cmd_str == "sn"
                or cmd_str.startswith("sn ")
            ):
                if cmd_str.startswith("sn*"):
                    filter_arg = cmd_str[3:].strip()
                    all_nodes = self.note_tree.root.get_node_list(
                        only_visible=False,
                        hide_done=True,
                        hide_archive=self.note_tree.hide_archive,
                    )
                else:
                    filter_arg = cmd_str[2:].strip()
                    all_nodes = self.note_tree.context_node.get_node_list(
                        only_visible=False,
                        hide_done=True,
                        hide_archive=self.note_tree.hide_archive,
                    )
                # Skip the root node and the context node itself
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

                # Filter out first-child answer nodes of child-answer flashcards
                answer_ids = set()
                for n in matched:
                    fc = _parse_flashcard(n)
                    if fc and fc[2] and n.children:  # fc[2] = is_child_answer
                        answer_ids.add(id(n.children[0]))
                matched = [n for n in matched if id(n) not in answer_ids]

                if not matched:
                    self.notify("No matching notes found.")
                else:
                    hl_colors = {
                        0: self.theme_variables.get("HL1", "#039ad7"),
                        1: self.theme_variables.get("HL2", "#dca708"),
                        2: self.theme_variables.get("HL3", "#c44f1f"),
                    }
                    self._sticky_note_state = {
                        "nodes": matched,
                        "title": title,
                        "hl_colors": hl_colors,
                        "cursor_index": 0,
                    }
                    self.status_bar.has_sticky_recovery = True
                    screen = StickyNotesScreen(
                        matched, title_text=title, hl_colors=hl_colors
                    )

                    def on_dismiss(node):
                        self._sticky_note_state["cursor_index"] = screen._cursor_index
                        if node is not None:
                            self.note_tree_widget.update_location(
                                context_node=node.parent if node.parent else node,
                                line_node=node,
                            )

                    self.push_screen(screen, callback=on_dismiss)
            elif cmd_str == "snr":
                if self._sticky_note_state:
                    state = self._sticky_note_state
                    all_tree_nodes = set(
                        id(n)
                        for n in self.note_tree.root.get_node_list(
                            only_visible=False,
                            hide_done=False,
                            hide_archive=self.note_tree.hide_archive,
                        )
                    )
                    valid_nodes = [
                        n
                        for n in state["nodes"]
                        if id(n) in all_tree_nodes and not n.is_done()
                    ]
                    # Filter out first-child answer nodes of child-answer flashcards
                    answer_ids = set()
                    for n in valid_nodes:
                        fc = _parse_flashcard(n)
                        if fc and fc[2] and n.children:  # fc[2] = is_child_answer
                            answer_ids.add(id(n.children[0]))
                    valid_nodes = [n for n in valid_nodes if id(n) not in answer_ids]
                    if not valid_nodes:
                        self.notify("All notes from that board have been removed.")
                        self._sticky_note_state = None
                        self.status_bar.has_sticky_recovery = False
                    else:
                        screen = StickyNotesScreen(
                            valid_nodes,
                            title_text=state["title"],
                            hl_colors=state["hl_colors"],
                        )
                        screen._cursor_index = min(
                            state["cursor_index"], len(valid_nodes) - 1
                        )

                        def on_dismiss(node):
                            self._sticky_note_state["cursor_index"] = (
                                screen._cursor_index
                            )
                            self._sticky_note_state["nodes"] = valid_nodes
                            if node is not None:
                                self.note_tree_widget.update_location(
                                    context_node=node.parent if node.parent else node,
                                    line_node=node,
                                )

                        self.push_screen(screen, callback=on_dismiss)
                else:
                    self.notify("No sticky note board to recover.")
            elif cmd_str == "archive" or cmd_str.startswith("archive "):
                parts = cmd_str.split(None, 1)
                sub = parts[1].strip() if len(parts) > 1 else ""
                if sub == "set":
                    node = self.note_tree_widget.cursor_node._node
                    if "#ARCHIVE" not in node.text:
                        self.note_tree.push_undo(node.parent or node)
                        words = node.text.split()
                        words.append("#ARCHIVE")
                        node.text = " ".join(words)
                        node.post_text_update()
                        self.note_tree.has_unsaved_operations = True
                        self.note_tree.update_visible_node_list()
                        self.note_tree_widget.render()
                        if self.note_tree.hide_archive:
                            self.note_tree_widget.move_cursor_to_line(0)
                elif sub == "unset":
                    node = self.note_tree_widget.cursor_node._node
                    if "#ARCHIVE" in node.text:
                        self.note_tree.push_undo(node.parent or node)
                        words = [w for w in node.text.split() if w != "#ARCHIVE"]
                        node.text = " ".join(words)
                        node.post_text_update()
                        self.note_tree.has_unsaved_operations = True
                        self.note_tree.update_visible_node_list()
                        self.note_tree_widget.render()
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

                if sub in ("set", "unset", "show", "hide"):
                    self.info_sidebar.update_data()

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
                    self.copied_list.toggle(node)
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
