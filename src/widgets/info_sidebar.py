import logging
import re
import textwrap

from rich.text import Text
from textual.color import Color
from textual.widgets import OptionList
from textual.widgets.option_list import Option


class InfoSidebar(OptionList):
    DEFAULT_CSS = """
    InfoSidebar {
        height: 100%;
        color: $foreground 50%;
        background-tint: $panel 10%;
        width: 0;
        visibility: hidden;
        layer: overlay;
        offset: 0 1;
        scrollbar-size: 0 0;
        padding: 0 1;
        border: none;
    }
    InfoSidebar:focus {
        border: none;
    }
    """

    _panel_width = None

    mode_index = 0
    mode_options = [None, "bookmarks", "perpetual_journal"]
    # The panel stays in the layout at a constant width at all times and
    # opens/closes by toggling `visibility`. A constant-width widget is laid out
    # on every frame, so its overlay region always exists and revealing it
    # composites on the first frame — unlike a display:none -> block transition,
    # whose overlay region is only created during the ensuing layout (missing the
    # first frame), and unlike a 0 -> N width change, which forces the OptionList
    # to rebuild its lines from a zero-width state.
    _open = False
    _search_results = []  # list of match nodes when search panel is shown
    _pre_search_mode_index = 0  # panel mode to restore after search exits

    def on_mount(self):
        self._option_nodes = {}  # option id -> Node (selectable entries only)
        self._opt_counter = 0
        self._search_entry_ids = []  # option ids of search results, in order

    # --------------------------------------------------------------- layout

    def apply_layout(self, side: str, width: int):
        self._panel_width = width
        self._side = side
        self.styles.dock = side
        self._sync_visibility()

    # --------------------------------------------------------- open / close

    @property
    def is_open(self) -> bool:
        """Whether the panel is currently shown. Replaces the old `display`
        flag; visibility is driven by the `visibility` style, not width."""
        return self._open

    def _sync_visibility(self) -> None:
        # The panel keeps its real width at all times; `visibility` is the
        # open/closed switch. `hidden` paints nothing (border, padding, and
        # background-tint included), so no strip lingers when closed.
        if self._panel_width:
            self.styles.width = self._panel_width
        if self._open:
            self.styles.visibility = "visible"
            self._apply_border()
        else:
            self.styles.visibility = "hidden"

    def open_panel(self) -> None:
        self._open = True
        self._sync_visibility()

    def close_panel(self) -> None:
        self._open = False
        self._sync_visibility()

    def _apply_border(self, focused: bool | None = None):
        # Draw only the divider edge (the side facing the center of the screen),
        # in HL1 while focused and the panel color otherwise. Set all four edges
        # inline (inline styles beat the OptionList :focus rule that would
        # otherwise re-add a full `tall` border on focus).
        if focused is None:
            focused = self.has_focus
        tv = self.app.theme_variables
        panel = Color.parse(tv.get("panel", "#000000"))
        active_color = Color.parse(tv.get("HL1", "#ffffff")) if focused else panel
        border = ("vkey", active_color)
        no_border = ("none", panel)
        self.styles.border_top = no_border
        self.styles.border_bottom = no_border
        if getattr(self, "_side", "right") == "right":
            self.styles.border_left = border
            self.styles.border_right = no_border
        else:
            self.styles.border_right = border
            self.styles.border_left = no_border

    def _content_width(self) -> int:
        # The panel is always laid out at its real width (only `visibility`
        # toggles), so content_size is reliable here.
        w = self.content_size.width or self._panel_width or 30
        return max(w, 16)

    # ------------------------------------------------------- option helpers

    def _register(self, prompt, node) -> Option:
        """Selectable entry carrying a node (resolved on select/highlight)."""
        tok = f"opt{self._opt_counter}"
        self._opt_counter += 1
        self._option_nodes[tok] = node
        return Option(prompt, id=tok)

    def _header(self, markup: str) -> Option:
        return Option(Text.from_markup(f"[b]{markup}[/b]"), disabled=True)

    def _blank(self) -> Option:
        return Option("", disabled=True)

    def _ellipsize(self, s: str, width: int) -> str:
        if len(s) > width:
            return s[: max(width - 1, 0)].rstrip() + "…"
        return s

    def _line(self, marker: Text, body: str, width: int, body_style=None) -> Text:
        """Single-line prompt: `marker` inline + `body` collapsed to one line and
        truncated with an ellipsis. (OptionList soft-wraps and ignores Rich's
        overflow, so the one-line cap has to be applied here.)"""
        marker_len = marker.cell_len
        avail = max(width - marker_len - 1, 6)
        line = self._ellipsize(" ".join(body.split()), avail)
        t = Text()
        t.append_text(marker)
        if marker_len:
            t.append(" ")
        t.append(line, style=body_style or "")
        return t

    def _wrapped(
        self, marker: Text, body: str, width: int, max_lines: int, body_style=None
    ) -> Text:
        """`marker` inline on line 1, `body` wrapped to at most `max_lines`
        (over-long text ellipsised). Short bodies use fewer lines. Wrapped lines
        carry a small hanging indent, not a marker-width column."""
        marker_len = marker.cell_len
        init = " " * (marker_len + 1)
        sub = "  "
        body = " ".join(body.split())
        wrapped = textwrap.wrap(
            body,
            max(width, marker_len + 6),
            initial_indent=init,
            subsequent_indent=sub,
        ) or [init]
        shown = wrapped[:max_lines]
        if len(wrapped) > max_lines:
            shown[-1] = self._ellipsize(shown[-1] + " …", width)
        t = Text()
        t.append_text(marker)
        t.append(" ")
        t.append(shown[0][len(init) :], style=body_style or "")
        for line in shown[1:]:
            t.append("\n")
            t.append(line, style=body_style or "")
        return t

    def _entry(
        self, marker: Text, body: str, node, width, body_style=None, max_lines=1
    ) -> Option:
        """Selectable bookmark/journal/search entry carrying `node`. Renders on
        one line by default; `max_lines` > 1 wraps up to that many lines."""
        if max_lines <= 1:
            prompt = self._line(marker, body, width, body_style)
        else:
            prompt = self._wrapped(marker, body, width, max_lines, body_style)
        return self._register(prompt, node)

    # --------------------------------------------------------------- render

    def _render_options(self, options, highlight=None):
        self.clear_options()
        self.add_options(options)
        if highlight is not None and 0 <= highlight < self.option_count:
            try:
                self.highlighted = highlight
            except Exception:
                pass
        # Outside search, only show the cursor when the panel has focus — a
        # lingering blurred highlight (e.g. after a rebuild while the cursor is
        # on the tree) is just visual noise.
        if not self._search_results and not self.has_focus:
            self.highlighted = None
        self.refresh()

    def _first_entry_index(self, options):
        for i, opt in enumerate(options):
            if not opt.disabled:
                return i
        return None

    # ---------------------------------------------------------------- modes

    def is_showing_bookmarks(self) -> bool:
        return (
            self._open
            and not self._search_results
            and self.mode_options[self.mode_index] == "bookmarks"
        )

    def cycle_mode(self):
        old_index = self.mode_index
        self.mode_index = (self.mode_index + 1) % len(self.mode_options)
        logging.info(
            f"cycle_mode: {old_index} -> {self.mode_index}, mode = {self.mode_options[self.mode_index]}"
        )
        self.update_data()

    def _branch_stats(self, node) -> str:
        """One-line branch summary: age of the newest note and the number of
        open-question leaves (leaf notes with a `?`, excluding #DONE/#ARCHIVE)."""
        questions = sum(
            1
            for n in node.get_node_list()
            if not n.children
            and "?" in n.text
            and not n.is_done()
            and not n.is_archived()
        )
        days = node.get_days_old(recurse=True)
        age = "today" if days <= 0 else f"{days}d ago"
        return f"{age} - {questions} leaf Q"

    def _bookmark_entry(self, marker, node, width) -> Option:
        """Two-line bookmark entry: note text on line 1, dim branch stats on
        line 2 (aligned under the text)."""
        first = self._line(marker, node.text, width - 1)
        indent = " " * (marker.cell_len + 1)
        stats = self._ellipsize(indent + self._branch_stats(node), width)
        t = Text()
        t.append_text(first)
        t.append("\n")
        t.append(stats, style="dim")
        return self._register(t, node)

    def _build_bookmark_rows(self, width):
        options = [self._header("Bookmarks"), self._blank()]
        copied_nodes = self.app.note_tree.copied_nodes
        if copied_nodes:
            added_first_slot = False
            for i, node in enumerate(copied_nodes[::-1]):
                # if i > 0:
                #     options.append(self._blank())
                slot = self.app.note_tree.get_bookmark_slot(node)
                if slot is not None:
                    marker_inner = f"[b]{slot}[/b]"
                    if not added_first_slot:
                        options.append(self._blank())
                        added_first_slot = True
                else:
                    marker_inner = "•"
                marker = Text.from_markup(f"[dim]{marker_inner}[/dim]")
                options.append(self._bookmark_entry(marker, node, width))

            options.extend(
                [
                    self._blank(),
                    Option(
                        Text.from_markup("[dim]\\[c]opy \\[v]paste \\[l]ink[/dim]"),
                        disabled=True,
                    ),
                    Option(
                        Text.from_markup(
                            "[dim]\\[u/d]move \\[#]jump \\[S-#]bookmark[/dim]"
                        ),
                        disabled=True,
                    ),
                    Option(
                        Text.from_markup("[dim]\\[Del]remove from list[/dim]"),
                        disabled=True,
                    ),
                ]
            )

        return options

    def _build_perpetual_journal_rows(self, width):
        from datetime import date as _date

        before, after = 3, 7
        node_matches = self.app.note_tree.get_journal_entries_in_day_radius(
            before, after
        )
        today_ymd = _date.today().strftime("%Y-%m-%d")
        today_md = _date.today().strftime("%m-%d")
        hl1 = self.app.theme_variables.get("HL1", "white")
        strip_re = r"\[\d{4}-\d{2}-\d{2}.*?\]\s*"

        options = [self._header(f"-{before} / +{after} days"), self._blank()]

        today_inserted = any(match_str[5:] == today_md for _, match_str in node_matches)
        today_row_added = False

        def today_marker_option():
            return Option(
                Text.from_markup(f"[{hl1}]{today_ymd} Today[/{hl1}]"), disabled=True
            )

        for node, match_str in node_matches:
            entry_md = match_str[5:]  # MM-DD from YYYY-MM-DD
            if not today_inserted and not today_row_added and entry_md > today_md:
                options.append(today_marker_option())
                options.append(self._blank())
                today_row_added = True
            text = re.sub(strip_re, "", node.text if node else "").strip()
            is_today = entry_md == today_md
            date_style = hl1 if is_today else "dim"
            # Full YYYY-MM-DD, inline (not a column); its styling marks the
            # entry boundary. Journal entries are prose — allow up to 3 lines.
            marker = Text.from_markup(f"[{date_style}]{match_str}[/{date_style}]")
            options.append(self._entry(marker, text, node, width, max_lines=3))
            options.append(self._blank())

        if not today_inserted and not today_row_added:
            options.append(today_marker_option())
        return options

    _ROW_BUILDERS = {
        "bookmarks": _build_bookmark_rows,
        "perpetual_journal": _build_perpetual_journal_rows,
    }

    def update_data(self):
        # Remember which node the cursor is on so an in-place refresh keeps the
        # cursor put rather than snapping back to the top. On a genuine mode
        # change the node won't exist in the new options and we fall back to the
        # first entry.
        prev_node = self._current_node()
        self._search_results = []
        self._search_entry_ids = []
        self._option_nodes = {}
        self._opt_counter = 0
        mode = self.mode_options[self.mode_index]
        if mode is None:
            self.clear_options()
            self.close_panel()
            self.refresh()
            return
        self.open_panel()
        width = self._content_width()
        options = []
        builder = self._ROW_BUILDERS.get(mode)
        if builder is not None:
            options.extend(builder(self, width))
        hi = self._index_of_node(options, prev_node)
        if hi is None:
            hi = self._first_entry_index(options)
        self._render_options(options, highlight=hi)

    def _index_of_node(self, options, node):
        if node is None:
            return None
        for i, opt in enumerate(options):
            if opt.id and self._option_nodes.get(opt.id) is node:
                return i
        return None

    # ----------------------------------------------------------------- help

    def show_help(self):
        logging.info("show_help called")
        self._search_results = []
        self._search_entry_ids = []
        self._option_nodes = {}
        self._opt_counter = 0
        # Set mode_index to last position so next cycle wraps to 0 (None/hidden)
        self.mode_index = len(self.mode_options) - 1
        self.open_panel()

        # Help lines are enabled (node=None) so arrow keys scroll the panel;
        # selecting one is a no-op. `right` is rendered as plain text (never
        # markup) so bracketed help like [[PATH]] or [c]opy doesn't misparse.
        def line(left, right=""):
            if right:
                text = Text()
                text.append(left, style="dim")
                text.append("  ")
                text.append(right)
            else:
                text = Text.from_markup(left)
            return self._register(text, None)

        options = []
        # remember to keep ForestApp.on_key up-to-date
        options.extend(
            [
                line("[b]Forest Help[/b]"),
                line("[dim](Press ` to hide)[/dim]"),
                self._blank(),
                line("[b]Navigation[/b]"),
                line("←/→", "Zoom out/in"),
                line("space", "Toggle collapse"),
                line("0-9", "Jump to bookmarked copy"),
                line("S-0..9", "Assign bookmark # to copied note"),
                self._blank(),
                line("[b]Editing[/b]"),
                line("bksp", "Edit note"),
                line("enter", "Add new note"),
                line("delete", "Delete note"),
                line("u/d", "Move note up/down"),
                line("tab/S-tab", "Indent/deindent"),
                line("h", "Cycle highlight"),
                line("x", "Toggle #DONE"),
                line("X", "Toggle hiding #DONE notes"),
                line("c", "Copy (press again to uncopy)"),
                line("v", "Paste last-focused copied note after cursor"),
                line("l", "Paste [[path]] link to last-focused note"),
                line("y", "Yank note text to system clipboard"),
                line("Y", "Yank note + subtree to system clipboard"),
                line("z/Z", "Undo/redo"),
                self._blank(),
                line("[b]Commands[/b]"),
                line(":", "Command mode"),
                line(":j+ <text>", "Add journal entry"),
                line(":collapse", "Collapse all nodes in context"),
                line(":? <query regex>", "Search in context"),
                line(":?*/?? <query regex>", "Search globally"),
                line("", "(empty query to find similar)"),
                line(":sn [filter]", "Sticky notes (context)"),
                line(":sn* [filter]", "Sticky notes (global)"),
                line(":snr", "Recover last sticky board"),
                line(":random", "Jump to random note (context)"),
                line(":random*", "Jump to random note (global)"),
                line(":insert <name>", "Insert template"),
                line(":run [<idx>]", "Run ! cmd or follow [[PATH]]"),
                line(":archive set/unset", "Mark/unmark cursor as #ARCHIVE"),
                line(":archive show/hide", "Reveal/hide archived nodes"),
                line(":help", "Show this help"),
                self._blank(),
                line("[b]Other[/b]"),
                line("s", "Save"),
                line("`", "Cycle side panel"),
            ]
        )
        self._render_options(options, highlight=self._first_entry_index(options))

    # --------------------------------------------------------------- search

    def show_search_results(self, matches, query="", current_index=0):
        logging.info(
            f"show_search_results called with {len(matches)} matches, query={query!r}"
        )
        self._pre_search_mode_index = self.mode_index
        self._search_results = matches
        self.open_panel()
        self._render_search_rows(query, highlight_match=current_index)

    def _render_search_rows(self, query="", highlight_match=0):
        self._last_search_query = query
        self._option_nodes = {}
        self._opt_counter = 0
        self._search_entry_ids = []
        matches = self._search_results
        width = self._content_width()

        options = []

        copied_nodes = self.app.note_tree.copied_nodes
        hl1 = self.app.theme_variables.get("HL1", "white")

        search = getattr(self.app, "_search", None)
        if (
            search
            and getattr(search, "is_local", False)
            and search.context_node is not None
        ):
            skip = search.context_node.depth + 1
        else:
            skip = 1

        highlight_index = None
        for idx, match_node in enumerate(matches):
            is_copied = match_node in copied_nodes

            path_parts = match_node.get_path(include_self=False)[skip:]
            if path_parts:
                path_preview = self._ellipsize(
                    " › ".join(path_parts[:3]), max(width - 6, 10)
                )
                options.append(
                    Option(
                        Text.from_markup(f"[dim]{path_preview}[/dim]"), disabled=True
                    )
                )

            if is_copied:
                marker = Text.from_markup(f"[{hl1}]•[/{hl1}]")
            else:
                marker = Text.from_markup("[dim]›[/dim]")

            opt = self._register(self._line(marker, match_node.text, width), match_node)
            self._search_entry_ids.append(opt.id)
            if idx == highlight_match:
                highlight_index = len(options)
            options.append(opt)
            options.append(self._blank())

        if not matches:
            options.append(Option(Text("No results found"), disabled=True))

        self._render_options(options, highlight=highlight_index)

    def hide_search_results(self):
        self._search_results = []
        self._search_entry_ids = []
        self.mode_index = self._pre_search_mode_index
        self.update_data()

    # ------------------------------------------------------- messages / keys

    def _node_for_option(self, option) -> object:
        if option is None or option.id is None:
            return None
        return self._option_nodes.get(option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        node = self._option_nodes.get(event.option_id)
        if node is None:
            return
        if self._search_results:
            self.app.accept_search(node)
        else:
            self.app.jump_to_node(node)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted):
        # Search: live-preview the highlighted match + update status bar.
        if self._search_results:
            node = self._option_nodes.get(event.option_id)
            if node is not None and event.option_id in self._search_entry_ids:
                order = self._search_entry_ids.index(event.option_id)
                self.app.status_bar.search_progress = (order, len(self._search_results))
                if getattr(self.app, "_search", None) is not None:
                    self.app._search.index = order
                # Preview only — don't record until the user selects a result.
                self.app.note_tree_widget.update_location(
                    context_node=node.parent, line_node=node, record=False
                )
            return
        # Bookmarks: the entry the user actively navigates to becomes the paste
        # / link source (guarded by focus so background rebuilds don't clobber
        # it). v/l then act on this last-focused note. See _resolve_paste_source.
        if self.is_showing_bookmarks() and self.has_focus:
            node = self._option_nodes.get(event.option_id)
            if node is not None:
                self.app._paste_source_node = node

    def _current_node(self):
        if self.highlighted is None:
            return None
        return self._node_for_option(self.get_option_at_index(self.highlighted))

    def on_focus(self):
        if self._open:
            self._apply_border(focused=True)

    def on_blur(self):
        if self._open:
            self._apply_border(focused=False)

    def on_key(self, event):
        if event.key == "enter":
            # Handle the jump here and swallow the key so it never bubbles to
            # ForestApp.on_key (which would also fire action_add_note).
            # prevent_default stops OptionList's own `select` binding, so no
            # duplicate OptionSelected fires; mouse clicks still route through
            # on_option_list_option_selected.
            event.stop()
            event.prevent_default()
            node = self._current_node()
            if node is not None:
                if self._search_results:
                    self.app.accept_search(node)
                else:
                    self.app.jump_to_node(node)
            return
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            if self._search_results:
                self.app.cancel_search()
            else:
                self.app.hide_sidebar_focus_tree()
            return
        if event.key == "delete":
            # Del in the bookmarks panel removes the highlighted entry from the
            # quick-links list (and clears its bookmark slot) — it never touches
            # the underlying note. Swallowed in every context so it can't bubble
            # to the tree and delete the cursor note while the panel is focused.
            event.stop()
            event.prevent_default()
            if self.is_showing_bookmarks():
                node = self._current_node()
                if node is not None and node in self.app.note_tree.copied_nodes:
                    self.app.copied_toggle(node)
            return
        if event.key in ("u", "d"):
            # u/d reorder a copied note up/down when the bookmarks panel is
            # focused and the cursor sits on a copied note. Swallowed in every
            # other context so the keys never bubble to the tree.
            event.stop()
            event.prevent_default()
            if self.is_showing_bookmarks():
                node = self._current_node()
                if node is not None and node in self.app.note_tree.copied_nodes:
                    self.app.copied_move(node, up=(event.key == "u"))
            return
        if event.key == "c" and self._search_results:
            event.stop()
            event.prevent_default()
            node = self._current_node()
            if node is not None and node.parent is not None:
                # Match ordinal is stable across the toggle; preserve highlight.
                order = self._search_entry_ids_order(node)
                self.app.copied_toggle(node)
                self._render_search_rows(
                    getattr(self, "_last_search_query", ""), highlight_match=order
                )
                self.app.note_tree_widget.render()
            return

    def _search_entry_ids_order(self, node):
        for order, oid in enumerate(self._search_entry_ids):
            if self._option_nodes.get(oid) is node:
                return order
        return 0
