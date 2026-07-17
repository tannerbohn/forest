from datetime import datetime

from rich.text import Text
from textual.widgets import Static


class CommandInfoPanel(Static):
    """Single, transient line shown directly below the command input while in
    command mode. Reports the tree's last local edit (date + relative age) and
    the number of archived branches in the current context. Expiring notes now
    live in the InfoSidebar's journal view. Content is rebuilt each time command
    mode is entered (it is short-lived, so no interval refresh is needed)."""

    DEFAULT_CSS = """
    CommandInfoPanel {
        display: none;
        layer: overlay;
        offset: 0 1;
        width: 100%;
        height: auto;
        background: $surface;
        background-tint: $panel 10%;
        border-bottom: solid $foreground 20%;
        color: $foreground 30%;
        padding: 0 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    can_focus = False

    def _last_edit_part(self) -> Text | None:
        ctx = self.app.note_tree.context_node
        nodes = ctx.get_node_list(only_visible=False, hide_archive=False)
        times = [n.creation_time for n in nodes if n.creation_time is not None]
        if not times:
            return None
        newest = max(times)
        days = (datetime.now() - newest).days
        rel = "today" if days <= 0 else ("1d ago" if days == 1 else f"{days}d ago")
        t = Text()
        # t.append(newest.strftime("%Y-%m-%d"), style="dim")
        t.append(f"Branch last edited {rel}")
        return t

    def _leaf_q_part(self) -> Text | None:
        """Open-question leaves in the current context: leaf notes containing a
        `?`, excluding #DONE/#ARCHIVE. (Moved here from the bookmark rows.)"""
        ctx = self.app.note_tree.context_node
        questions = sum(
            1
            for n in ctx.get_node_list()
            if not n.children
            and "?" in n.text
            and not n.is_done()
            and not n.is_archived()
        )
        if not questions:
            return None
        return Text(f"{questions} leaf questions")

    def _archived_part(self) -> Text | None:
        ctx = self.app.note_tree.context_node
        nodes = ctx.get_node_list(only_visible=False, hide_archive=False)
        roots = [
            n
            for n in nodes
            if "#ARCHIVE" in n.text
            and n.parent is not None
            and "#ARCHIVE" not in n.parent.text
        ]
        if not roots:
            return None
        n = len(roots)
        return Text(f"{n} archived branch{'es' if n != 1 else ''}")

    def refresh_content(self) -> bool:
        """Rebuild the line from the current tree state. Returns True if there is
        anything to show (the caller only un-hides the panel when so)."""
        parts = [
            p
            for p in (
                self._last_edit_part(),
                self._leaf_q_part(),
                self._archived_part(),
            )
            if p
        ]
        if not parts:
            self.update("")
            return False
        line = Text(no_wrap=True, overflow="ellipsis")
        for i, part in enumerate(parts):
            if i:
                line.append("  ·  ", style="dim")
            line.append_text(part)
        self.update(line)
        return True
