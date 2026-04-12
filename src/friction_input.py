import time

from textual import events
from textual.widgets import Input


class FrictionInput(Input):
    """Input subclass that delays printable keystrokes during note edit.

    When the user is editing a note (not in command mode) and friction is
    enabled, characters typed faster than the configured interval are queued
    and released one by one with a delay, instead of being inserted instantly.
    Slow, deliberate typing is unaffected — the delay only kicks in when the
    user is currently outpacing the limit.

    Override is on `_on_key` (not `on_key`) because Textual's Input performs
    character insertion inside `_on_key` itself, not through a binding — so
    `on_key` runs too late to suppress the insert.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending_chars: list[str] = []
        self._release_timer = None
        self._last_release_ts: float = 0.0
        self._pause_detect_timer = None
        self._pause_reward_active: bool = False

    def reset(self) -> None:
        """Reset all friction state for a new edit session."""
        self._drop_pending()
        self._last_release_ts = 0.0
        self._cancel_pause_detect()
        self._clear_pause_reward()

    def _is_friction_active(self) -> bool:
        return (
            getattr(self.app, "_node_being_edited", None) is not None
            and self.app.config.friction_rate_limit_enabled
        )

    def _flush_pending(self) -> None:
        """Insert all queued chars at once and cancel the release timer."""
        if self._release_timer is not None:
            self._release_timer.stop()
            self._release_timer = None
        if self._pending_chars:
            self.insert_text_at_cursor("".join(self._pending_chars))
            self._pending_chars.clear()
            self._last_release_ts = time.monotonic()

    def _drop_pending(self) -> None:
        """Discard queued chars and cancel the release timer."""
        if self._release_timer is not None:
            self._release_timer.stop()
            self._release_timer = None
        self._pending_chars.clear()

    def _release_one(self) -> None:
        self._release_timer = None
        if not self._pending_chars:
            return
        ch = self._pending_chars.pop(0)
        self.insert_text_at_cursor(ch)
        self._last_release_ts = time.monotonic()
        if self._pending_chars:
            interval = self.app.config.friction_min_interval_ms / 1000.0
            self._release_timer = self.set_timer(interval, self._release_one)

    def _cancel_pause_detect(self) -> None:
        if self._pause_detect_timer is not None:
            self._pause_detect_timer.stop()
            self._pause_detect_timer = None

    def _start_pause_detect(self) -> None:
        """After each printable key, (re)start a 2s timer to show the reward."""
        self._cancel_pause_detect()
        self._pause_detect_timer = self.set_timer(2.0, self._show_pause_reward)

    def _show_pause_reward(self) -> None:
        """Activate the pause-reward cursor color."""
        self._pause_detect_timer = None
        self._pause_reward_active = True
        self.add_class("-friction-pause")

    def _clear_pause_reward(self) -> None:
        if self._pause_reward_active:
            self._pause_reward_active = False
            self.remove_class("-friction-pause")

    async def _on_key(self, event: events.Key) -> None:
        # Pause reward: show reward color after 2s of inactivity,
        # clear it when the user resumes typing.
        if (
            event.is_printable
            and getattr(self.app, "_node_being_edited", None) is not None
        ):
            self._clear_pause_reward()
            self._start_pause_detect()

        if (
            event.is_printable
            and event.character is not None
            and self._is_friction_active()
        ):
            now = time.monotonic()
            delay = self.app.config.friction_min_interval_ms / 1000.0
            # Slow typing: insert immediately when nothing is queued and
            # enough time has passed since the last released char.
            if not self._pending_chars and (now - self._last_release_ts) >= delay:
                self._last_release_ts = now
                await super()._on_key(event)
                return
            # Fast typing: suppress the immediate insert and queue the char.
            event.stop()
            event.prevent_default()
            self._pending_chars.append(event.character)
            self._restart_blink()
            if self._release_timer is None:
                wait = max(0.0, delay - (now - self._last_release_ts))
                self._release_timer = self.set_timer(wait, self._release_one)
            return
        # Non-printable key (backspace, arrows, enter, escape, tab, ...):
        # flush any pending chars so the buffer matches the user's mental
        # model before the key takes effect.
        if self._pending_chars:
            self._flush_pending()
        await super()._on_key(event)

    def _on_paste(self, event: events.Paste) -> None:
        if self._pending_chars:
            self._flush_pending()
        super()._on_paste(event)
