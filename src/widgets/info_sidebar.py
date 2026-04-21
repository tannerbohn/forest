import logging
import re
import textwrap
from datetime import datetime

from rich.text import Text
from textual.color import Color
from textual.widgets import DataTable

from utils import compose_clock_notify_contents


class InfoSidebar(DataTable):
    DEFAULT_CSS = """
    InfoSidebar {
        height: 100%;
        color: $foreground 50%;
        background-tint: $panel 10%;
        display: none;
        layer: overlay;
        offset: 0 1;
    }
    """

    mode_index = 0
    mode_options = [None, "bookmarks", "perpetual_journal"]
    _search_results = []  # list of match nodes when search panel is shown
    _search_highlight_index = 0
    _pre_search_mode_index = 0  # panel mode to restore after search exits

    def on_mount(self):
        """Initialize the DataTable with columns to prevent first-render issues."""
        self.add_columns("", "")
        self.show_header = True

    def apply_layout(self, side: str, width: int):
        self.styles.dock = side
        self.styles.width = width
        panel = Color.parse(self.app.theme_variables.get("panel", "#000000"))
        # bg = Color.parse(self.app.theme_variables.get("background", "#ffffff"))
        blended = panel  # .blend(bg, 0.5).hex
        border = ("vkey", blended)
        no_border = ("none", blended)
        if side == "right":
            self.styles.border_left = border
            self.styles.border_right = no_border
        else:
            self.styles.border_right = border
            self.styles.border_left = no_border

    def cycle_mode(self):
        old_index = self.mode_index
        self.mode_index = (self.mode_index + 1) % len(self.mode_options)
        logging.info(
            f"cycle_mode: {old_index} -> {self.mode_index}, mode = {self.mode_options[self.mode_index]}"
        )
        self.update_data()

    def _collect_archived_roots(self):
        """Archived branch roots inside the current context."""
        ctx = self.app.note_tree.context_node
        nodes = ctx.get_node_list(only_visible=False, hide_archive=False)
        return [
            n
            for n in nodes
            if "#ARCHIVE" in n.text
            and n.parent is not None
            and "#ARCHIVE" not in n.parent.text
        ]

    def _clock_rows(self):
        """Return dim clock/date rows for appending to any panel."""
        title, body = compose_clock_notify_contents()
        hl = self.app.theme_variables["HL1"]
        rows = [
            [
                "",
                Text.from_markup(f"[italic]{title}[dim] - {body}[/dim][/italic]"),
            ],
            ["", ""],
        ]
        # for line in body.split("\n"):
        #     rows.append(["", Text.from_markup(f"[dim]{line}[/dim]")])
        return rows

    def show_help(self):
        """Display help information without adding to the cycle."""
        logging.info("show_help called")
        self._search_results = []
        # Set mode_index to last position so next cycle wraps to 0 (None/hidden)
        self.mode_index = len(self.mode_options) - 1
        self.display = True
        self.show_header = False

        table_rows = self._clock_rows()

        # remember to keep ForestApp.on_key up-to-date
        table_rows.extend(
            [
                ["", Text.from_markup("[b]Forest Help[/b]")],
                ["", Text.from_markup("[dim](Press ` to hide)[/dim]")],
                ["", ""],
                ["", Text.from_markup("[b]Navigation[/b]")],
                ["←/→", "Zoom out/in"],
                ["space", "Toggle collapse"],
                ["0-9", "Jump to bookmark"],
                ["", ""],
                ["", Text.from_markup("[b]Editing[/b]")],
                ["bksp", "Edit note"],
                ["enter", "Add new note"],
                ["delete", "Delete note"],
                ["u/d", "Move note up/down"],
                ["tab/S-tab", "Indent/deindent"],
                ["h", "Cycle highlight"],
                ["x", "Toggle #DONE"],
                ["X", "Toggle hiding #DONE notes"],
                ["c", "Copy (press again to uncopy)"],
                ["C", "Cycle paste target (rotates list)"],
                ["v", "Paste top of copied list after cursor"],
                ["V", "Move to next copied note (rotates list)"],
                ["z/Z", "Undo/redo"],
                ["", ""],
                ["", Text.from_markup("[b]Commands[/b]")],
                [":", "Command mode"],
                [":b or :bookmark", "Toggle bookmark"],
                [":j+ <text>", "Add journal entry"],
                [":collapse", "Collapse all nodes in context"],
                [":? <query regex>", "Search in context"],
                [":?*/?? <query regex>", "Search globally"],
                ["", "(empty query to find similar)"],
                [":sn [filter]", "Sticky notes (context)"],
                [":sn* [filter]", "Sticky notes (global)"],
                [":snr", "Recover last sticky board"],
                [":random", "Jump to random note (context)"],
                [":random*", "Jump to random note (global)"],
                [":insert <name>", "Insert template"],
                [":run [<idx>]", "Run ! cmd or follow [[PATH]]"],
                [":archive set/unset", "Mark/unmark cursor as #ARCHIVE"],
                [":archive show/hide", "Reveal/hide archived nodes"],
                [":help", "Show this help"],
                ["", ""],
                ["", Text.from_markup("[b]Other[/b]")],
                ["s", "Save"],
                ["`", "Cycle side panel"],
            ]
        )

        self.clear(columns=True)
        self.add_columns("", "")
        self.add_rows(table_rows)
        self.refresh()

    def show_search_results(self, matches, query="", current_index=0):
        """Display search results in panel with current match highlighted."""
        logging.info(
            f"show_search_results called with {len(matches)} matches, query={query!r}"
        )
        self._pre_search_mode_index = self.mode_index
        self._search_results = matches
        self._search_highlight_index = current_index
        self.display = True
        self.show_header = False

        self._render_search_rows(query)

    def update_search_highlight(self, new_index):
        """Update which row is highlighted in the search results panel."""
        if not self._search_results:
            return
        self._search_highlight_index = new_index % len(self._search_results)
        # Re-render the table with updated highlight
        query = getattr(self, "_last_search_query", "")
        self._render_search_rows(query)

    def _render_search_rows(self, query=""):
        """Render search results table rows with highlight on current index."""
        self._last_search_query = query
        matches = self._search_results
        width = min(self.app.size.width // 2, 60)

        table_rows = self._clock_rows()

        header = f"Search: {query}" if query else "Similar Notes"
        table_rows.extend(
            [
                ["", Text.from_markup(f"[b]{header}[/b]")],
                [
                    "",
                    Text.from_markup(
                        f"[dim]{len(matches)} result{'s' if len(matches) != 1 else ''} - Use ↑/↓ to cycle[/dim]"
                    ),
                ],
                ["", ""],
            ]
        )

        # Track which DataTable row index corresponds to the highlighted match
        highlight_row = None
        max_text_width = max(width - 6, 10)

        for idx, match_node in enumerate(matches):
            is_current = idx == self._search_highlight_index

            # Row 1: marker + node text
            node_text = match_node.text
            if len(node_text) > max_text_width:
                node_text = node_text[: max_text_width - 1] + "…"

            marker = (
                Text.from_markup("❯")
                if is_current
                else Text.from_markup("[dim]›[/dim]")
            )
            if is_current:
                styled_text = Text.from_markup(f"[reverse]{node_text}[/reverse]")
                highlight_row = len(table_rows)
            else:
                styled_text = Text.from_markup(f"{node_text}")
            table_rows.append([marker, styled_text])

            # Row 2: ancestor path (first few parts, dim)
            path_parts = match_node.get_path(include_self=False)[1:]  # skip root
            if path_parts:
                path_parts = path_parts[:3]  # show up to 3 ancestor parts
                path_preview = " › ".join(path_parts)
                if len(path_preview) > max_text_width:
                    path_preview = path_preview[: max_text_width - 1] + "…"
                table_rows.append(["", Text.from_markup(f"[dim]{path_preview}[/dim]")])

        if not matches:
            table_rows.append(["", "No results found"])

        self.clear(columns=True)
        self.add_columns("", "")
        self.add_rows(table_rows)

        # Scroll to keep highlighted row visible
        if highlight_row is not None:
            try:
                self.move_cursor(row=highlight_row)
            except Exception:
                pass

        self.refresh()

    def hide_search_results(self):
        """Clear search results and restore previous panel mode."""
        self._search_results = []
        self._search_highlight_index = 0
        self.mode_index = self._pre_search_mode_index
        self.update_data()

    def update_data(self):
        self._search_results = []

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

        table_rows = self._clock_rows()

        if mode == "bookmarks":
            logging.info("update_data: building bookmarks table")
            self.show_header = False

            table_rows.extend(
                [
                    ["", Text.from_markup("[b]Bookmarks[/b]")],
                    ["", ""],
                    ["Key", "Note"],
                ]
            )

            nb_bookmarks = 10
            for index in range(nb_bookmarks):
                node = self.app.note_tree.bookmarks.get(index)
                text = node.text if node else ""
                table_rows.append([index, text])

            copied_nodes = self.app.note_tree.copied_nodes
            if copied_nodes:
                table_rows.extend(
                    [
                        ["", ""],
                        ["", Text.from_markup("[b]Copied[/b]")],
                        ["", ""],
                    ]
                )
                max_text_width = max(width - 6, 10)
                hl1 = self.app.theme_variables.get("HL1", "white")
                n = len(copied_nodes)
                for i, node in enumerate(copied_nodes[::-1]):
                    text = node.text
                    if len(text) > max_text_width:
                        text = text[: max_text_width - 1] + "…"
                    marker = "v" if i == 0 else "•"
                    table_rows.append(
                        [
                            Text.from_markup(f"[dim][{hl1}]{marker}[/{hl1}][/dim]"),
                            Text.from_markup(text),
                        ]
                    )
                table_rows.append(
                    [
                        "",
                        Text.from_markup(
                            "[dim]\\[c]opy \\[v]paste \\[C]ycle \\[V]isit[/dim]"
                        ),
                    ]
                )

            archived_roots = self._collect_archived_roots()
            if archived_roots:
                table_rows.extend(
                    [
                        ["", ""],
                        ["", Text.from_markup("[b]Archived[/b]")],
                        ["", ""],
                    ]
                )
                max_text_width = max(width - 6, 10)
                for node in archived_roots:
                    text = node.text.replace("#ARCHIVE", "").strip()
                    if len(text) > max_text_width:
                        text = text[: max_text_width - 1] + "…"
                    table_rows.append(["", Text.from_markup(f"[dim]{text}[/dim]")])

            self.clear(columns=True)
            self.add_columns("", "")
            self.add_rows(table_rows)
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

            table_rows.extend(
                [
                    ["", Text.from_markup("[b]On This Day[/b]")],
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
                        Text.from_markup("[b]In This Month[/b]"),
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
