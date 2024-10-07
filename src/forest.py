# Author: Tanner Bohn

import _thread
import argparse
import curses
import json
import os

from encryption_manager import encryption_manager
# from modules.linksaver import LinkSaver
from note_tree import NoteTree
from palette import Palette

"""
TODO:
    - highlight all question marks, not just the first one
        - https://stackoverflow.com/questions/4664850/how-to-find-all-occurrences-of-a-substring
    - have easy way to see all the different commands (persistent bar somewhere?)
        - on status bar, show possible commands. When in command mode, show command patterns
        - hijack the bookmarks panel?
"""


parser = argparse.ArgumentParser(description="Run Note Interface")
parser.add_argument("notes", help="a notes file (.txt)")
args = parser.parse_args()
notes_filename = args.notes
T = None


def main(stdscr):
    global T

    # curses.curs_set(False)
    # curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)

    with open("colour_schemes.json", "r") as f:
        colour_schemes = json.load(f)

    with open("config.json", "r") as f:
        config = json.load(f)

    colour_scheme = colour_schemes[config.get("colour_scheme", "brown_and_blue")]
    assert colour_scheme

    T = NoteTree(
        notes_filename,
        stdscr,
        palette=Palette(stdscr, colour_scheme),
    )

    # T.add_plugin(LinkSaver)
    T.run_plugins()

    encryption_manager.set_tree(T)
    encryption_manager.set_stdscr(stdscr)
    encryption_manager.run()

    T.render()

    last_ch = None
    while True:
        c = stdscr.getch()
        encryption_manager.keep_alive()

        focus_node = T.visible_node_list[T.focus_index]

        command_mode = False
        if c == curses.KEY_UP:
            T.move_up()
        elif c == curses.KEY_DOWN:
            T.move_down()
        elif c == curses.KEY_RIGHT:
            T.move_right()
        elif c == curses.KEY_LEFT:
            T.move_left()
        elif c == ord(" "):
            T.toggle_collapse()
        elif c == ord("a") or c == curses.KEY_BACKSPACE:
            focus_node.start_edit_mode()
        elif c == ord("s"):
            # can alsu use command mode: "save"
            T.save()
        elif c == ord("r"):
            # can also use command mode "random"
            T.jump_to_random()
        elif c == ord("\n"):
            T.contextual_add_new_note()
        elif c == 353:  # shift-tab #curses.KEY_BACKSPACE:
            T.deindent()
        elif c == ord("\t"):
            T.indent()
        elif c == ord(":"):
            # start using commandline
            command_mode = True
        elif c == ord("x"):
            # toggle done state
            T.toggle_done()
        elif c == ord("!"):  # 0: ctrl-space #ord("b"):
            # toggle bookmark status of current focus node
            T.toggle_bookmark()
        elif c == ord("h"):
            # cycle highlight status of current focus node (switch between colours)
            T.cycle_highlight()
        elif c == 330:  # delete
            T.delete_focus_node()
        elif c == 24:  # Ctrl-X: cut
            T.cut_focus_node()
        elif c == 22:  # Ctrl-V: paste
            T.paste()
        elif c == 0x1B:  # escape
            T.cut_nodes = []
        elif c == 96:  # ` button
            T.toggle_bookmark_panel()
        elif c >= 48 and c <= 57:
            index = c - 48
            T.jump_to_bookmark(index)
        elif c == ord("u"):
            T.move_line("up")
        elif c == ord("d"):
            T.move_line("down")
        # elif c == curses.KEY_RESIZE and not last_ch == curses.KEY_RESIZE:
        #     curses.resizeterm(*stdscr.getmaxyx())
        #     stdscr.clear()
        #     stdscr.refresh()
        #     focus_node.text = f"RESIZE: {curses.COLS}, {curses.LINES}"
        # elif c == curses.KEY_MOUSE:
        #     _, x, y, _, button = curses.getmouse()
        #     focus_node.text = f"{button}: {x}, {y}"
        # else:
        #     focus_node.text = str(c)

        last_ch = c

        T.render(command_mode)


if __name__ == "__main__":
    # Must happen BEFORE calling the wrapper, else escape key has a 1 second delay after pressing:
    os.environ.setdefault("ESCDELAY", "100")  # in mS; default: 1000

    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        exit()
