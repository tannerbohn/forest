import textwrap
from typing import cast

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual._segment_tools import line_pad
from textual.binding import Binding
from textual.color import Gradient
from textual.strip import Strip
from textual.widgets import Tree

from note_tree import NoteTree
from subtrees import SUBTREES
from utils import add_subtree

logging = None


class NoteTreeWidget(Tree):

    BINDINGS = [
        Binding("s", "save()", "Save", show=True),
        # Binding("enter", "add_note()", "Add note", show=True),
        Binding("left", "zoom_out()", "Zoom out", show=True),
        Binding("right", "zoom_in()", "Zoom in", show=True),
        Binding("space", "toggle_node()", "Toggle", show=False),
        Binding("h", "cycle_highlight()", "Cycle highlight", show=True),
        Binding("x", "toggle_done()", "Toggle done", show=True),
        Binding("tab", "indent()", "Indent", show=False),
        Binding("shift+tab", "deindent()", "Deindent", show=False),
        Binding("delete", "delete_node()", "Delete", show=False),
        Binding("u", "move_node('up')", "Move up", show=False),
        Binding("d", "move_node('down')", "Move down", show=False),
    ]

    def __init__(self, note_tree: NoteTree, id: str):
        super().__init__("Root", id=id)  # Initial placeholder
        # self.parent_app = parent_app
        self.note_tree = note_tree

        # self.COMPONENT_CLASSES.remove('tree--cursor')

        self._depth = 0  # 0: context node
        self._node = None
        self._first_widget_of_multiline = None
        self._last_widget_of_multiline = None

        # override the widget-wide icon nodes so that we can specify them individually
        self.ICON_NODE_EXPANDED = ""
        self.ICON_NODE = ""

        self._last_cursor = None

        self.age_gradient = Gradient((0, "red"), (1, "black"))

        global logging
        logging = self.app.logging

    def on_mount(self) -> None:
        """Called when the widget is added to the DOM."""
        # self._is_mounted = False

        self.center_scroll = True
        self.show_guides = False
        self.guide_depth = 4
        self.show_root = False
        self.auto_expand = False

        # logging.info("FIRST RENDERING...")
        self.render()
        # logging.info("DONE FIRST RENDERING")
        self.move_cursor_to_line(0)
        # self.note_tree.update_context(self.cursor_node._node)

    def set_styled_node_label(self, widget_node, is_cursor=False):

        # since this could be part of a multiline, start from the plain label
        text = widget_node.label.plain
        if not text:
            return
        if not hasattr(widget_node, "_node"):
            return

        _node = widget_node._node

        # arrow color/style
        arrow_str = ""
        if widget_node == widget_node._first_widget_of_multiline:
            text = text[1:]  # remove the existing arrow

            is_bookmarked = self.note_tree.determine_if_bookmarked(_node)

            if _node.is_collapsed or is_cursor:
                arrow_str = "▶"
            else:
                arrow_str = "►"

            if is_cursor:
                tag = (
                    self.app.get_theme_variable_defaults().get("cursor-arrow")
                    or "white"
                )
            # elif is_bookmarked:
            # elif _node.is_collapsed:
            # tag = self.app.get_theme_variable_defaults().get('HL3') or 'red'
            else:
                tag = (
                    self.app.get_theme_variable_defaults().get("default-arrow")
                    or "white"
                )

            arrow_str = f"[{tag}]{arrow_str}[/{tag}]"

        if _node.is_collapsed:
            text = text.replace("[•••]", "[white][•••][/white]")

        # completion coloring
        if _node.is_done():
            tag = self.app.get_theme_variable_defaults().get("dim-text") or "dim"
            text = f"[{tag}]{text}[/{tag}]"

        # highlighting
        if _node.is_highlighted():
            hashtag = _node.get_highlight_hashtag()
            hl = None
            if "HL1" == hashtag:
                hl = self.app.get_theme_variable_defaults().get("HL1") or "green"
            elif "HL2" == hashtag:
                hl = self.app.get_theme_variable_defaults().get("HL2") or "yellow"
            elif "HL3" == hashtag:
                hl = self.app.get_theme_variable_defaults().get("HL3") or "red"
            if hl:
                text = f"[{hl}]{text}[/{hl}]"

        if _node.depth == self.note_tree.context_node.depth + 1:
            text = f"[bold]{text}[/bold]"
        text = arrow_str + text

        try:
            widget_node.label = Text.from_markup(text)
        except Exception as e:
            logging.error("Text.from_markup failed: {e}")
            widget_node.label = Text.from_markup("ERROR")

    def build_tree(self, tree_widget, root_node, depth=0, target_widget=None):

        tree_widget._node = root_node
        tree_widget._depth = depth

        for node in root_node.children:
            if target_widget is not None and node != target_widget._node:
                continue

            insertion_index = None
            if target_widget:
                insertion_index = tree_widget.children.index(target_widget)
                target_widget.remove()

            text = node.get_text()

            is_done = node.is_done()

            # 2 for arrow + space
            # 4 for age strip + space
            available_width = self.app.size.width - (self.guide_depth * depth + 2 + 4)

            if node.is_collapsed:
                text += " [•••]"

            parts = textwrap.wrap(text, width=available_width)

            if depth == 0 and not node == root_node.children[0]:
                spacer_node = tree_widget.add("")
                spacer_node._node = node

            parts[0] = (
                "> " + parts[0]
            )  # use a placeholder arrow here, will be replaced when we apply line formatting

            if len(parts) > 1:
                child_widget = tree_widget.add(parts[0], before=insertion_index)
                child_widget._depth = depth + 1
                child_widget._node = node
                first_widget = child_widget
                first_widget.expand()

                for p in parts[1:]:
                    child_widget = tree_widget.add("  " + p, before=insertion_index)
                    child_widget._node = node
                    child_widget._depth = depth + 1
                    child_widget._first_widget_of_multiline = first_widget
                    self.set_styled_node_label(child_widget)

                first_widget._first_widget_of_multiline = first_widget
                first_widget._last_widget_of_multiline = child_widget

                self.set_styled_node_label(first_widget)

                child_widget._last_widget_of_multiline = child_widget

            else:
                child_widget = tree_widget.add(parts[0], before=insertion_index)
                child_widget._node = node
                child_widget._depth = depth + 1
                child_widget._first_widget_of_multiline = child_widget
                child_widget._last_widget_of_multiline = child_widget

                self.set_styled_node_label(child_widget)

            if not node.is_collapsed:
                self.build_tree(child_widget, node, depth=depth + 1)

            if not node.is_collapsed:
                child_widget.expand()

    def render(self, target_widget=None) -> None:
        """Load tab-indented data and populate the tree."""

        # TODO: move this somewhere else to be more efficient?
        if "age-color-0" in self.app.get_theme_variable_defaults():
            age_0 = self.app.get_theme_variable_defaults().get("age-color-0")
            age_1 = self.app.get_theme_variable_defaults().get("age-color-1")
            age_2 = self.app.get_theme_variable_defaults().get("age-color-2")

            self.age_gradient = Gradient((0, age_0), (0.5, age_1), (1, age_2))

        if target_widget is None:
            self.root.remove_children()  # Clear the tree before reloading

            # width = self.styles.width  # this gives a fraction "1fr"
            # width = self.app.size.width

            self.note_tree.update_wells()
            self.build_tree(self.root, self.note_tree.context_node, depth=0)
            logging.info(f"DONE building tree")

            self.app.status_bar.context_node = self.note_tree.context_node

        else:
            # target_widget.parent.remove_children()
            try:
                self.build_tree(
                    target_widget.parent,
                    target_widget.parent._node,
                    depth=target_widget.parent._depth,
                    target_widget=target_widget,
                )
            except AttributeError as e:
                logging.error(
                    f"Could not update tree for specified widget (defaulting to update all): {e}"
                )
                self.render()
            logging.info(f"DONE updating single tree node")

        self.app.status_bar.needs_saving = self.note_tree.has_unsaved_operations

    def update_location(self, context_node, line_node):
        self.note_tree.update_context(context_node, expand=True)
        # self.move_cursor_to_line(0)
        self.render()
        self._fix_cursor_position(line_node)

    def action_cycle_highlight(self):
        if not self.cursor_node:
            return

        self.cursor_node._node.cycle_highlight()
        self.render(target_widget=self.cursor_node)

    def action_toggle_done(self):
        if not self.cursor_node:
            return

        self.cursor_node._node.toggle_done()
        self.render(target_widget=self.cursor_node)

    def _fix_cursor_position(self, target_node):
        if not target_node:
            return
        # find where the cursor line should be
        for l in self._tree_lines:
            if not hasattr(l.path[-1], "_node"):
                continue
            candidate = l.path[-1]
            if candidate._node != target_node:
                continue
            if (
                hasattr(candidate, "_first_widget_of_multiline")
                and candidate._first_widget_of_multiline == candidate
            ):
                self.move_cursor(candidate)

    def action_indent(self):
        if not self.cursor_node:
            return

        _node = self.cursor_node._node

        self.note_tree.indent(self.cursor_node._node)
        self.render(target_widget=self.cursor_node.parent)

        self._fix_cursor_position(_node)

    def action_deindent(self):
        if not self.cursor_node:
            return

        _node = self.cursor_node._node
        self.note_tree.deindent(self.cursor_node._node)
        self.render()  # target_widget=self.cursor_node.parent.parent)

        self._fix_cursor_position(_node)

    def action_delete_node(self):
        if not self.cursor_node:
            return

        self.note_tree.delete_focus_node(self.cursor_node._node)
        self.render(target_widget=self.cursor_node.parent)

    def action_toggle_node(self):

        # node_widget = event.node
        if not self.cursor_node:
            return

        # logging.info(f"TOGGLING NODE: {self.cursor_node.label}")
        self.note_tree.update_wells()
        self.note_tree.toggle_collapse(self.cursor_node._node)
        self.render(target_widget=self.cursor_node)

    def action_add_note(self):

        if not self.cursor_node:
            return

        # logging.info(f"ADDING NOTE UNDER: {self.cursor_node._node.text[:20]}")
        _node = self.note_tree.contextual_add_new_note(self.cursor_node._node)
        self.render()

        # initiate editing of the node
        if _node:
            self._fix_cursor_position(_node)
            self.app.action_edit_note()

    def action_move_node(self, direction: str):
        if (
            self.cursor_node
            and hasattr(self.cursor_node, "_node")
            and self.cursor_node._node
        ):
            _node = self.cursor_node._node
            self.note_tree.move_line(_node, direction=direction)
            self.render(target_widget=self.cursor_node.parent)
            self._fix_cursor_position(_node)

    # def action_move_node_down(self):
    #     if self.cursor_node and hasattr(self.cursor_node, "_node") and self.cursor_node._node:
    #         _node = self.cursor_node._node
    #         self.note_tree.move_line(self.cursor_node._node, direction="down")
    #         self.render()
    #         self._fix_cursor_position(self.cursor_node._node)

    def on_resize(self, event) -> None:
        new_size = event.size
        # logging.info(f"Window resized to: {new_size.width} x {new_size.height}")
        # self.refresh()
        self.render()

    def action_zoom_in(self):
        if not self.cursor_node or not self.cursor_node._node.children:
            return
        if self.app.in_search_mode():
            return

        self.note_tree.update_context(self.cursor_node._node, expand=True)

        self.render()
        self.cursor_line = 0

        self._fix_cursor_position(self.note_tree.context_node.children[0])

    def action_zoom_out(self):
        if self.app.in_search_mode():
            return

        if not self.cursor_node:
            self.note_tree.update_context(
                self.note_tree.context_node.parent, expand=True
            )
            self.render()
            self.move_cursor_to_line(0)
            return

        if not self.cursor_node._node.parent:
            return

        current_node_list = self.note_tree.context_node.get_node_list(
            only_visible=True
        )[1:]
        # if the parent is already in the current context.. just switch lines
        if self.cursor_node._node.parent in current_node_list:
            self.move_cursor(self.cursor_node.parent)
            if self.cursor_node != self.cursor_node._first_widget_of_multiline:
                self.move_cursor(self.cursor_node._first_widget_of_multiline)
        elif self.cursor_line != 0:
            self.move_cursor_to_line(0)
        else:
            if self.note_tree.context_node.depth > 0:
                _node = self.note_tree.context_node  # self.cursor_node._node.parent
                self.note_tree.update_context(self.note_tree.context_node.parent)
                self.render()

                self._fix_cursor_position(_node)

    def action_cursor_down(self):
        # logging.info(f"CURSOR DOWN: {self.cursor_line}")
        # if self.cursor_line == -1:
        #     return
        if not self.note_tree.context_node.children:
            return

        for _ in range(10):

            if self.cursor_line < self.last_line:
                self.move_cursor_to_line(self.cursor_line + 1)
            elif self.cursor_line == self.last_line:
                self.move_cursor_to_line(0)

            if (
                self.cursor_node.label.plain.strip()
                and self.cursor_node._first_widget_of_multiline == self.cursor_node
            ):
                break

    def action_cursor_up(self):
        # logging.info(f"CURSOR UP: {self.cursor_line}")

        if not self.note_tree.context_node.children:
            return

        if not self.cursor_node:
            self.move_cursor_to_line(0)
            return

        for _ in range(10):
            if self.cursor_line > 0:
                self.move_cursor_to_line(self.cursor_line - 1)
            elif self.cursor_line == 0:
                self.move_cursor_to_line(self.last_line)

            if (
                self.cursor_node.label.plain.strip()
                and self.cursor_node._first_widget_of_multiline == self.cursor_node
            ):
                break

    def action_save(self):
        logging.info("SAVING")
        self.note_tree.save()
        self.app.status_bar.needs_saving = self.note_tree.has_unsaved_operations

    def add_journal_entry(self, text):
        new_node = self.note_tree.add_journal_entry(text)
        self.note_tree.context_node = new_node.parent  # self.cursor_node._node.parent
        self.move_cursor_to_line(0)
        # current_node = self.cursor_node._node
        self.render()

    def visit_bookmark(self, bookmark_index: int):

        _node = self.note_tree.jump_to_bookmark(bookmark_index)
        if _node:
            self.render()

            self._fix_cursor_position(_node)

    def toggle_bookmark(self):
        if not self.cursor_node:
            return
        _node = self.cursor_node._node
        self.note_tree.toggle_bookmark(_node)
        self.render(target_widget=self.cursor_node)

    def add_subtree(self, subtree_name: str):
        if not self.cursor_node or not self.cursor_node._node:
            return

        if subtree_name in SUBTREES:
            add_subtree(self.cursor_node._node, SUBTREES[subtree_name])

            self.render()

    def _render_line(self, y: int, x1: int, x2: int, base_style: Style) -> Strip:
        tree_lines = self._tree_lines
        width = self.size.width

        if y >= len(tree_lines):
            return Strip.blank(width, base_style)

        line = tree_lines[y]

        is_hover = self.hover_line >= 0 and any(node._hover for node in line.path)

        cache_key = (
            y,
            is_hover,
            width,
            self._updates,
            self._pseudo_class_state,
            tuple(node._updates for node in line.path),
        )
        if cache_key in self._line_cache:
            strip = self._line_cache[cache_key]
        else:
            # Allow tree guides to be explicitly disabled by setting color to transparent
            base_hidden = self.get_component_styles("tree--guides").color.a == 0
            hover_hidden = self.get_component_styles("tree--guides-hover").color.a == 0
            selected_hidden = (
                self.get_component_styles("tree--guides-selected").color.a == 0
            )

            base_guide_style = self.get_component_rich_style(
                "tree--guides", partial=True
            )
            guide_hover_style = base_guide_style + self.get_component_rich_style(
                "tree--guides-hover", partial=True
            )
            guide_selected_style = base_guide_style + self.get_component_rich_style(
                "tree--guides-selected", partial=True
            )

            hover = line.path[0]._hover
            selected = line.path[0]._selected and self.has_focus

            def get_guides(style: Style, hidden: bool) -> tuple[str, str, str, str]:
                """Get the guide strings for a given style.

                Args:
                    style: A Style object.
                    hidden: Switch to hide guides (make them invisible).

                Returns:
                    Strings for space, vertical, terminator and cross.
                """
                lines: tuple[Iterable[str], Iterable[str], Iterable[str], Iterable[str]]
                if self.show_guides and not hidden:
                    lines = self.LINES["default"]
                    if style.bold:
                        lines = self.LINES["bold"]
                    elif style.underline2:
                        lines = self.LINES["double"]
                else:
                    lines = ("  ", "  ", "  ", "  ")

                guide_depth = max(0, self.guide_depth - 2)
                guide_lines = tuple(
                    f"{characters[0]}{characters[1] * guide_depth} "
                    for characters in lines
                )
                return cast("tuple[str, str, str, str]", guide_lines)

            if is_hover:
                line_style = self.get_component_rich_style("tree--highlight-line")
            else:
                line_style = base_style

            line_style += Style(meta={"line": y})

            guides = Text(style=line_style)
            guides_append = guides.append

            guide_style = base_guide_style

            hidden = True
            for node in line.path[1:]:
                hidden = base_hidden
                if hover:
                    guide_style = guide_hover_style
                    hidden = hover_hidden
                if selected:
                    guide_style = guide_selected_style
                    hidden = selected_hidden

                space, vertical, _, _ = get_guides(guide_style, hidden)
                guide = space if node.is_last else vertical
                if node != line.path[-1]:
                    guides_append(guide, style=guide_style)
                hover = hover or node._hover
                selected = (selected or node._selected) and self.has_focus

            if len(line.path) > 1:
                _, _, terminator, cross = get_guides(guide_style, hidden)
                if line.last:
                    guides.append(terminator, style=guide_style)
                else:
                    guides.append(cross, style=guide_style)

            label_style = self.get_component_rich_style("tree--label", partial=True)
            if self.hover_line == y:
                label_style += self.get_component_rich_style(
                    "tree--highlight", partial=True
                )
            # if self.cursor_line == y:
            #     label_style += self.get_component_rich_style(
            #         "tree--cursor", partial=False
            #     )

            label = self.render_label(line.path[-1], line_style, label_style).copy()
            label.stylize(Style(meta={"node": line.node._id}))
            guides.append(label)

            age_char = "    "
            age_segment = Segment(age_char)
            if line.path[-1]._node:
                if line.path[
                    -1
                ].label.plain.strip() and self.note_tree.determine_if_bookmarked(
                    line.path[-1]._node
                ):
                    age_char = "▎💠 "  #
                else:
                    age_char = "▎   "
                age_days = line.path[-1]._node.get_days_old()
                age_color = self.age_gradient.get_color(min(1, age_days / 365)).hex
                age_bg = self.app.get_theme_variable_defaults().get("age-column-bg", "#1f170d")
                age_segment = Segment(age_char, Style(color=age_color, bgcolor=age_bg))

            segments = [age_segment] + list(guides.render(self.app.console))
            pad_width = max(self.virtual_size.width, width)
            segments = line_pad(segments, 0, pad_width - guides.cell_len, line_style)

            strip = self._line_cache[cache_key] = Strip(segments)

        strip = strip.crop(x1, x2)
        return strip

    def watch_cursor_line(self, previous_line: int, line: int) -> None:
        previous_node = self._get_node(previous_line)
        node = self._get_node(line)

        if previous_node and previous_node.label:
            self.set_styled_node_label(previous_node)

        if node and node.label:
            self.set_styled_node_label(node, is_cursor=True)

        # self.app.progress_bar.update(total=self.last_line, progress=line)

        if not node or not hasattr(node, "_node") or not node._node:
            self.app.status_bar.progress = (0, 0)
        else:
            try:
                self.app.status_bar.progress = (
                    self.note_tree.visible_node_list.index(node._node),
                    len(self.note_tree.visible_node_list) - 1,
                )
            except ValueError:
                logging.error(f"Node not in list: {node._node.text}")
        super().watch_cursor_line(previous_line, line)
