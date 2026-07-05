import logging
import shutil
import subprocess
import sys


def _spawn(argv):
    try:
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logging.warning("Notification backend %s failed: %s", argv[0], e)
        return False


def _linux_notify(title: str, message: str, urgency: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    return _spawn(
        [
            "notify-send",
            f"--urgency={urgency}",
            "--app-name=Forest",
            title,
            message,
        ]
    )


def _macos_notify(title: str, message: str) -> bool:
    if not shutil.which("osascript"):
        return False
    safe_title = title.replace('"', '\\"')
    safe_msg = message.replace('"', '\\"')
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    return _spawn(["osascript", "-e", script])


def send_notification(title: str, message: str, urgency: str = "critical"):
    """Fire-and-forget desktop notification, best-effort across platforms."""
    if sys.platform == "darwin":
        if _macos_notify(title, message):
            return

    _linux_notify(title, message, urgency)
