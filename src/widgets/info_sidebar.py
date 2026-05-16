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
        self.set_interval(5, self._refresh_clock_row)

    def _refresh_clock_row(self):
        """Update the clock row in place so it stays current while the sidebar is open."""
        if not self.display or self.row_count == 0:
            return
        title, body = compose_clock_notify_contents()
        clock_text = Text.from_markup(f"[italic]{title}[dim] - {body}[/dim][/italic]")
        try:
            self.update_cell_at((0, 1), clock_text)
        except Exception:
            pass

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
                ["0-9", "Jump to bookmarked copy"],
                ["S-0..9", "Assign bookmark # to copied note"],
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
                ["l", "Paste [[path]] link to top of copied list"],
                ["y", "Yank note text to system clipboard"],
                ["Y", "Yank note + subtree to system clipboard"],
                ["z/Z", "Undo/redo"],
                ["", ""],
                ["", Text.from_markup("[b]Commands[/b]")],
                [":", "Command mode"],
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

        self._render_rows(table_rows)

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

        copied_nodes = self.app.note_tree.copied_nodes
        hl1 = self.app.theme_variables.get("HL1", "white")

        for idx, match_node in enumerate(matches):
            is_current = idx == self._search_highlight_index
            is_copied = match_node in copied_nodes

            node_text = self._truncate(match_node.text, width)

            if is_current:
                marker = Text.from_markup("❯")
            elif is_copied:
                marker = Text.from_markup(f"[{hl1}]•[/{hl1}]")
            else:
                marker = Text.from_markup("[dim]›[/dim]")
            if is_current:
                styled_text = Text.from_markup(f"[reverse]{node_text}[/reverse]")
                highlight_row = len(table_rows)
            else:
                styled_text = Text.from_markup(f"{node_text}")
            table_rows.append([marker, styled_text])

            # Row 2: ancestor path (first few parts, dim)
            path_parts = match_node.get_path(include_self=False)[1:]  # skip root
            if path_parts:
                path_preview = self._truncate(" › ".join(path_parts[:3]), width)
                table_rows.append(["", Text.from_markup(f"[dim]{path_preview}[/dim]")])

        if not matches:
            table_rows.append(["", "No results found"])

        self._render_rows(table_rows)

        # Scroll to keep highlighted row visible
        if highlight_row is not None:
            try:
                self.move_cursor(row=highlight_row)
            except Exception:
                pass

    def hide_search_results(self):
        """Clear search results and restore previous panel mode."""
        self._search_results = []
        self._search_highlight_index = 0
        self.mode_index = self._pre_search_mode_index
        self.update_data()

    def _render_rows(self, rows):
        self.clear(columns=True)
        self.add_columns("", "")
        self.add_rows(rows)
        self.refresh()

    def _truncate(self, text, width):
        max_text_width = max(width - 6, 10)
        if len(text) > max_text_width:
            return text[: max_text_width - 1] + "…"
        return text

    def _build_bookmark_rows(self, width):
        rows = [
            ["", Text.from_markup("[b]Copied Stack[/b]")],
            ["", ""],
        ]
        copied_nodes = self.app.note_tree.copied_nodes
        if copied_nodes:
            hl1 = self.app.theme_variables.get("HL1", "white")
            for i, node in enumerate(copied_nodes[::-1]):
                text = self._truncate(node.text, width)
                slot = self.app.note_tree.get_bookmark_slot(node)
                if slot is not None:
                    base = " vl" if i == 0 else ""
                    marker_inner = f"[b]{slot}[/b]{base}"
                else:
                    marker_inner = "vl" if i == 0 else "•"
                rows.append(
                    [
                        Text.from_markup(f"[dim][{hl1}]{marker_inner}[/{hl1}][/dim]"),
                        Text.from_markup(text),
                    ]
                )
            rows.extend(
                [
                    ["", Text.from_markup("[dim]\\[c]opy \\[v]paste \\[l]ink[/dim]")],
                    ["", Text.from_markup("[dim]\\[C]ycle \\[V]isit \\[#]jump[/dim]")],
                    ["", Text.from_markup("[dim]\\[S-#]bookmark[/dim]")],
                ]
            )

        archived_roots = self._collect_archived_roots()
        if archived_roots:
            rows.extend(
                [
                    ["", ""],
                    ["", Text.from_markup("[b]Archived[/b]")],
                    ["", ""],
                ]
            )
            for node in archived_roots:
                text = self._truncate(node.text.replace("#ARCHIVE", "").strip(), width)
                rows.append(["", Text.from_markup(f"[dim]{text}[/dim]")])
        return rows

    def _build_perpetual_journal_rows(self, width):
        from datetime import date as _date

        before, after = 7, 14
        node_matches = self.app.note_tree.get_journal_entries_in_day_radius(
            before, after
        )
        today_year = _date.today().strftime("%Y")
        today_md = _date.today().strftime("%m-%d")
        hl1 = self.app.theme_variables.get("HL1", "white")
        strip_re = r"\[\d{4}-\d{2}-\d{2}.*?\]\s*"
        today_marker = [
            Text.from_markup(f"[{hl1}]{today_year}-{today_md}[/{hl1}]"),
            Text.from_markup("Today"),
        ]

        rows = [
            ["", Text.from_markup(f"[b]-{before} / +{after} days[/b]")],
            ["", ""],
            ["Date", "Entry"],
        ]
        today_inserted = any(match_str[5:] == today_md for _, match_str in node_matches)
        today_row_added = False
        for node, match_str in node_matches:
            entry_md = match_str[5:]  # MM-DD from YYYY-MM-DD
            if not today_inserted and not today_row_added and entry_md > today_md:
                rows.append(today_marker)
                today_row_added = True
            text = node.text if node else ""
            text = re.sub(strip_re, "", text).strip()
            lines = textwrap.wrap(text, width - 16)
            is_today = entry_md == today_md
            for i_l, line in enumerate(lines):
                if is_today:
                    date_cell = (
                        Text.from_markup(f"[{hl1}]{match_str}[/{hl1}]")
                        if i_l == 0
                        else ""
                    )
                    rows.append([date_cell, Text.from_markup(f"{line}")])
                else:
                    rows.append([match_str if i_l == 0 else "", line])
        if not today_inserted and not today_row_added:
            rows.append(today_marker)
        return rows

    _ROW_BUILDERS = {
        "bookmarks": _build_bookmark_rows,
        "perpetual_journal": _build_perpetual_journal_rows,
    }

    def update_data(self):
        self._search_results = []
        mode = self.mode_options[self.mode_index]
        if mode is None:
            self.clear(columns=True)
            self.display = False
            self.refresh()
            return
        self.display = True
        self.show_header = False
        width = min(self.app.size.width // 2, 60)
        rows = self._clock_rows()
        builder = self._ROW_BUILDERS.get(mode)
        if builder is not None:
            rows.extend(builder(self, width))
        self._render_rows(rows)
