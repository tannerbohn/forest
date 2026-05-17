import logging
import shutil
import subprocess
import sys

from utils import is_wsl


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


def _ps_escape(s: str) -> str:
    # Escape for a PowerShell single-quoted string, and for XML.
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("'", "''")
    )


def _windows_toast(title: str, message: str, urgency: str) -> bool:
    if not shutil.which("powershell.exe"):
        return False
    scenario = ' scenario="reminder"' if urgency == "critical" else ""
    actions = (
        "<actions><action content='Dismiss' arguments='dismiss' "
        "activationType='system'/></actions>"
        if urgency == "critical"
        else ""
    )
    xml = (
        f"<toast{scenario}><visual><binding template='ToastGeneric'>"
        f"<text>{_ps_escape(title)}</text>"
        f"<text>{_ps_escape(message)}</text>"
        f"</binding></visual>{actions}</toast>"
    )
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument,"
        "Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] > $null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('{xml}');"
        "$t = [Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]"
        "::CreateToastNotifier('Forest').Show($t);"
    )
    return _spawn(
        [
            "powershell.exe",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-Command",
            script,
        ]
    )


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
    if is_wsl():
        if shutil.which("wsl-notify-send.exe"):
            if _spawn(
                [
                    "wsl-notify-send.exe",
                    "--category",
                    urgency,
                    "--appId",
                    "Forest",
                    f"{title}: {message}",
                ]
            ):
                return
        if _windows_toast(title, message, urgency):
            return
        _linux_notify(title, message, urgency)
        return

    if sys.platform == "darwin":
        if _macos_notify(title, message):
            return

    _linux_notify(title, message, urgency)
