import logging
import subprocess
import time

from pytimeparse import parse

from utils import play_sound_effect


class Timer:
    """Manages a countdown timer with optional repeats."""

    def __init__(self, app):
        self._app = app
        self._end_time = None
        self._duration = None
        self._callback = None
        self._repeats_remaining = 0
        self._repeats_total = 0

    @property
    def is_running(self):
        return self._callback is not None

    def start(self, duration_str: str):
        """Start a timer. Accepts e.g. '5m', '1h30m', '25m 3x'."""
        # Parse optional repeat suffix (e.g. "5m 3x")
        repeats = 1
        parts = duration_str.strip().split()
        if len(parts) == 2 and parts[1].endswith("x"):
            try:
                repeats = int(parts[1][:-1])
                duration_str = parts[0]
            except ValueError:
                pass  # Not a valid repeat count, treat whole string as duration

        seconds = parse(duration_str)
        if seconds is None or seconds <= 0:
            self._app.notify(f"Invalid duration: {duration_str}", severity="error")
            return

        # Stop existing timer if any
        if self._callback:
            self._callback.stop()

        self._duration = seconds
        self._end_time = time.time() + seconds
        self._repeats_total = repeats
        self._repeats_remaining = repeats - 1  # current round counts as one
        self._callback = self._app.set_interval(0.5, self._update)
        self._update()  # Refresh display immediately

        if repeats > 1:
            self._app.notify(f"⏱ Timer started: {duration_str} x{repeats}")
        else:
            self._app.notify(f"⏱ Timer started: {duration_str}")

    def cancel(self):
        """Cancel the running timer."""
        if self._callback:
            self._stop()
            self._app.notify("⏱ Timer cancelled")
        else:
            self._app.notify("No timer running", severity="warning")

    def _update(self):
        """Tick callback — updates the status bar or fires completion."""
        if self._end_time is None:
            return

        remaining = self._end_time - time.time()
        if remaining <= 0:
            self._complete()
        else:
            mins, secs = divmod(int(remaining), 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                time_str = f"{hours}:{mins:02d}:{secs:02d}"
            else:
                time_str = f"{mins}:{secs:02d}"

            if self._repeats_total > 1:
                current_round = self._repeats_total - self._repeats_remaining
                time_str += f" ({current_round}/{self._repeats_total})"

            self._app.status_bar.timer_remaining = time_str

    def _complete(self):
        """Handle a single round completing. Restarts if repeats remain."""
        play_sound_effect("timer")

        if self._repeats_remaining > 0:
            current_round = self._repeats_total - self._repeats_remaining
            self._send_notification(
                f"Round {current_round}/{self._repeats_total} complete",
                urgency="low",
            )
            self._repeats_remaining -= 1
            self._end_time = time.time() + self._duration
            self._update()
        else:
            if self._repeats_total > 1:
                self._send_notification(
                    f"All {self._repeats_total} rounds complete!",
                    urgency="critical",
                )
            else:
                self._send_notification("Timer complete!", urgency="critical")
            self._stop()
            self._app.notify("⏱ Timer complete!", timeout=10)

    def _send_notification(self, message: str, urgency: str = "critical"):
        try:
            subprocess.Popen(
                ["notify-send", f"--urgency={urgency}", "--app-name=Forest", message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    def _stop(self):
        """Clear all timer state and hide the status bar display."""
        if self._callback:
            self._callback.stop()
        self._callback = None
        self._end_time = None
        self._duration = None
        self._repeats_remaining = 0
        self._repeats_total = 0
        self._app.status_bar.timer_remaining = None
