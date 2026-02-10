import argparse
import json
import logging
import os
import re
import textwrap
from datetime import datetime

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Gradient
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.suggester import Suggester, SuggestFromList
from textual.theme import Theme
from textual.widgets import (DataTable, Footer, Input, Markdown, ProgressBar,
                             Static, Tree)

from config import Config
from node import Node
from note_tree import NoteTree
from note_tree_widget import NoteTreeWidget
from subtrees import SUBTREES
from themes import THEMES
from timer import Timer
from utils import (apply_input_substitutions, compose_clock_notify_contents,
                   determine_state_filename, play_sound_effect)

# ============================================================================
# CONFIGURATION
# ============================================================================
# Load configuration from config.json
config = Config()

LOG_FILE = "log.txt"

# Configure logging from config
log_level = getattr(logging, config.log_level.upper(), logging.INFO)
logging.basicConfig(
    filename=LOG_FILE,
    level=log_level,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode="w",
    force=True,
)
logging.info("Application started")


class StatusBar(Static):
    progress = reactive((0, 0))
    context_node = reactive(None)
    needs_saving = reactive(False)
    hide_done = reactive(False)
    search_mode = reactive(False)
    search_progress = reactive((0, 0))
    timer_remaining = reactive(None)

    def compose_content(self):

        hl = self.app.theme_variables["secondary"]
        progress_text = Text.from_markup(
            f" [{hl}][{self.progress[0]}/{self.progress[1]}][/{hl}]"
        )

        if self.hide_done:
            hide_done_text = Text.from_markup(f" [{hl}]Ⓧ[/{hl}]")
        else:
            hide_done_text = Text.from_markup("")

        if not self.needs_saving:
            needs_saving_text = Text("")
        else:
            hl = self.app.get_theme_variable_defaults().get("HL2") or "yellow"
            needs_saving_text = Text.from_markup(f" [{hl}]\\[S]AVE[/{hl}] ")

        # Timer display
        if self.timer_remaining is not None:
            hl = self.app.get_theme_variable_defaults().get("HL3") or "red"
            timer_text = Text.from_markup(f" [{hl}]{self.timer_remaining}[/{hl}] ")
        else:
            timer_text = Text("")

        if self.search_mode:
            hl = self.app.theme_variables["HL3"]
            # hl = self.app.theme_variables["panel-HL"]
            # logging.info(self.app.theme_variables)

            text = Text.from_markup(
                "🌲 "
                + f"[{hl}][b]Search result {self.search_progress[0]+1}/{self.search_progress[1]}[/b][/{hl}] | "
            )
            remaining_width = self.size.width - len(text.plain) - 1

            context_path = self.context_node.get_path_string(width=remaining_width)

            text = text + Text.from_markup(context_path)
        else:
            start_text = Text.from_markup("🌲 ")

            end_text = timer_text + needs_saving_text + hide_done_text + progress_text

            remaining_width = max(
                0,
                self.size.width - len(start_text.plain) - len(end_text.plain) - 1,
            )
            path_text = ""
            if self.context_node:
                path_text = self.context_node.get_path_string(width=remaining_width)
            path_text += " " * max(0, remaining_width - len(path_text))
            text = start_text + Text.from_markup(path_text) + end_text

        self.update(content=text)

    def watch_progress(self, new_value):
        self.compose_content()

    def watch_hide_done(self, new_value):
        self.compose_content()

    def watch_context_node(self, new_value):
        self.compose_content()

    def watch_needs_saving(self, new_value):
        self.compose_content()

    def watch_search_mode(self, new_value):
        self.compose_content()

    def watch_search_progress(self, new_value):
        self.compose_content()

    def watch_timer_remaining(self, new_value):
        self.compose_content()

    def on_resize(self, event) -> None:
        self.compose_content()


class InfoWidget(DataTable):
    mode_index = 0
    mode_options = [None, "bookmarks", "perpetual_journal"]

    def cycle_mode(self):
        old_index = self.mode_index
        self.mode_index = (self.mode_index + 1) % len(self.mode_options)
        logging.info(
            f"cycle_mode: {old_index} -> {self.mode_index}, mode = {self.mode_options[self.mode_index]}"
        )
        self.update_data()

    def show_help(self):
        """Display help information without adding to the cycle."""
        logging.info("show_help called")
        # Set mode_index to last position so next cycle wraps to 0 (None/hidden)
        self.mode_index = len(self.mode_options) - 1
        self.display = True
        self.show_header = False

        table_rows = [
            ["", Text.from_markup("[white][b]Forest Help[/b][/white]")],
            ["", Text.from_markup("[dim](Press ` to hide)[/dim]")],
            ["", ""],
            ["", Text.from_markup("[b]Navigation[/b]")],
            ["←/→", "Zoom out/in"],
            ["space", "Toggle collapse"],
            ["0-9", "Jump to bookmark"],
            ["", ""],
            ["", Text.from_markup("[b]Editing[/b]")],
            ["e/bksp", "Edit note"],
            ["enter", "Add new note"],
            ["delete", "Delete note"],
            ["u/d", "Move note up/down"],
            ["tab/S-tab", "Indent/deindent"],
            ["h", "Cycle highlight"],
            ["x", "Toggle #DONE"],
            ["X", "Toggle hiding #DONE notes"],
            ["z/Z", "Undo/redo"],
            ["", ""],
            ["", Text.from_markup("[b]Commands[/b]")],
            [":", "Command mode"],
            [":b or :bookmark", "Toggle bookmark"],
            [":sound", "Toggle sound effects"],
            [":j+ <text>", "Add journal entry"],
            [":<path hint>+ <text>", "Add entry to best path"],
            ["", "(e.g. 'Places>LA+ bla')"],
            [":?<query>", "Search in context"],
            [":??<query>", "Search globally"],
            [":insert <name>", "Insert template"],
            [":run", "Run shell command"],
            [":help", "Show this help"],
            ["", ""],
            ["", Text.from_markup("[b]Other[/b]")],
            ["s", "Save"],
            ["`", "Cycle side panel"],
        ]

        self.clear(columns=True)
        self.add_columns("", "")
        self.add_rows(table_rows)
        self.refresh()

    def update_data(self):

        mode = self.mode_options[self.mode_index]
        logging.info(f"update_data: mode = {mode}")
        if mode is None:
            logging.info("update_data: hiding widget")
            self.clear(columns=True)
            self.display = False
            self.refresh()
            return

        logging.info(f"update_data: showing widget, display = True")
        self.display = True

        width = min(self.app.size.width // 2, 60)
        # logging.info(f"Updating info widget with size: {self.size}")

        if mode == "bookmarks":
            logging.info("update_data: building bookmarks table")
            self.show_header = False

            table_rows = [
                ["", Text.from_markup("[white][b]Bookmarks[/b][/white]")],
                ["", ""],
                ["Key", "Note"],
            ]

            nb_bookmarks = 10
            for index in range(nb_bookmarks):
                node = self.app.note_tree.bookmarks.get(index)
                text = node.text if node else ""
                table_rows.append([index, text])
            self.clear(columns=True)
            self.add_columns("", "")
            self.add_rows(table_rows)  # [1:])
            logging.info(
                f"update_data: bookmarks table built with {len(table_rows)} rows, calling refresh()"
            )
            self.refresh()

        elif mode == "perpetual_journal":
            logging.info("update_data: building perpetual_journal table")
            self.show_header = False

            # ON THIS DAY
            # get the current ymd
            month_day = datetime.now().strftime("%m-%d")
            date_regex = r"\[(\d{4}-" + month_day + r").*\]"
            # date_regex = r"\[(\d{4}-04-12).*\]"
            logging.info(f"Searching for regex: {date_regex}")
            node_matches = self.app.note_tree.get_entries_matching_regex(
                date_regex, group_index=1
            )
            logging.info(f"Found matches: {node_matches}")

            table_rows = [
                ["", Text.from_markup("[white][b]On This Day[/b][/white]")],
                ["", ""],
                ["Date", "Entry"],
            ]
            for node, match_str in node_matches:
                text = node.text if node else ""
                text = re.sub(date_regex, "", text).strip()
                lines = textwrap.wrap(text, width - 16)
                for i_l, line in enumerate(lines):
                    table_rows.append([match_str if i_l == 0 else "", line])

            # ON THIS MONTH
            # get the current ymd
            month = datetime.now().strftime("%m")
            date_regex = r"\[(\d{4}-" + month + r"-\d{2}).*\]"
            # date_regex = r"\[(\d{4}-04-12).*\]"
            logging.info(f"Searching for regex: {date_regex}")
            node_matches = self.app.note_tree.get_entries_matching_regex(
                date_regex, group_index=1
            )
            logging.info(f"Found matches: {node_matches}")

            table_rows.extend(
                [
                    ["", ""],
                    [
                        "",
                        Text.from_markup("[white][b]In This Month[/b][/white]"),
                    ],
                    ["", ""],
                    ["Date", "Entry"],
                ]
            )
            for node, match_str in node_matches:
                text = node.text if node else ""
                text = re.sub(date_regex, "", text).strip()
                lines = textwrap.wrap(text, width - 16)
                for i_l, line in enumerate(lines):
                    table_rows.append([match_str if i_l == 0 else "", line])

            self.clear(columns=True)
            self.add_columns("", "")  # *table_rows[0])
            self.add_rows(table_rows)  # [1:])
            logging.info(
                f"update_data: perpetual_journal table built with {len(table_rows)} rows, calling refresh()"
            )
            self.refresh()


class MultiPurposeSuggester(Suggester):

    def __init__(self, mode="command"):
        super().__init__()
        self.mode = mode  # "command" or "edit"
        if self.mode == "command":
            self.placeholder = "help | bookmark | sound | clock | run | timer <duration> | insert <name> | j+ <text> | ?<query> | ??<query> | <path hint>+ <text>"
        else:
            self.placeholder = ""

    async def get_suggestion(self, value: None | str) -> None | str:

        if self.mode == "edit":
            # Suggestions for editing notes
            if not value:
                return None

            # Suggest hashtags
            if value.endswith("#"):
                return value + "WELL | #T- | #sum | #max | #min | #avg"

            # Suggest value syntax
            if value.endswith("$"):
                return (
                    value + "variable=value | $variable_inc=value | $variable_dec=value"
                )

            return None

        # Command mode suggestions
        if not value:
            # Show all available commands with syntax hints
            return self.placeholder

        # Smart auto-completion for partial commands
        value_lower = value.lower()

        if "help".startswith(value_lower):
            return "help"

        if "bookmark".startswith(value_lower):
            return "bookmark"

        if "run".startswith(value_lower):
            return "run"

        if "clock".startswith(value_lower):
            return "clock"

        if "sound".startswith(value_lower):
            return "sound"

        if "timer".startswith(value_lower):
            return "timer <duration> | timer cancel"

        if value_lower == "j":
            return "j+ <text>"

        if value_lower == "j+":
            return "j+ <text>"

        if value in ["?", "??"]:
            return value + "<query>"

        # Show example durations when user types "timer "
        if value == "timer ":
            return "timer 5m | 25m | 1h | 5m 3x | cancel"

        if value == "timer c":
            return "timer cancel"

        # Show and filter subtree options when user types "insert"
        if value.startswith("insert"):
            if value == "insert":
                return "insert <name>"
            elif value == "insert ":
                subtree_names = " | ".join(sorted(SUBTREES.keys()))
                return "insert " + subtree_names
            else:
                # Filter subtrees based on what's been typed
                partial = value[7:].upper()  # Get text after "insert "
                matching = [
                    name for name in SUBTREES.keys() if name.startswith(partial)
                ]
                if matching:
                    if len(matching) == 1:
                        return "insert " + matching[0]
                    else:
                        return "insert " + " | ".join(sorted(matching))

        return None


class ForestApp(App):
    # CSS_PATH = "forest.tcss"
    CSS = """
    Screen {
        layers: base overlay;
    }

    #input-box {
        display: none; /* Initially hidden */
        layer: overlay;
        offset: 0 1;
        border: $secondary 75%;
        background: $background;
    }
    ScrollView {
        scrollbar-size: 0 0;  /* Hides the scrollbar */
    }

    #status-bar {
        background: $panel;
        color: $foreground 90%;
    }

    #info-widget {
        width: 30%;
        height: 100%;
        background-tint: $panel 50%;
        display: none;
        layer: overlay;
        dock: right;
        offset: 0 1;
    }

    Tree {
        &:focus {
            background-tint: $foreground 0%;
        }
        & > .tree--cursor {
            color: blue;
        }
        & > .tree--highlight-line {  /* what lines look like when the MOUSE hovers */
            background: $foreground 10%;
        }
        & > .tree--guides-selected {
            color: transparent;
        }
    }
    """

    BINDINGS = [
        Binding("e,backspace", "edit_note()", "Edit note", show=True),
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

        self.note_tree = NoteTree(self.file_path, undo_depth=self.config.undo_depth)
        self._node_being_edited = None
        self._search_matches = []
        self._search_index = 0
        self._pre_search_position = (None, None)

        self.sound_effects_enabled = self.config.sound_effects_enabled
        self.timer = Timer(self)

        self.logging = logging

    def on_mount(self):
        # Play intro sound
        if self.sound_effects_enabled:
            play_sound_effect("intro")

        if self.config.auto_save and self.config.auto_save_interval > 0:
            self.set_interval(self.config.auto_save_interval, self._auto_save)

        # self.notify("It's an older code, sir, but it checks out.")

    def _auto_save(self):
        if self.note_tree.has_unsaved_operations:
            self.note_tree.save()
            self.status_bar.needs_saving = False

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        # self.screen.styles.text_wrap = "wrap" # Enable word wrapping on the screen.

        logging.info(f"COMPOSING APP. SIZE: {self.size}")

        # self.header = Header(id="header")
        # self.header.icon = "🌲"
        self.status_bar = StatusBar(id="status-bar")
        yield self.status_bar

        self.command_suggester = MultiPurposeSuggester(mode="command")
        self.edit_suggester = MultiPurposeSuggester(mode="edit")
        self.input_widget = Input(id="input-box", suggester=self.command_suggester)
        yield self.input_widget

        self.note_tree_widget = NoteTreeWidget(note_tree=self.note_tree, id="note-tree")
        self.note_tree_widget.focus()
        # self.note_tree_widget.move_cursor_to_line(0)

        self.info_widget = InfoWidget(id="info-widget")
        # yield Horizontal(self.note_tree_widget, self.info_widget)
        yield self.note_tree_widget
        yield self.info_widget

        # self.progress_bar = ProgressBar(total=100, gradient=gradient, id="progress-bar")
        # self.progress_bar.show_eta = False
        # yield self.progress_bar

        # yield Footer()

    def get_theme_variable_defaults(self):
        # Return the variables for the current theme
        theme = THEMES.get(self.theme)
        if theme:
            return theme.variables
        return {}

        # start_file_watcher(self.file_path, self.load_file_data)  # Start file watcher

    def update_search_view(self):
        self._search_index = self._search_index % len(self._search_matches)
        node = self._search_matches[self._search_index]
        self.status_bar.search_progress = (
            self._search_index,
            len(self._search_matches),
        )

        self.note_tree_widget.update_location(context_node=node.parent, line_node=node)

    def action_edit_note(self):
        # if the input widget already in use, stop
        if self.input_widget.display:
            return

        node = self.note_tree_widget.cursor_node

        if not node:
            return

        # TODO: how to figure out visual position of a node? Only works if no scrolling needed
        # self.input_widget.offset = (0, node._line)

        label_text = str(node._node.text)
        # Create an Input widget pre-filled with the current label
        self._node_being_edited = node
        # input_widget.id = f"input-{id(node)}"
        self.input_widget.suggester = self.edit_suggester
        self.input_widget.display = True
        self.input_widget.value = label_text
        self.input_widget.placeholder = ""
        self.input_widget.focus()
        self.input_widget.border_title = "Edit note"

    def action_cycle_side_panel(self):
        logging.info("action_cycle_side_panel called")
        self.info_widget.cycle_mode()

    def on_input_submitted(self, event):
        logging.info(f"INPUT SUBMITTED: {event}")
        if self._node_being_edited:
            new_text = event.value.strip()
            if new_text:
                new_text = apply_input_substitutions(new_text)

                self.note_tree.push_undo(self._node_being_edited._node.parent)
                self._node_being_edited._node.text = new_text  # set_label(new_label)
                self._node_being_edited._node.post_text_update()
                self.note_tree.has_unsaved_operations = True
                self._node_being_edited = None

                # input_widget.remove()
                # self.input_widget.clear()
                # self.input_widget.display = False

                self.note_tree_widget.render()
                # self.note_tree_widget.focus()
            else:
                # TODO:
                self.input_widget.display = False
                self.input_widget.value = ""
                self.note_tree_widget.focus()

        else:
            # we're in command mode
            cmd_str = event.value.strip()
            if cmd_str.startswith("j+ "):
                text = cmd_str[3:]
                self.note_tree.push_undo(self.note_tree.root)
                self.note_tree_widget.add_journal_entry(text)
            elif cmd_str.startswith("?"):
                global_scope = False
                if cmd_str.startswith("??"):
                    global_scope = True
                query = cmd_str.lstrip("? ")
                matching_nodes = self.note_tree.find_matches(
                    query, global_scope=global_scope
                )

                self._search_matches = matching_nodes
                self.status_bar.search_mode = True
                try:
                    self._pre_search_position = (
                        self.note_tree.context_node,
                        self.note_tree_widget.cursor_node._node,
                    )
                except AttributeError:
                    self._pre_search_position = (
                        self.note_tree.context_node,
                        None,
                    )
                self.update_search_view()

            elif cmd_str in ["b", "bookmark"]:
                self.note_tree_widget.toggle_bookmark()
            elif cmd_str == "sound":
                self.sound_effects_enabled = not self.sound_effects_enabled
                status = "enabled" if self.sound_effects_enabled else "disabled"
                self.notify(f"Sound effects {status}")
            elif cmd_str == "help":
                self.info_widget.show_help()
            elif cmd_str in ["run"]:
                try:
                    logging.info("Running command")
                    self.note_tree_widget.cursor_node._node.run_command()
                except Exception as e:
                    logging.error(f"Could not run command: {e}")
            elif cmd_str.startswith("insert "):
                subtree_name = cmd_str.split(" ", 1)[-1]
                self.note_tree_widget.add_subtree(subtree_name)
            elif cmd_str == "clock":
                title, body = compose_clock_notify_contents(self.config.location)
                self.notify(body, title=title)
            elif cmd_str == "timer cancel":
                self.timer.cancel()
            elif cmd_str.startswith("timer "):
                duration_str = cmd_str[6:].strip()
                self.timer.start(duration_str)
            elif "+ " in cmd_str:
                # Quick add: <location hint>+ <note text>
                plus_idx = cmd_str.index("+ ")
                hint_str = cmd_str[:plus_idx].strip()
                note_text = cmd_str[plus_idx + 2 :].strip()

                if hint_str and note_text:
                    matching_nodes = self.note_tree.find_matches(
                        hint_str, global_scope=True, match_path=True
                    )
                    if matching_nodes:
                        target_node = matching_nodes[0]
                        self.note_tree.push_undo(target_node)
                        note_text = apply_input_substitutions(note_text)
                        new_node = target_node.add_child(note_text)
                        self.note_tree.index_nodes()
                        self.note_tree.update_visible_node_list()
                        self.note_tree.has_unsaved_operations = True

                        # self.note_tree_widget.update_location(
                        #     context_node=target_node, line_node=new_node
                        # )
                        path_str = target_node.get_path_string(width=100)
                        self.notify(f"Added to: {path_str}")
                    else:
                        self.notify("No matching node found")

        self.input_widget.clear()
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
        return bool(self._search_matches)

    def on_key(self, event):
        # logging.info(f"KEY: {event.key}")
        # logging.info(f"Info widget with size: {self.info_widget.size}")

        if event.key == "escape" and self.input_widget.display:
            self.input_widget.display = False
            self.input_widget.value = ""
            self.note_tree_widget.focus()
        elif self._node_being_edited:
            if event.key == "tab":
                self.note_tree_widget.action_indent()
                self.input_widget.focus()
            elif event.key == "shift+tab":
                self.note_tree_widget.action_deindent()
                self.input_widget.focus()
        elif self._search_matches:
            if event.key == "left":
                self._search_index -= 1
                self.update_search_view()
            elif event.key == "right":
                self._search_index += 1
                self.update_search_view()
            elif event.key in ["enter", "escape"]:
                self._search_index = 0
                self._search_matches = []
                self.status_bar.search_mode = False
                if event.key == "escape":
                    self.note_tree_widget.update_location(
                        context_node=self._pre_search_position[0],
                        line_node=self._pre_search_position[1],
                    )
                self._pre_search_position = (None, None)
        elif event.key == "enter" and not self.input_widget.display:
            self.note_tree_widget.action_add_note()
        elif event.key in "0123456789":
            self.note_tree_widget.visit_bookmark(int(event.key))


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Run Note Interface")
    parser.add_argument("notes", help="a notes file (.txt)")
    args = parser.parse_args()
    notes_filename = args.notes

    app = ForestApp(notes_filename)
    app.run()
