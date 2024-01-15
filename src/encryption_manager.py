import _thread
import curses
import time
from curses.textpad import Textbox, rectangle

from cryptography.fernet import Fernet


class EncryptionManager:
    def __init__(self):
        self.tree = None
        self.stdscr = None
        self.key = None
        self.key_get_time = 0
        self.key_ttl = 60 * 3

    def set_tree(self, tree):
        self.tree = tree  # need access to tree in order to call encryption

    def set_stdscr(self, stdscr):
        self.stdscr = stdscr

    def encrypt(self, message):
        self.ensure_key()
        if not self.key:
            return message
        return (
            Fernet(self.key).encrypt(message.encode()).decode()
        )  # encrypt but return a string

    def decrypt(self, message):
        self.ensure_key()
        if not self.key:
            return message
        return Fernet(self.key).decrypt(message.encode()).decode()

    def ensure_key(self):
        if self.key:
            self.keep_alive()
        else:
            key = self.ask_for_key()
            if key.endswith("="):
                self.key = key.encode()
                self.keep_alive()  # if we've requested the key, let it live longer

    def ask_for_key(self):
        y = curses.LINES // 2
        x_start = curses.COLS // 4
        edit_rect_details = (
            y - 1,  # upper left y
            x_start - 1,  # upper left x
            y + 1,  # bottom right y
            curses.COLS - x_start - 1,  # bottom right x
        )
        rectangle(self.stdscr, *edit_rect_details)
        self.stdscr.refresh()

        editwin = curses.newwin(
            1,  # height
            curses.COLS // 2,  # width
            y,  # start y
            x_start,  # start x
        )

        box = Textbox(editwin, insert_mode=True)

        accumulated_input = []

        # Let the user edit until Ctrl-G or Enter is struck.
        def key_validator(ch):
            if ch in [7, 10]:
                return 7  # for ctrl-G/terminate
            if ch == curses.KEY_BACKSPACE:
                try:
                    accumulated_input.pop()
                except IndexError:
                    pass
                return ch
            accumulated_input.append(chr(ch))
            return "*"

        box.edit(key_validator)

        message = "".join(accumulated_input)

        return message

    @staticmethod
    def is_encrypted(message):
        return message.startswith("gAAAAAB")

    def keep_alive(self):
        if self.key:
            self.key_get_time = time.time()

    # def step(self):
    #     while True:
    #         if self.key and time.time() - self.key_get_time > self.key_ttl:
    #             self.tree.encrypt()
    #             self.key = None

    #         time.sleep(15)

    def run(self):
        # _thread.start_new_thread(self.step, tuple())
        return


encryption_manager = EncryptionManager()
