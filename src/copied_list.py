class CopiedList:
    def __init__(self, app):
        self.app = app

    @property
    def nodes(self) -> list:
        return self.app.note_tree.copied_nodes

    def _refresh_sidebar(self) -> None:
        sidebar = getattr(self.app, "info_sidebar", None)
        if sidebar is None or not sidebar.display:
            return
        if sidebar._search_results:
            return
        sidebar.update_data()

    def toggle(self, node) -> None:
        if node in self.nodes:
            self.nodes.remove(node)
            self.app.note_tree.remove_bookmark_for(node)
        else:
            self.nodes.append(node)
        self.app.note_tree.has_unsaved_operations = True
        self.app.status_bar.needs_saving = True
        self._refresh_sidebar()

    def prune(self) -> bool:
        live_ids = {
            id(n) for n in self.app.note_tree.root.get_node_list(only_visible=False)
        }
        self.nodes[:] = [n for n in self.nodes if id(n) in live_ids]
        return bool(self.nodes)

    def rotate(self) -> None:
        # Only rotate the non-bookmarked tail; bookmarked nodes stay pinned
        # at the start of the list (= bottom of sidebar) in their order.
        k = self.app.note_tree.bookmark_split_index()
        tail = self.nodes[k:]
        if len(tail) <= 1:
            return
        self.nodes[k:] = [tail[-1]] + tail[:-1]
        self.app.note_tree.has_unsaved_operations = True
        self.app.status_bar.needs_saving = True

    def jump_to_next(self) -> None:
        if not self.nodes:
            self.app.notify("No copied notes.")
            return
        if not self.prune():
            self._refresh_sidebar()
            return
        target = self.nodes[-1]
        self.rotate()
        self.app.note_tree_widget.update_location(
            context_node=target.parent if target.parent else target,
            line_node=target,
        )
        self._refresh_sidebar()

    def cycle_target(self) -> None:
        if not self.nodes:
            self.app.notify("No copied notes.")
            return
        if not self.prune():
            self._refresh_sidebar()
            return
        self.rotate()
        self._refresh_sidebar()
