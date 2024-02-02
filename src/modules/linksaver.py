import _thread
import subprocess
import unicodedata
from datetime import datetime

import pyclip
from pynput.keyboard import Key, Listener


class LinkSaver:
    def __init__(self, parent):
        self.parent = parent

        self.key_stack = []

        self.hashes = {"DOWN:Key.cmd|DOWN:'l'|UP:'l'|UP:Key.cmd": self.handle_clipboard}

    def handle_clipboard(self):
        # print("CLIPBOARD:", str(pyclip.paste()))

        # tree_root = self.parent.search("Scratchpad")
        now = datetime.now()

        text = normalize_text(pyclip.paste().decode("utf-8"))

        # TODO: need to ensure existence of path
        year_root = self.parent.ensure_path(["Articles", now.strftime("%Y")])

        if is_url(text):
            time_str = now.strftime("%Y %B %d %I:%M %p")
            year_root.add_child(f"{time_str} - {text}")
            notification("Added new note", text)
        else:
            year_root.children[-1].add_child(text)
            notification("Extending note", text)

        self.parent.refresh()

    def _stack_add(self, key):
        self.key_stack.append(key)
        self.key_stack = self.key_stack[-4:]

        seq = "|".join(self.key_stack)

        callback = self.hashes.get(seq)
        # look for patterns

        if callback:
            callback()

    def on_press(self, key):
        # print(f"Pressed: {str(key)}")
        self._stack_add("DOWN:" + str(key))

    def on_release(self, key):
        # print(f"Released: {str(key)}")
        self._stack_add("UP:" + str(key))

    def start_listener(self):
        with Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            listener.join()

    def run(self):
        _thread.start_new_thread(self.start_listener, tuple())


def is_url(text):
    text = text.strip()

    if len(text.split()) > 1:
        return False

    pPos = text.rfind(".")
    if pPos != -1 and pPos != len(text) - 1:
        return True

    return False


def normalize_text(text):
    text = text.replace("`", "'")
    # lines = text.split('\n')
    # text = '\n'.join(lines)
    text = text.replace("\n", " ")
    # text = unicodedata.normalize('NFKD', unicode(text)).encode('ascii', 'ignore')
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    # print(type(text))
    return text.decode("utf-8")


def notification(title, msg):
    msg = "".join([ch if ord(ch) < 128 else "?" for ch in msg])

    cmdStr = 'notify-send "' + title + '" "' + msg + '" > /dev/null 2>&1 &'
    subprocess.call(cmdStr, shell=True)


if __name__ == "__main__":
    linksaver = LinkSaver(None)
    linksaver.run()
