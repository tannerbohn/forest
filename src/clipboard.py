import base64
import logging
import os
import shutil
import subprocess
import sys

from utils import is_wsl

OSC52_LIMIT_BYTES = 74000


def _try_clipboard_tool(text: str) -> bool:
    candidates = []
    if is_wsl():
        candidates.append(["clip.exe"])
    if os.environ.get("WAYLAND_DISPLAY"):
        candidates.append(["wl-copy"])
    if os.environ.get("DISPLAY"):
        candidates.append(["xclip", "-selection", "clipboard"])
        candidates.append(["xsel", "--clipboard", "--input"])
    if sys.platform == "darwin":
        candidates.append(["pbcopy"])
    for argv in candidates:
        if not shutil.which(argv[0]):
            continue
        try:
            if argv[0] == "clip.exe":
                data = text.encode("utf-16-le")
            else:
                data = text.encode("utf-8")
            proc = subprocess.run(argv, input=data, check=True, timeout=2)
            if proc.returncode == 0:
                return True
        except Exception as e:
            logging.warning("Clipboard tool %s failed: %s", argv[0], e)
    return False


def copy_to_clipboard(text: str) -> bool:
    if text is None:
        return False
    if _try_clipboard_tool(text):
        return True
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if len(payload) > OSC52_LIMIT_BYTES:
        logging.warning(
            "OSC 52 payload is %d bytes; many terminals cap around %d and may reject it",
            len(payload),
            OSC52_LIMIT_BYTES,
        )
    seq = f"\x1b]52;c;{payload}\x07"

    term = os.environ.get("TERM", "")
    if os.environ.get("TMUX"):
        inner = seq.replace("\x1b", "\x1b\x1b")
        seq = f"\x1bPtmux;{inner}\x1b\\"
    elif term.startswith("screen"):
        inner = seq.replace("\x1b", "\x1b\x1b")
        seq = f"\x1bP{inner}\x1b\\"

    try:
        with open("/dev/tty", "w") as tty:
            tty.write(seq)
            tty.flush()
        return True
    except Exception:
        pass
    try:
        stream = sys.__stdout__ or sys.stdout
        stream.write(seq)
        stream.flush()
        return True
    except Exception as e:
        logging.error("Failed to write OSC 52 sequence: %s", e)
        return False
