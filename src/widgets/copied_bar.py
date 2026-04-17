from textual.widgets import Static


class CopiedBar(Static):
    """A bottom panel showing copied notes, one per line. The top row is the
    current paste target (what `v` will paste). Press `C` to cycle the paste
    target, or `V` to move to the next copied note (also rotates the list)."""

    DEFAULT_CSS = """
    CopiedBar {
        dock: bottom;
        height: 1;
        background: $panel 50%;
        color: $foreground 50%;
        display: none;
        padding: 0 1;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_copied_nodes: list = []

    @property
    def nodes(self) -> list:
        return self.app.note_tree.copied_nodes

    def toggle(self, node) -> None:
        if node in self.nodes:
            self.nodes.remove(node)
        else:
            self.nodes.append(node)
        self.app.note_tree.has_unsaved_operations = True
        self.app.status_bar.needs_saving = True
        self.render_content(self.nodes)

    def prune(self) -> bool:
        live_ids = {
            id(n) for n in self.app.note_tree.root.get_node_list(only_visible=False)
        }
        self.nodes[:] = [n for n in self.nodes if id(n) in live_ids]
        return bool(self.nodes)

    def rotate(self) -> None:
        self.nodes[:] = [self.nodes[-1]] + self.nodes[:-1]
        self.app.note_tree.has_unsaved_operations = True
        self.app.status_bar.needs_saving = True

    def jump_to_next(self) -> None:
        if not self.nodes:
            self.app.notify("No copied notes.")
            return
        if not self.prune():
            self.render_content(self.nodes)
            return
        target = self.nodes[-1]
        self.rotate()
        self.app.note_tree_widget.update_location(
            context_node=target.parent if target.parent else target,
            line_node=target,
        )
        self.render_content(self.nodes)

    def cycle_target(self) -> None:
        if not self.nodes:
            self.app.notify("No copied notes.")
            return
        if not self.prune():
            self.render_content(self.nodes)
            return
        self.rotate()
        self.render_content(self.nodes)

    def render_content(self, copied_nodes: list) -> None:
        self._last_copied_nodes = copied_nodes
        if not copied_nodes:
            self.update("")
            self.styles.height = 0
            self.display = False
            return
        self.display = True
        self.styles.height = len(copied_nodes)
        hl1 = self.app.get_theme_variable_defaults().get("HL1", "white")
        hl2 = self.app.get_theme_variable_defaults().get("HL2", "yellow")
        hint_plain = "[c]opy [v]paste [C]ycle [V]isit"
        hint_markup = f"[b]\\[c]opy \\[v]paste \\[C]ycle \\[V]isit[/]"
        width = self.size.width or self.app.size.width
        max_len = max(20, width - 5)
        n = len(copied_nodes)
        lines = []
        for i, node in enumerate(copied_nodes[::-1]):
            is_bottom = i == n - 1
            # Bottom row reserves space for the right-aligned hint
            # (marker + space + text + space-pad + hint).
            row_max = max(1, width - len(hint_plain) - 3) if is_bottom else max_len
            if len(node.text) > row_max:
                txt = node.text[: max(1, row_max - 1)] + "…"
            else:
                txt = node.text
            marker = "v" if i == 0 else "•"
            visible_len = 2 + len(txt)  # marker + space + text
            body = f"[dim][{hl1}]{marker}[/][/] {txt}"
            if is_bottom:
                pad = max(1, width - visible_len - len(hint_plain))
                body = f"{body}{' ' * pad}{hint_markup}"
            lines.append(body)
        self.update("\n".join(lines))

    def on_resize(self, event) -> None:
        self.render_content(self._last_copied_nodes)
