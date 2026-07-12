from rich.style import Style
from rich.text import Text
from textual.color import Color
from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        background: $panel;
        color: $foreground 90%;
    }
    """

    progress = reactive((0, 0))
    context_node = reactive(None)
    needs_saving = reactive(False)
    hide_done = reactive(False)
    hide_archive = reactive(True)
    search_mode = reactive(False)
    search_progress = reactive((0, 0))
    timer_remaining = reactive(None)
    has_sticky_recovery = reactive(False)
    show_renew_hint = reactive(False)

    def render(self):

        hl = self.app.theme_variables["secondary"]
        progress_text = Text.from_markup(
            f" [dim][{hl}]{self.progress[0]}/{self.progress[1]}[/{hl}][/dim]"
        )

        if self.hide_done:
            hide_done_text = Text.from_markup(f" [{hl}]Ⓧ[/{hl}]")
        else:
            hide_done_text = Text.from_markup("")

        if not self.hide_archive:
            hide_archive_text = Text.from_markup(f" [{hl}]Ⓐ[/{hl}]")
        else:
            hide_archive_text = Text.from_markup("")

        if not self.needs_saving:
            needs_saving_text = Text("")
        else:
            hl = self.app.get_theme_variable_defaults().get("HL2") or "yellow"
            needs_saving_text = Text.from_markup(f" [dim][{hl}]\\[s]ave[/{hl}][/dim] ")

        # Renew hint, shown just left of [s]ave when the cursor is on an expired note.
        if self.show_renew_hint:
            hl = self.app.get_theme_variable_defaults().get("HL3") or "red"
            renew_hint_text = Text.from_markup(f" [dim][{hl}]\\[r]enew[/{hl}][/dim]")
        else:
            renew_hint_text = Text("")

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

            hint_text = Text("")

            remaining_width = (
                self.size.width - len(text.plain) - len(hint_text.plain) - 1
            )

            context_path = self.context_node.get_path_string(width=remaining_width)

            remaining_width -= len(context_path)

            text = (
                text
                + Text.from_markup(context_path + " " * remaining_width)
                + hint_text
            )
        else:
            start_text = Text.from_markup("🌲 ")

            cut_text = Text("")

            if self.has_sticky_recovery:
                hl_sec = self.app.theme_variables["secondary"]
                sticky_recovery_text = Text.from_markup(f" [{hl_sec}]⮺[/{hl_sec}]")
            else:
                sticky_recovery_text = Text("")

            end_text = (
                cut_text
                + timer_text
                + renew_hint_text
                + needs_saving_text
                + sticky_recovery_text
                + hide_done_text
                + hide_archive_text
                + progress_text
            )

            remaining_width = max(
                0,
                self.size.width - len(start_text.plain) - len(end_text.plain) - 1,
            )
            path_text = ""
            if self.context_node:
                path_text = self.context_node.get_path_string(width=remaining_width)
            path_text += " " * max(0, remaining_width - len(path_text))
            text = start_text + Text.from_markup(path_text) + end_text

            total = self.progress[1]
            if total > 0 and self.size.width > 0:
                p = max(0.0, min(1.0, self.progress[0] / total))
                filled_cells = round(p * self.size.width)
                if filled_cells > 0:
                    panel = Color.parse(
                        self.app.theme_variables.get("panel", "#000000")
                    )
                    fg = Color.parse(
                        self.app.theme_variables.get("foreground", "#ffffff")
                    )
                    fill_color = panel.blend(fg, 0.075).hex
                    text.stylize(Style(bgcolor=fill_color), 0, filled_cells)

        return text
