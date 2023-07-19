# Author: Tanner Bohn

import _thread
import argparse
import curses
import json
import os
import random
import re
import textwrap
import time
from curses.textpad import Textbox, rectangle
from datetime import datetime

import pyclip
from cryptography.fernet import Fernet

"""
TODO:
    - highlight all question marks, not just the first one
        - https://stackoverflow.com/questions/4664850/how-to-find-all-occurrences-of-a-substring
    - have easy way to see all the different commands (persistent bar somewhere?)
        - on status bar, show possible commands. When in command mode, show command patterns
    - create github repo to share
    - create config file
        - color scheme
        - special words/regexs to highlight
"""


parser = argparse.ArgumentParser(description="Run Note Interface")
parser.add_argument("notes", help="a notes file (.txt)")
args = parser.parse_args()
notes_filename = args.notes


MONTH_ORDER = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

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

    def step(self):
        while True:
            if self.key and time.time() - self.key_get_time > self.key_ttl:
                self.tree.encrypt()
                self.key = None

            time.sleep(15)

    def run(self):
        _thread.start_new_thread(self.step, tuple())


class Node:
    def __init__(self, parent, text, depth=0, is_collapsed=False):
        self.parent = parent
        self.text = text
        self.children = []
        self.depth = depth
        self.is_collapsed = is_collapsed
        self.edit_mode = False

        self.bookmark_timestamp = None

        self.creation_time = datetime.now()

        self.index = 0

    def get_slug(self):
        """
        TODO: make this a property that only needs to be computed once? (and upon any change to the text)
        """
        if not self.text.startswith("#"):
            return
        # the slug consists of the first few words
        words = self.text[1:].split()
        words = [w for w in words if not w[0] == "#"]
        return "-".join(words[:3]).lower()

    def get_hashtags(self):
        if not "#" in self.text:
            return []

        matches = re.findall(r"#([a-z\-]+)", self.text)
        return matches

    def get_path(self, include_self):
        parts = []
        if include_self:
            parts.append(self.text)
        cur_node = self.parent
        while cur_node:
            parts.append(cur_node.text)
            cur_node = cur_node.parent

        return parts[::-1]

    def toggle_bookmark(self):
        if self.bookmark_timestamp is None:
            self.bookmark_timestamp = datetime.now().timestamp()
        else:
            self.bookmark_timestamp = None

    def is_done(self):
        if not self.parent:
            return "#DONE" in self.text
        return "#DONE" in self.text or self.parent.is_done()

    def toggle_done(self):
        if encryption_manager.is_encrypted(self.text):
            return

        words = self.text.split()

        if not self.is_done():
            words.append("#DONE")
            self.text = " ".join(words)
        else:
            if "#DONE" in words:
                words.remove("#DONE")
                self.text = " ".join(words)
            else:
                words.append("#DONE")
                self.text = " ".join(words)
            # if it is done, but there's no #DONE in the text, it means that a parent/ancestor is marked as done,
            #   in which case, don't do anything

    def is_bookmarked(self):
        return self.bookmark_timestamp is not None

    def get_days_old(self, recurse=False):
        days = (datetime.now() - self.creation_time).days
        if self.is_collapsed or recurse:
            return min([days] + [c.get_days_old(recurse=True) for c in self.children])
        else:
            return days

    def get_text(self, indentation=True):
        text = self.text
        if encryption_manager.is_encrypted(self.text):
            text = "█" * (len(self.text) // 5)
        if indentation:
            return "► " + text
        else:
            return text

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed

    def paste_node_here(self, node):
        if node == self:
            return
        node.parent.children.remove(node)

        node.parent = self

        self.children.insert(0, node)
        self.update_child_depth()

    def add_child(self, text, top=False, index=None):
        child = Node(self, text, self.depth + 1)
        if top:
            self.children = [child] + self.children
        elif index is not None:
            self.children.insert(index, child)
        else:
            self.children.append(child)
        return child

    def add_directly_below(self, is_context):
        # if the node doesn't have a parent, that can only mean it's the root node
        if not self.parent:
            return

        # if the node is the context node, that means that if we create a sibling node to it,
        #   we will be taken outside the current branch of the tree. Thus, any new node needs to
        #   be a child of the current/context node
        if is_context:
            new_node = self.add_child("", top=True)

        else:
            sibling_index = self.parent.children.index(self)
            new_node = self.parent.add_child("", index=sibling_index + 1)
            # if we create a new node DIRECTLY below the current node, that means we get between it and it's children,
            #   which means that the new node needs to adopt the children
            new_node.adopt_children_from_node(self)

        return new_node

    def find_bookmarked(self):
        if self.is_bookmarked():
            return self
        for c in self.children:
            n = c.find_bookmarked()
            if n:
                return n

    def delete_branch(self):
        if not self.parent:
            return
        self.parent.children.remove(self)

    def delete_single(self):
        if not self.parent:
            return

        if self not in self.parent.children:
            # something went wrong...
            return

        if self.parent.children and self.parent.children.index(self) != 0:
            # pass to preceding sibling
            sibling = self.parent.children[self.parent.children.index(self) - 1]
            sibling.adopt_children_from_node(self)
            self.parent.children.remove(self)

        else:
            # pass to parent
            self.parent.adopt_children_from_node(self)
            self.parent.children.remove(self)

    def update_child_depth(self):
        for c in self.children:
            c.depth = self.depth + 1
            c.update_child_depth()

    def adopt_children_from_node(self, node, only_uncollapsed=True):
        if node.is_collapsed:
            return
        self.children.extend(node.children)
        self.children = sorted(self.children, key=lambda k: k.index)
        for c in self.children:
            c.parent = self
        node.children = []
        self.update_child_depth()

    def move_shallower(self):
        # move up a level in the hierarchy
        parent = self.parent
        if parent is None:
            return
        grandparent = parent.parent
        if grandparent is None:
            return
        self.depth -= 1
        self.update_child_depth()
        parent.children.remove(self)
        self.parent = grandparent
        grandparent.children.insert(grandparent.children.index(parent) + 1, self)

    def move_deeper(self):
        parent = self.parent
        if parent is None:
            return
        siblings = parent.children

        sibling_index = siblings.index(self)
        if sibling_index == 0:
            return

        prev_sibling = siblings[sibling_index - 1]

        siblings.remove(self)

        self.depth += 1
        self.update_child_depth()
        self.parent = prev_sibling
        prev_sibling.children.append(self)

    def show(self):
        indentation = "\t" * self.depth
        print(f"{indentation}{self.get_text()}")
        for c in self.children:
            c.show()

    def get_node_list(self, only_visible=False):
        l = [self]
        if (not only_visible) or (only_visible and not self.is_collapsed):
            for c in self.children:
                l.extend(c.get_node_list(only_visible=only_visible))
        return l

    def start_edit_mode(self):
        self.edit_mode = True

    def stop_edit_mode(self):
        self.edit_mode = False

    def encrypt(self, force=False):
        already_encrypted = encryption_manager.is_encrypted(self.text)

        if already_encrypted or "#ENCRYPT" in self.text or force:
            if not already_encrypted:
                self.text = encryption_manager.encrypt(self.text)
            for c in self.children:
                c.encrypt(force=True)
        else:
            for c in self.children:
                c.encrypt()

    def decrypt(self):
        already_decrypted = not encryption_manager.is_encrypted(self.text)
        if not already_decrypted:
            self.text = encryption_manager.decrypt(self.text)
        for c in self.children:
            c.decrypt()


class NoteTree:
    def __init__(self, filename, stdscr, palette):
        self.filename = filename
        self.state_filename = f"{self.filename}_state.json"

        self.stdscr = stdscr

        self.palette = palette

        self.root = Node(parent=None, text=filename)
        with open(self.filename, "r") as f:
            lines = f.read().splitlines()

            cur_node = self.root

            prev_depth = -1
            for l in lines:
                print("Line:", l)
                if not l.strip():
                    print("\tskipping")
                    continue

                depth = len(l) - len(l.lstrip())

                # handle the case where we accidentally indent a little too much
                if depth > prev_depth:
                    depth = prev_depth + 1
                print(f"\tdepth = {depth}")

                text = l.strip()
                text = text.lstrip("- ")

                if depth > prev_depth:
                    print(f"\tDEEPER. Adding child")
                    child = cur_node.add_child(text)
                    cur_node = child
                elif depth == prev_depth:
                    print(f"\tSAME DEPTH. Adding sibling")
                    sibling = cur_node.parent.add_child(text)
                    cur_node = sibling
                elif depth < prev_depth:
                    # prev_depth = 1, depth = 3
                    nb_steps = prev_depth - depth
                    print(f"\tSHALLOWER BY {nb_steps}")
                    for _ in range(nb_steps):
                        cur_node = cur_node.parent
                    node = cur_node.parent.add_child(text)
                    cur_node = node

                prev_depth = depth

        node_list = self.index_nodes()

        creation_time_map = {}  # map from first 30 chars to creation time
        context_node = None
        if os.path.exists(self.state_filename):
            with open(self.state_filename, "r") as f:
                state = json.load(f)

                for index, suffix, properties in state:
                    matching_node = None
                    for prop in properties:
                        if isinstance(prop, str) and re.match(
                            r"\d{4}-\d{2}-\d{2}", prop
                        ):
                            creation_time_map[suffix] = datetime.strptime(
                                prop, "%Y-%m-%d"
                            )
                            continue

                        if not matching_node:
                            for i in range(
                                max(index - 5, 0), min(index + 5, len(node_list))
                            ):
                                node = node_list[i]
                                if node.text.endswith(suffix):
                                    matching_node = node
                                    break
                        if matching_node:
                            if prop == "collapsed":
                                matching_node.is_collapsed = True
                            elif prop == "context":
                                context_node = matching_node
                            elif isinstance(prop, list) and prop[0] == "bookmark":
                                matching_node.bookmark_timestamp = prop[1]

        for n in node_list:
            n.creation_time = creation_time_map.get(n.text[-30:], datetime.now())

        self.context_node = context_node or self.root
        self.visible_node_list = self.context_node.get_node_list(only_visible=True)
        self.focus_index = 0

        self.journal = None

        self.key = None

        self.cut_nodes = []

        self.has_unsaved_operations = False

    def index_nodes(self):
        node_list = self.get_node_list(only_visible=False)
        for i, node in enumerate(node_list):
            node.index = i
        return node_list

    def get_node_list(self, only_visible=False):
        return self.root.get_node_list(only_visible=only_visible)

    def show(self):
        self.root.show()

    def save(self):
        # apply encryption where needed
        self.encrypt()

        node_list = self.get_node_list(only_visible=False)

        states = []

        with open(self.filename, "w") as f:
            for i, node in enumerate(node_list):
                if node == self.root:
                    continue

                text = ("\t" * (node.depth - 1)) + "- " + node.text
                f.write(text + "\n")

                properties = []

                if node.is_collapsed:
                    properties.append("collapsed")

                if node == self.context_node:
                    properties.append("context")

                if node.bookmark_timestamp:
                    properties.append(("bookmark", node.bookmark_timestamp))

                properties.append(node.creation_time.strftime("%Y-%m-%d"))

                states.append((i, node.text[-30:], properties))

        with open(f"{self.filename}_state.json", "w") as f:
            json.dump(states, f, indent=4, default=str)

        self.has_unsaved_operations = False

    def toggle_bookmark(self):
        focus_node = self.visible_node_list[self.focus_index]
        focus_node.toggle_bookmark()
        self.has_unsaved_operations = True

    def toggle_done(self):
        focus_node = self.visible_node_list[self.focus_index]
        focus_node.toggle_done()
        self.has_unsaved_operations = True

    def decrypt(self):
        encryption_manager.ensure_key()
        if not encryption_manager.key:
            return

        self.root.decrypt()

    def encrypt(self):
        self.root.encrypt()
        self.render()

    def update_context(self, node, expand=False):
        self.context_node = node
        if expand:
            self.context_node.is_collapsed = False
        self.visible_node_list = self.context_node.get_node_list(only_visible=True)

        self.has_unsaved_operations = True

    def jump_to_random(self):
        # set focus_index and context_node
        node_list = self.root.get_node_list(only_visible=False)
        node_list = node_list[1:]  # remove the root node which has no parent
        if not node_list:
            return

        focus_node = random.choice(node_list)

        self.update_context(focus_node.parent, expand=True)

        self.focus_index = self.visible_node_list.index(focus_node)

    def find_matches(self, query):
        # find the node in the tree that best matches the query string

        node_list = self.get_node_list()

        matching_nodes = []

        for n in node_list:
            text = n.text.replace("-", " ").lower()  # remove dashes due to hashtags
            score = trigram_similarity(text, query.lower(), coverage_weight=0.75)
            if score:
                matching_nodes.append((n, score))

        # sort nodes from best to worst
        matching_nodes = sorted(matching_nodes, key=lambda el: -el[1])
        if not matching_nodes:
            return []
        else:
            top_score = matching_nodes[0][1]
            matching_nodes = [n for n, s in matching_nodes if s >= top_score * 0.75]

        return matching_nodes

    def find_bookmarks(self):
        node_list = self.get_node_list()
        bookmarks = [n for n in node_list if n.is_bookmarked()]
        bookmarks = sorted(bookmarks, key=lambda n: -n.bookmark_timestamp)
        return bookmarks

    def ensure_journal_existence(self):
        if not "Journal" in [c.text for c in self.root.children]:
            node = self.root.add_child("Journal")
            self.journal = node
            self.has_unsaved_operations = True
        else:
            for c in self.root.children:
                if c.text == "Journal":
                    self.journal = c
                    break

    def add_journal_entry(self, entry):
        self.ensure_journal_existence()
        if self.journal is None:
            assert False
        # add journal entry to the path Journal -> Year -> Month. And ensure that the entry is prepended with
        #   a timestamp like [2023-05-21 9:30 AM]
        now = datetime.now()

        first_word = entry.split()[0]
        if re.match(r"\d{4}-\d{2}-\d{2}", first_word):
            now = datetime.strptime(first_word, "%Y-%m-%d")
            entry = " ".join(entry.split()[1:])

        # make sure there's a branch in the journal for the current year
        year = str(now.year)
        month = now.strftime("%B")

        years = [c.text for c in self.journal.children]
        if not year in years:
            year_node = self.journal.add_child(year)
            self.journal.children = sorted(self.journal.children, key=lambda c: c.text)
        else:
            year_node = self.journal.children[years.index(year)]

        months = [c.text for c in year_node.children]
        if not month in months:
            month_node = year_node.add_child(month)
            year_node.children = sorted(
                year_node.children, key=lambda c: MONTH_ORDER.index(c.text)
            )
        else:
            month_node = year_node.children[months.index(month)]

        date_str = now.strftime("%Y-%m-%d %H:%M")
        entry = f"[{date_str}] {entry}"
        new_node = month_node.add_child(entry)

        self.index_nodes()

        self.has_unsaved_operations = True

        return new_node

    def move_up(self):
        self.focus_index = (self.focus_index - 1) % len(self.visible_node_list)

    def move_down(self):
        self.focus_index = (self.focus_index + 1) % len(self.visible_node_list)

    def move_right(self):
        self.update_context(self.visible_node_list[self.focus_index], expand=True)
        self.focus_index = 0
        self.has_unsaved_operations = True

    def move_left(self):
        focus_node = self.visible_node_list[self.focus_index]
        if focus_node.depth >= 1:
            if self.focus_index == 0:
                # if we're already at the context node, need to update visible nodes
                self.update_context(focus_node.parent, expand=True)
                # if focus_node in self.visible_node_list
                self.focus_index = self.visible_node_list.index(focus_node)
                self.has_unsaved_operations = True
            else:
                self.focus_index = self.visible_node_list.index(focus_node.parent)

    def toggle_collapse(self):
        focus_node = self.visible_node_list[self.focus_index]
        if focus_node.children:
            focus_node.toggle_collapse()
            self.visible_node_list = self.context_node.get_node_list(only_visible=True)
            self.has_unsaved_operations = True

    def contextual_add_new_note(self):
        focus_node = self.visible_node_list[self.focus_index]
        is_context = focus_node == self.context_node
        if (
            focus_node.children and not focus_node.is_collapsed
        ) or not focus_node.parent:
            new_node = focus_node.add_child("", top=True)
        else:
            new_node = focus_node.add_directly_below(is_context=is_context)

        if new_node:
            self.focus_index += 1
            new_node.start_edit_mode()
            self.index_nodes()
            self.visible_node_list = self.context_node.get_node_list(only_visible=True)
            self.has_unsaved_operations = True

    def deindent(self):
        focus_node = self.visible_node_list[self.focus_index]

        # we can only deindent if the focus node is not a direct child of the context node, otherwise,
        #   deindenting will make it move outside of the current context window
        if focus_node.parent != self.context_node:
            focus_node.move_shallower()
            self.index_nodes()
            self.visible_node_list = self.context_node.get_node_list(only_visible=True)
            self.has_unsaved_operations = True

    def indent(self):
        focus_node = self.visible_node_list[self.focus_index]
        focus_node.move_deeper()
        self.index_nodes()
        self.visible_node_list = self.context_node.get_node_list(only_visible=True)
        self.has_unsaved_operations = True

    def delete_focus_node(self):
        # TODO: what if we accidentally delete the context node?
        focus_node = self.visible_node_list[self.focus_index]
        if focus_node.is_collapsed:
            focus_node.delete_branch()
        else:
            focus_node.delete_single()
        self.index_nodes()
        self.visible_node_list = self.context_node.get_node_list(only_visible=True)
        self.focus_index = min(self.focus_index, len(self.visible_node_list) - 1)
        self.has_unsaved_operations = True

    def cut_focus_node(self):
        focus_node = self.visible_node_list[self.focus_index]
        # add the node to a cut list
        self.cut_nodes.append(focus_node)
        clipboard_contents = "\n".join(n.text for n in self.cut_nodes)

        # make the cut content accessible via clipboard (for external use)
        pyclip.copy(clipboard_contents)

    def paste(self):
        if self.cut_nodes:
            focus_node = self.visible_node_list[self.focus_index]
            for n in self.cut_nodes[::-1]:
                focus_node.paste_node_here(n)
            self.cut_nodes = []
            self.index_nodes()
            self.visible_node_list = self.context_node.get_node_list(only_visible=True)
            self.focus_index = min(self.focus_index, len(self.visible_node_list) - 1)
            self.has_unsaved_operations = True

    def find_hashtag_sources(self):
        # first extract the hashtags (not slugs)
        focus_node = self.visible_node_list[self.focus_index]
        hashtags = focus_node.get_hashtags()

        node_list = self.get_node_list()
        matching_nodes = [node for node in node_list if node.get_slug() in hashtags]

        if matching_nodes:
            matching_nodes.append(focus_node)
        return matching_nodes

    def find_hashtag_citations(self):
        focus_node = self.visible_node_list[self.focus_index]

        slug = focus_node.get_slug()
        if not slug:
            return []

        node_list = self.get_node_list()
        matching_nodes = [node for node in node_list if slug in node.get_hashtags()]

        if matching_nodes:
            matching_nodes.append(focus_node)

        return matching_nodes

    def draw_status_bar(self, match_index=None, total_matches=None, refresh=False):
        first_node = self.visible_node_list[0]
        ancestry = []
        while True:
            ancestry.append(first_node.get_text(indentation=False))
            first_node = first_node.parent
            if first_node is None:
                break

        # TODO: refine calculation of max_a_len
        max_a_len = int((curses.COLS) / len(ancestry))
        ancestry = [l[:max_a_len] for l in ancestry]

        path_text = " ▶ ".join(ancestry[::-1])

        match_text = ""
        if match_index is not None:
            match_text = f"[{match_index+1}/{total_matches}]"

        cut_text = ""
        if self.cut_nodes:
            cut_text = f"[{len(self.cut_nodes)} cut]"

        pct_text = f"{100*(self.focus_index + 1)/len(self.visible_node_list):.0f}%"

        unsaved_text = ""
        unsaved_changes_str = "[Unsaved changes]"
        if self.has_unsaved_operations:
            unsaved_text = unsaved_changes_str

        encryption_text = ""
        if encryption_manager.key:
            encryption_text = "[decrypted]"

        # we need to fit these on the bar:
        # path_text, match_text, cut_text, pct_text, unsaved_text, encryption_text

        left_text_parts = []
        if match_text:
            left_text_parts.append(match_text)
        if cut_text:
            left_text_parts.append(cut_text)
        if path_text:
            left_text_parts.append(path_text)

        top_text = "🌲 " + " ".join(left_text_parts)
        top_text = top_text.ljust(curses.COLS)

        right_text = " ".join([encryption_text, unsaved_text, pct_text])
        top_text = top_text[: -(len(right_text) + 1)] + right_text

        self.stdscr.addstr(0, 0, top_text, self.palette.top_bar | curses.A_BOLD)

        if unsaved_changes_str in top_text:
            # not sure why the +1 is needed for the x coord...
            self.stdscr.addstr(
                0,
                top_text.find(unsaved_changes_str) + 1,
                unsaved_changes_str,
                self.palette.status_section | curses.A_BOLD,
            )

    def render(self, command_mode=False, match_index=None, total_matches=None):
        # in the event that there have been collapses or deletions, make sure the focus index is still valid
        focus_node = self.visible_node_list[self.focus_index]

        y_offset = max(0, self.focus_index - curses.LINES // 2)

        if command_mode:
            edit_width = curses.COLS
            edit_start_col = 0

            editwin = curses.newwin(1, edit_width, 0, edit_start_col)

            editwin.addstr(0, 0, "")
            box = Textbox(editwin, insert_mode=True)

            # Let the user edit until Ctrl-G is struck.
            box.edit(self.command_edit_validator)

            # Get resulting contents
            message = box.gather()

            query_mode = message.startswith("?")
            bookmark_mode = message.strip() == "b"
            jump_to_sources = (
                message.strip() == "<"
            )  # given hashtags, go to slug locations
            jump_to_citations = (
                message.strip() == ">"
            )  # given slug, find hashtag references

            if (
                query_mode
                or bookmark_mode
                or jump_to_citations
                or jump_to_sources
            ):
                if query_mode:
                    query = message[1:].strip()
                    matching_nodes = self.find_matches(query=query)
                elif jump_to_sources:
                    matching_nodes = self.find_hashtag_sources()
                elif jump_to_citations:
                    matching_nodes = self.find_hashtag_citations()
                else:
                    matching_nodes = self.find_bookmarks()

                if not matching_nodes:
                    return self.render(command_mode=False)

                match_index = 0
                while True:
                    match = matching_nodes[match_index]
                    # set the new context to be the parent of the match
                    self.context_node = match.parent
                    self.context_node.is_collapsed = False
                    self.visible_node_list = self.context_node.get_node_list(
                        only_visible=True
                    )
                    self.focus_index = self.visible_node_list.index(match)
                    _ = self.render(
                        command_mode=False,
                        match_index=match_index,
                        total_matches=len(matching_nodes),
                    )

                    c = self.stdscr.getch()
                    encryption_manager.keep_alive()

                    if c in [curses.KEY_DOWN, curses.KEY_RIGHT]:
                        match_index = (match_index + 1) % len(matching_nodes)
                    elif c in [curses.KEY_UP, curses.KEY_LEFT]:
                        match_index = (match_index - 1) % len(matching_nodes)
                    else:
                        return self.render(command_mode=False)

            elif message.startswith("j+"):
                # add to journal

                journal_entry = message[2:].strip()

                new_node = self.add_journal_entry(journal_entry)
                self.context_node = new_node.parent
                self.context_node.is_collapsed = False
                self.visible_node_list = self.context_node.get_node_list()
                self.focus_index = self.visible_node_list.index(new_node)
                return self.render(command_mode=False)

            else:
                return self.render(command_mode=False)
        else:
            editwin = None
            edit_node = None
            edit_placeholder = None
            edit_rect_details = None
            edit_width = None
            edit_start_col = None

            root_depth = self.context_node.depth

            # how many characters will line numbers along the left require?
            line_num_chars = 3

            self.draw_status_bar(match_index=match_index, total_matches=total_matches)

            line_num = 1
            for node_index in range(y_offset + 1, len(self.visible_node_list)):
                is_focus = node_index == self.focus_index

                node = self.visible_node_list[node_index]
                is_done = node.is_done()

                age_text = "▌".ljust(line_num_chars)

                days_old = node.get_days_old()
                age_color = None
                if days_old <= 2:
                    age_color = self.palette.age_0
                elif days_old <= 7:
                    age_color = self.palette.age_1
                elif days_old <= 30:
                    age_color = self.palette.age_2
                elif days_old <= 356:
                    age_color = self.palette.age_3
                else:
                    age_color = self.palette.age_4

                bookmarked_node = node.find_bookmarked()

                is_last_child = node.parent.children[-1] == node
                text = (("    ") * (node.depth - root_depth - 1)) + node.get_text()
                if node.is_collapsed:
                    text = text + " [•••]"

                remaining_text = text
                is_first_chunk = True
                nb_chunks = 0
                while remaining_text:
                    line_start = age_text
                    if is_first_chunk:
                        is_first_chunk = False

                    max_chunk_size = curses.COLS - 0 - (line_num_chars)
                    # TODO: modify this to avoid splitting words under n chars
                    chunk = remaining_text[:max_chunk_size]
                    chunk = (line_start + chunk).ljust(curses.COLS)
                    remaining_text = remaining_text[max_chunk_size:]
                    remaining_text = (
                        (("    ") * (node.depth - root_depth - 1))
                        + "   "
                        + remaining_text
                    )
                    remaining_text = remaining_text.rstrip()

                    # first draw the full text
                    try:
                        formatting = curses.A_NORMAL
                        coloring = 0
                        if is_done:
                            formatting = formatting | curses.A_DIM

                        if node.depth == root_depth + 1:
                            formatting = formatting | curses.A_BOLD

                        if node in self.cut_nodes:
                            formatting = formatting | curses.A_UNDERLINE

                        self.stdscr.addstr(line_num, 0, chunk, formatting | coloring)

                        ch = "►"
                        if ch in chunk:
                            if is_focus:
                                self.stdscr.addstr(
                                    line_num,
                                    chunk.find(ch),
                                    "▶",
                                    formatting | self.palette.focus_arrow,
                                )
                            else:
                                self.stdscr.addstr(
                                    line_num,
                                    chunk.find(ch),
                                    ch,
                                    formatting | self.palette.nonfocus_arrow,
                                )

                        collapse_str = "[•••]"
                        if collapse_str in chunk:
                            self.stdscr.addstr(
                                line_num,
                                chunk.find(collapse_str),
                                collapse_str,
                                formatting
                                | self.palette.collapse_indicator
                                | curses.A_BOLD,
                            )

                        # apply hashtag coloring
                        if "#" in chunk:
                            matches = re.findall(r"\B#[a-zA-Z\-]+", chunk)
                            for m in matches:
                                if m in ["#DONE", "#ENCRYPT"]:
                                    continue
                                if node.text.startswith(m):
                                    coloring = self.palette.hashtag
                                    m = " ".join(node.text.split()[:3])
                                else:
                                    coloring = self.palette.hashtag
                                self.stdscr.addstr(
                                    line_num, chunk.find(m), m, formatting | coloring
                                )

                        if "?" in chunk:
                            self.stdscr.addstr(
                                line_num,
                                chunk.find("?"),
                                "?",
                                formatting | self.palette.question,
                            )

                        nb_chunks += 1
                    except:
                        raise Exception(f"[{curses.LINES}/{curses.COLS}]\n{chunk}")

                    # now overwrite the formatting for the line number part
                    try:
                        formatting = curses.A_NORMAL
                        coloring = age_color
                        self.stdscr.addstr(
                            line_num, 0, chunk[:line_num_chars], formatting | age_color
                        )
                    except:
                        raise Exception(f"[{curses.LINES}/{curses.COLS}]\n{chunk}")

                    # now draw the bookmark indicator strip
                    try:
                        formatting = curses.A_NORMAL
                        coloring = None
                        if bookmarked_node == node or (
                            bookmarked_node
                            and bookmarked_node not in self.visible_node_list
                        ):
                            coloring = self.palette.bookmark
                        if coloring is not None:
                            formatting = formatting | coloring
                            self.stdscr.addstr(line_num, 1, "🮋", formatting)
                    except:
                        raise Exception(f"[{curses.LINES}/{curses.COLS}]\n{chunk}")

                    line_num += 1

                    if line_num >= curses.LINES - 1:
                        break

                if node.edit_mode:
                    edit_width = (
                        curses.COLS
                        - 1
                        - (line_num_chars + 1)
                        - 4 * (node.depth - root_depth - 1)
                    )
                    edit_start_col = (
                        line_num_chars + 1 + 4 * (node.depth - root_depth - 1)
                    )

                    editwin = curses.newwin(
                        nb_chunks + 1, edit_width, line_num - nb_chunks, edit_start_col
                    )
                    edit_rect_details = (
                        line_num - nb_chunks - 1,
                        edit_start_col - 1,
                        line_num + 1,
                        curses.COLS - 1,
                    )

                    edit_node = node

                if line_num >= curses.LINES - 1:
                    break

                if node_index < len(self.visible_node_list) - 1:
                    next_depth = self.visible_node_list[node_index + 1].depth
                    if next_depth < root_depth + 2:
                        text = "▌" + " " * (curses.COLS - 1)

                        self.stdscr.addstr(
                            line_num, 0, text, curses.A_NORMAL | age_color
                        )
                        line_num += 1
                        if line_num >= curses.LINES - 1:
                            break

            while line_num < curses.LINES:
                text = " " * (curses.COLS - 1)
                self.stdscr.addstr(line_num, 0, text)
                line_num += 1

            self.stdscr.refresh()

            if editwin:
                self.stdscr.refresh()

                editwin.addstr(0, 0, textwrap.fill(edit_node.text, edit_width))
                box = Textbox(editwin, insert_mode=True)

                # Let the user edit until Ctrl-G or Enter is struck.
                box.edit(self.edit_validator)

                # Get resulting contents
                message = box.gather()
                message = message.replace("\n", "").strip()
                indent = message.startswith(">")
                deindent = message.startswith("<")
                message = message.lstrip(">")
                message = message.lstrip("<")

                message = re.sub(r"{YMD}", datetime.now().strftime("%Y-%m-%d"), message)
                message = re.sub(
                    r"{NOW}", datetime.now().strftime("%Y %B %d %I:%M %p"), message
                )

                edit_node.text = message
                edit_node.stop_edit_mode()

                if edit_node.text:
                    self.has_unsaved_operations = True

                    if indent:
                        self.indent()
                    elif deindent:
                        self.deindent()
                else:
                    self.delete_focus_node()

                return self.render()

        return

    @staticmethod
    def command_edit_validator(ch):
        # make it so that when the user presses enter, it's the same as ctrl-G (finish editing)
        if ch in [7, 10]:
            return 7
        return ch

    @staticmethod
    def edit_validator(ch):
        if ch == 9:  # tab
            return ">"
        if ch == 353:  # shift-tab
            return "<"
        # print(ch)
        if ch in [7, 10]:
            return 7

        return ch


class Palette:
    i = 50  # do not start at 0, because on some terminals, it messes up colours

    def create_color(self, color):
        if isinstance(color, str) and color[0] == "#":
            color = color[1:]
            r, g, b = tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))
        else:
            r, g, b = color
        self.i += 1
        curses.init_color(
            self.i, int(1000 * r / 256), int(1000 * g / 256), int(1000 * b / 256)
        )
        return self.i

    def create_pair(self, foreground, background):
        self.i += 1
        curses.init_pair(self.i, foreground, background)
        return curses.color_pair(self.i)

    def __init__(self, stdscr):
        self.background = self.create_color("#1f170d")
        self.light_background = self.create_color("#574832")

        self.default_text = self.create_color("#c9b597")
        self.highlight = self.create_color("#00b3ff")
        self.highlight_2 = self.create_color("#ffffff")

        # set the default background and foreground
        stdscr.bkgd(" ", self.create_pair(self.default_text, self.background))

        self.top_bar = self.create_pair(self.default_text, self.light_background)

        self.bookmark = self.create_pair(self.highlight_2, self.background)

        self.age_0_colour = self.create_color("#00b3ff")
        self.age_1_colour = self.create_color("#0793cd")
        self.age_2_colour = self.create_color("#0d749d")
        self.age_3_colour = self.create_color("#13556d")
        self.age_4_colour = self.create_color("#19363d")

        self.age_0 = self.create_pair(self.age_0_colour, self.background)
        self.age_1 = self.create_pair(self.age_1_colour, self.background)
        self.age_2 = self.create_pair(self.age_2_colour, self.background)
        self.age_3 = self.create_pair(self.age_3_colour, self.background)
        self.age_4 = self.create_pair(self.age_4_colour, self.background)

        self.hashtag = self.create_pair(self.highlight, self.background)
        self.focus_arrow = self.bookmark
        self.nonfocus_arrow = self.age_3
        self.status_section = self.create_pair(self.highlight, self.light_background)
        self.collapse_indicator = self.create_pair(self.highlight_2, self.background)

        question_colour = self.highlight_2
        self.question = self.create_pair(question_colour, self.background)


def trigram_similarity(w_a, w_b, coverage_weight=0.5):
    if not w_b:
        return 0
    # how well does w_a cover w_b
    w_a = w_a.lower()
    w_b = w_b.lower()

    # calculate intersection size of word bigrams
    set_a = set(zip(w_a[0:], w_a[1:], w_a[2:]))
    set_b = set(zip(w_b[0:], w_b[1:], w_b[2:]))

    if not set_a or not set_b:
        return 0

    n_intersect = len(set_a.intersection(set_b))

    coverage = n_intersect / len(set_b)
    similarity = n_intersect / len(set_a.union(set_b))

    return coverage * coverage_weight + similarity * (1 - coverage_weight)

def main(stdscr):
    palette = Palette(stdscr)

    T = NoteTree(notes_filename, stdscr, palette)

    encryption_manager.set_tree(T)
    encryption_manager.set_stdscr(stdscr)
    encryption_manager.run()

    T.render()

    # up, down, left right, space, a, s, d, r, enter, tab, backspace, b, x, del, ctrl-x, ctrl-v, esc, c, c-?, c-b, c-<, c->

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
            T.save()
        elif c == ord("d"):
            focus_node.decrypt()
        elif c == ord("r"):
            T.jump_to_random()
        elif c == ord("\n"):
            T.contextual_add_new_note()
        elif c == 353:  # shift-tab #curses.KEY_BACKSPACE:
            T.deindent()
        elif c == ord("\t"):
            T.indent()
        elif c == ord("c"):
            # start using commandline
            command_mode = True
        elif c == ord("b"):
            # bookmark
            T.toggle_bookmark()
        elif c == ord("x"):
            # toggle done state
            T.toggle_done()
        elif c == 330:  # delete
            T.delete_focus_node()
        elif c == 24:  # Ctrl-X: cut
            T.cut_focus_node()
        elif c == 22:  # Ctrl-V: paste
            T.paste()
        elif c == 0x1B:  # escape
            T.cut_nodes = []

        T.render(command_mode)


if __name__ == "__main__":
    encryption_manager = EncryptionManager()

    # Must happen BEFORE calling the wrapper, else escape key has a 1 second delay after pressing:
    os.environ.setdefault("ESCDELAY", "100")  # in mS; default: 1000

    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        exit()
