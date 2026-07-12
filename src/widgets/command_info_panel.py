from datetime import datetime

from rich.console import Group
from rich.text import Text
from textual.widgets import Static


class CommandInfoPanel(Static):
    """Transient, full-width panel shown directly below the command input while
    in command mode. Lists the tree's expiring notes and the archived roots in
    the current context — the same data that used to live at the bottom of the
    InfoSidebar's bookmarks view. Content is rebuilt each time command mode is
    entered (it is short-lived, so no interval refresh is needed)."""

    DEFAULT_CSS = """
    CommandInfoPanel {
        display: none;
        layer: overlay;
        offset: 0 1;
        width: 100%;
        height: auto;
        max-height: 50%;
        background: $surface;
        background-tint: $panel 10%;
        color: $foreground 45%;
        border-bottom: solid $foreground 20%;
        padding: 0 1;
    }
    """

    can_focus = False

    def _row(self, marker: Text, body: str, style: str | None = None) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append_text(marker)
        t.append(" ")
        t.append(" ".join(body.split()), style=style or "")
        return t

    def _header(self, label: str) -> Text:
        return Text(label, style="bold", no_wrap=True, overflow="ellipsis")

    def _last_edit_rows(self):
        ctx = self.app.note_tree.context_node
        nodes = ctx.get_node_list(only_visible=False, hide_archive=False)
        times = [n.creation_time for n in nodes if n.creation_time is not None]
        if not times:
            return []
        newest = max(times)
        days = (datetime.now() - newest).days
        rel = "today" if days <= 0 else ("1d ago" if days == 1 else f"{days}d ago")
        rows = [self._header("Last local edit")]
        marker = Text.from_markup(f"[dim]{newest.strftime('%Y-%m-%d')}[/dim]")
        rows.append(self._row(marker, rel))
        return rows

    def _expiring_rows(self):
        nodes = sorted(
            self.app.note_tree.iter_timer_nodes(), key=lambda n: n.expiry_datetime
        )
        if not nodes:
            return []
        red = self.app.theme_variables.get("HL3", "red")
        rows = [self._header("Expiring")]
        for node in nodes:
            expired, label = node.expiry_status()
            loop = "↺" if node.expiry_recurring else ""
            if expired:
                marker = Text.from_markup(f"[dim {red}]+{label}{loop}[/dim {red}]")
                rows.append(self._row(marker, node.get_text(), style=f"dim {red}"))
            else:
                marker = Text.from_markup(f"[dim]{label}{loop}[/dim]")
                rows.append(self._row(marker, node.get_text()))
        return rows

    def _archived_rows(self):
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
            return []
        rows = [self._header("Local archived branches")]
        for node in roots:
            text = node.text.replace("#ARCHIVE", "").strip()
            marker = Text.from_markup("[dim]›[/dim]")
            rows.append(self._row(marker, text, style="dim"))
        return rows

    def refresh_content(self) -> bool:
        """Rebuild the panel from the current tree state. Returns True if there
        is anything to show (the caller only un-hides the panel when so)."""
        sections = [
            s
            for s in (
                self._last_edit_rows(),
                self._archived_rows(),
                self._expiring_rows(),
            )
            if s
        ]
        if not sections:
            self.update("")
            return False
        lines = []
        for i, section in enumerate(sections):
            if i:
                lines.append(Text(""))  # blank spacer between sections
            lines.extend(section)
        self.update(Group(*lines))
        return True
