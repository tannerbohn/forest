import curses
import json
import os
import random
import re
import textwrap
from curses.textpad import Textbox
from datetime import datetime

import pyclip

from encryption_manager import encryption_manager
from node import Node
from subtrees import subtrees
from utils import (
    MONTH_ORDER,
    convert_to_nested_list,
    determine_state_filename,
    normalize_indentation,
    trigram_similarity,
)

EDIT_MODE_ESC = False


class NoteTree:
    def __init__(self, filename, stdscr, palette):
        self.filename = filename

        self.state_filename = determine_state_filename(filename)

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

        self.bookmarks: dict[int, Node] = {}
        self.bookmark_last_use_times: dict[int, datetime] = {}

        creation_time_map = {}  # map from first 30 chars to creation time
        context_node = None
        if os.path.exists(self.state_filename):
            with open(self.state_filename, "r") as f:
                state = json.load(f)

                for index, key, properties in state:
                    matching_node = None
                    for prop in properties:
                        if isinstance(prop, str) and re.match(
                            r"\d{4}-\d{2}-\d{2}", prop
                        ):
                            creation_time_map[key] = datetime.strptime(prop, "%Y-%m-%d")
                            continue

                        # TODO: improve the matching process?
                        if not matching_node:
                            for i in range(
                                max(index - 15, 0), min(index + 15, len(node_list))
                            ):
                                node = node_list[i]
                                if (
                                    node.get_key() == key
                                ):  # TODO: can store a mapping from i -> hash if this needs to be faster
                                    # if node.text[-30:] == key:
                                    matching_node = node
                                    break
                        if matching_node:
                            if prop == "collapsed":
                                matching_node.is_collapsed = True
                            elif prop == "context":
                                context_node = matching_node
                            elif isinstance(prop, list) and prop[0] == "bookmark":
                                self.bookmarks[prop[1]] = matching_node
                                self.bookmark_last_use_times[prop[1]] = (
                                    datetime.fromtimestamp(prop[2])
                                )

        for n in node_list:
            n.creation_time = creation_time_map.get(n.get_key(), datetime.now())
            # n.creation_time = creation_time_map.get(n.text[-30:], datetime.now())

        self.context_node = context_node or self.root
        self.visible_node_list = self.context_node.get_node_list(only_visible=True)
        self.focus_index = 0

        self.journal = None

        self.key = None

        self.show_bookmark_panel = False

        self.cut_nodes = []

        self.has_unsaved_operations = False

        self.plugins = []

        self.remove_expired_notes()

    def save(self):
        # apply encryption where needed
        self.encrypt()

        self.remove_expired_notes()

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

                if node in self.bookmarks.values():
                    for k, _node in self.bookmarks.items():
                        if node == _node:
                            last_use_time = self.bookmark_last_use_times[k].timestamp()
                            properties.append(("bookmark", k, last_use_time))
                            break

                properties.append(node.creation_time.strftime("%Y-%m-%d"))

                # states.append((i, node.text[-30:], properties))
                states.append((i, node.get_key(), properties))

        with open(self.state_filename, "w") as f:
            json.dump(states, f, indent=4, default=str)

        self.has_unsaved_operations = False

    def index_nodes(self):
        node_list = self.get_node_list(only_visible=False)
        for i, node in enumerate(node_list):
            node.index = i
        return node_list

    def get_node_list(self, only_visible=False):
        return self.root.get_node_list(only_visible=only_visible)

    def remove_expired_notes(self):
        focus_node = self.visible_node_list[self.focus_index]
        # TODO: need to account for possibility that context node is also removed out from under us
        self.root.remove_expired_notes()
        node_list = self.index_nodes()

        while self.context_node not in node_list:
            self.context_node = self.context_node.parent

        self.visible_node_list = self.context_node.get_node_list(only_visible=True)

        if focus_node in self.visible_node_list:
            self.focus_index = self.visible_node_list.index(focus_node)
        else:
            while focus_node not in self.visible_node_list:
                focus_node = focus_node.parent

            if focus_node is None:
                self.focus_index = 0
            else:
                self.focus_index = self.visible_node_list.index(focus_node)

        # focus_node = self.visible_node_list[self.focus_index]
        # index = focus_node.parent.children.index(focus_node)

    def search(self, text):
        to_search = self.root.children
        while to_search:
            for node in list(to_search):
                if node.text == text:
                    return node
                _ = to_search.pop(0)
                to_search.extend(node.children)
        return None

    def show(self):
        self.root.show()

    def toggle_done(self):
        focus_node = self.visible_node_list[self.focus_index]
        focus_node.toggle_done()
        self.has_unsaved_operations = True

    def cycle_highlight(self):
        focus_node = self.visible_node_list[self.focus_index]
        focus_node.cycle_highlight()
        self.has_unsaved_operations = True

    def toggle_bookmark_panel(self):
        self.show_bookmark_panel = not self.show_bookmark_panel

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
        node_list = self.context_node.get_node_list(only_visible=False)
        node_list = node_list[1:]  # remove the root node
        if not node_list:
            return

        focus_node = random.choice(node_list)

        parent = focus_node.parent
        while parent != self.context_node:
            parent.is_collapsed = False
            parent = parent.parent

        self.visible_node_list = self.context_node.get_node_list(only_visible=True)
        # self.update_context(focus_node.parent, expand=True)

        self.focus_index = self.visible_node_list.index(focus_node)

    def find_matches(self, query, global_scope=True):
        # find the node in the tree that best matches the query string

        if global_scope:
            node_list = self.get_node_list()
        else:
            node_list = self.context_node.get_node_list(only_visible=False)

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

        if entry.strip():
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

    def ensure_path(self, text_list):
        return self.root.ensure_path(text_list)

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

    def move_line(self, direction):
        focus_node = self.visible_node_list[self.focus_index]
        index = focus_node.parent.children.index(focus_node)
        if direction == "up" and index > 0:
            n = focus_node.parent.children.pop(index)
            focus_node.parent.children.insert(index - 1, n)
            self.has_unsaved_operations = True
        elif direction == "down" and index < len(focus_node.parent.children) - 1:
            n = focus_node.parent.children.pop(index)
            focus_node.parent.children.insert(index + 1, n)
            self.has_unsaved_operations = True

        self.visible_node_list = self.context_node.get_node_list(only_visible=True)
        self.focus_index = self.visible_node_list.index(focus_node)

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

    def deindent(self, count=1):
        for _ in range(count):
            focus_node = self.visible_node_list[self.focus_index]

            # we can only deindent if the focus node is not a direct child of the context node, otherwise,
            #   deindenting will make it move outside of the current context window
            if focus_node.parent != self.context_node:
                focus_node.move_shallower()
                self.index_nodes()
                self.visible_node_list = self.context_node.get_node_list(
                    only_visible=True
                )
                self.has_unsaved_operations = True

    def indent(self, count=1):
        for _ in range(count):
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
        # pyclip.copy(clipboard_contents)

    def paste(self):
        if self.cut_nodes:
            focus_node = self.visible_node_list[self.focus_index]
            for n in self.cut_nodes[::-1]:
                focus_node.paste_node_here(n)
            self.cut_nodes = []
        else:
            self.paste_from_clipboard()

        self.index_nodes()
        self.visible_node_list = self.context_node.get_node_list(only_visible=True)
        self.focus_index = min(self.focus_index, len(self.visible_node_list) - 1)
        self.has_unsaved_operations = True

    def paste_from_clipboard(self):
        # TODO: let this use ctrl-v -- use content to determine whether to use cut nodes or to use clipboard
        # get clipboard contents
        try:
            text = pyclip.paste(text=True)
        except:
            # doesn't seem to wrk on all systems
            return

        # if we can convert the text into a nested list, we should be able to use the existing subtree pasting method
        lines = text.splitlines()

        # normalize indentation to work with lists from multiple sources
        lines = normalize_indentation(lines)

        nested_list = convert_to_nested_list(lines)

        focus_node = self.visible_node_list[self.focus_index]

        insert_nested_list(focus_node, nested_list)

    def find_hashtag_sources(self):
        # first extract the hashtags (not slugs)
        focus_node = self.visible_node_list[self.focus_index]
        hashtags = focus_node.get_hashtags()

        node_list = self.get_node_list()
        matching_nodes = [node for node in node_list if node.get_slug() in hashtags]

        if matching_nodes:
            matching_nodes.append(focus_node)
        return matching_nodes

    def add_note_from_telegram(self, message):
        return f"Adding: {message}"

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

    def toggle_bookmark(self):
        node = self.visible_node_list[self.focus_index]
        if node in self.bookmarks.values():
            index = [k for k, n in self.bookmarks.items() if n == node][0]
            del self.bookmarks[index]
            del self.bookmark_last_use_times[index]
            self.has_unsaved_operations = True
        else:
            # find the first index that isn't user
            new_index = None
            for index in range(0, 10):
                if not index in self.bookmarks:
                    new_index = index
                    break
            if new_index is None:
                # replace the bookmark that hasn't been used in the longest time
                new_index = sorted(
                    self.bookmark_last_use_times,
                    key=lambda index: self.bookmark_last_use_times[index],
                )[0]

            self.bookmarks[new_index] = node
            self.bookmark_last_use_times[new_index] = datetime.now()
            self.has_unsaved_operations = True

    def jump_to_bookmark(self, index):
        if index in self.bookmarks:
            # self.context_node = self.bookmarks[index]
            # self.context_node.is_collapsed = False
            # self.visible_node_list = self.context_node.get_node_list()
            # self.focus_index = 0

            focus_node = self.bookmarks[index]
            self.bookmark_last_use_times[index] = datetime.now()

            if focus_node.parent:
                self.update_context(focus_node.parent, expand=True)
            else:
                self.update_context(focus_node, expand=True)

            self.focus_index = self.visible_node_list.index(focus_node)

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

        # pct_text = f"{100*(self.focus_index + 1)/len(self.visible_node_list):.0f}%"
        pct_text = f"{(self.focus_index + 1)}/{len(self.visible_node_list)}"

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

    def draw_bookmark_panel(self):
        start_line = 1  # curses.LINES//3
        nb_lines = (
            curses.LINES - start_line
        )  # 0 if not self.bookmarks else 1+max(self.bookmarks)
        panel_width = curses.COLS // 3

        start_col = curses.COLS - panel_width

        # indices = list(range(nb_lines))
        # if indices:
        #     indices = indices[1:] + [indices[0]]

        formatting = curses.A_BOLD  # self.palette.top_bar | curses.A_BOLD
        self.stdscr.addstr(
            start_line, start_col, "│ Bookmarks".ljust(panel_width), formatting
        )

        # locate the oldest bookmark
        if self.bookmark_last_use_times:
            oldest_index = sorted(
                self.bookmark_last_use_times,
                key=lambda index: self.bookmark_last_use_times[index],
            )[0]
        else:
            oldest_index = None

        nb_bookmarks = 10
        cur_y = None
        for index in range(nb_bookmarks):
            y_offset = index  # (index - 1) % 10

            node = self.bookmarks.get(index)
            text = node.text if node else ""
            y = y_offset + start_line + 1
            x = 0 + start_col

            text = f"│ {index}. {text}"
            text = text[:panel_width]
            text = text.ljust(panel_width)

            # if index == oldest_index:
            #     formatting = curses.A_BOLD | curses.A_DIM
            # else:
            #     formatting = (
            #         curses.A_BOLD
            #     )  # self.palette.top_bar # | curses.A_BOLD  # status_section

            self.stdscr.addstr(y, x, text)  # , formatting)

            cur_y = y

        has_bookmark_zero = 0 in self.bookmarks
        # draw separator

        cur_y += 1
        text = ("└" if not has_bookmark_zero else "│") + "─" * (panel_width - 1)
        formatting = curses.A_BOLD  # status_section
        self.stdscr.addstr(cur_y, start_col, text, formatting)

        # if we have a bookmark for slot 0, add that to the panel
        if 0 in self.bookmarks:
            y = cur_y + 1
            x = start_col

            parent_node = self.bookmarks[0]

            text = "│ " + parent_node.text
            text = text[:panel_width]
            text = text.ljust(panel_width)

            formatting = curses.A_BOLD  # status_section
            self.stdscr.addstr(y, x, text, formatting)

            for node in parent_node.children:
                if node.is_done(consider_parent=False):
                    continue
                text = "│ " + node.get_text()
                if node.children:
                    text = text + " [•••]"
                text = text[:panel_width]
                text = text.ljust(panel_width)
                y += 1
                # formatting = self.palette.top_bar
                self.stdscr.addstr(y, x, text)  # , formatting)

            # draw separator
            y += 1
            text = "└" + "─" * (panel_width - 1)
            formatting = curses.A_BOLD  # status_section
            self.stdscr.addstr(y, x, text, formatting)

    def render(self, command_mode=False, match_index=None, total_matches=None):
        global EDIT_MODE_ESC

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
            box.edit(command_edit_validator)

            # Get resulting contents
            message = box.gather()
            message = message.strip()

            query_mode = message.startswith("?")
            jump_to_sources = message == "<"  # given hashtags, go to slug locations
            jump_to_citations = message == ">"  # given slug, find hashtag references

            if query_mode or jump_to_citations or jump_to_sources:
                matching_nodes = []
                if query_mode:
                    global_scope = message.startswith("??")
                    query = message.lstrip("? ")
                    matching_nodes = self.find_matches(
                        query=query, global_scope=global_scope
                    )
                elif jump_to_sources:
                    matching_nodes = self.find_hashtag_sources()
                elif jump_to_citations:
                    matching_nodes = self.find_hashtag_citations()

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
                self.visible_node_list = self.context_node.get_node_list(
                    only_visible=True
                )
                self.focus_index = self.visible_node_list.index(new_node)
                return self.render(command_mode=False)
            elif message == "decrypt":
                focus_node.decrypt()
                return self.render(command_mode=False)
            elif message == "save":
                self.save()
                return self.render(command_mode=False)
            elif message == "random":
                self.jump_to_random()
                return self.render(command_mode=False)
            elif message == "run":
                focus_node.run_command()
                return self.render(command_mode=False)
            elif message in subtrees:
                # add_scamper_structure(focus_node)
                add_subtree(focus_node, subtrees[message])
                return self.refresh()
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
                is_highlighted = node.is_highlighted()
                is_self_deleting = node.is_self_deleting()

                days_old = node.get_days_old()
                age_char = "▌"
                age_color = None
                if not is_self_deleting:
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
                else:
                    days_remaining = node.get_days_remaining()
                    if days_remaining <= 2:
                        age_char = "█"
                        age_color = self.palette.expiry_4
                    elif days_remaining <= 7:
                        age_char = "▊"
                        age_color = self.palette.expiry_3
                    elif days_remaining <= 30:
                        age_color = self.palette.expiry_2
                    elif days_remaining <= 356:
                        age_color = self.palette.expiry_1
                    else:
                        age_color = self.palette.expiry_0

                age_text = age_char.ljust(line_num_chars)

                is_last_child = node.parent.children[-1] == node

                text = node.get_text()
                if node.is_collapsed:
                    text = text + " [•••]"

                indent_text = age_text + (("    ") * (node.depth - root_depth - 1))
                chunks = textwrap.wrap(
                    text,
                    width=curses.COLS,
                    initial_indent=indent_text,
                    subsequent_indent=indent_text + "   ",
                )

                nb_chunks = len(chunks)

                for chunk in chunks:
                    chunk = chunk.ljust(curses.COLS)
                    # first draw the full text
                    try:
                        formatting = curses.A_NORMAL

                        coloring = 0
                        if is_done:
                            # if self.palette.default_text > self.palette.background:
                            formatting = formatting | curses.A_DIM

                        if node.depth == root_depth + 1:
                            formatting = formatting | curses.A_BOLD

                        if node in self.cut_nodes:
                            formatting = formatting | curses.A_UNDERLINE

                        if is_highlighted:
                            coloring = self.palette.line_highlights[
                                node.highlight_index
                            ]

                        self.stdscr.addstr(line_num, 0, chunk, formatting | coloring)

                        ch = "►"  # "-" #

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
                                if m in ["#DONE", "#ENCRYPT", "#HL"]:
                                    continue
                                if node.text.startswith(m):
                                    coloring = self.palette.hashtag
                                    m = " ".join(node.text.split()[:3])
                                else:
                                    coloring = self.palette.hashtag
                                self.stdscr.addstr(
                                    line_num, chunk.find(m), m, formatting | coloring
                                )

                        if "?" in chunk and not is_highlighted:
                            self.stdscr.addstr(
                                line_num,
                                chunk.find("?"),
                                "?",
                                formatting | self.palette.question,
                            )

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

                        if node in self.bookmarks.values():
                            # coloring = self.palette.bookmark
                            # if coloring is not None:
                            #
                            self.stdscr.addstr(line_num, 1, "💠", formatting)
                        # elif "#y" in node.text:
                        #     formatting = formatting | self.palette.yellow
                        #     self.stdscr.addstr(line_num, 1, "▌", formatting)
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
                        text = age_char + " " * (curses.COLS - 1)

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

            if self.show_bookmark_panel:
                self.draw_bookmark_panel()

            self.stdscr.refresh()

            if editwin:
                self.stdscr.refresh()

                editwin.addstr(0, 0, textwrap.fill(edit_node.text, edit_width))
                box = Textbox(editwin, insert_mode=True)

                # Let the user edit until Ctrl-G or Enter is struck.
                box.edit(edit_validator)
                if EDIT_MODE_ESC:
                    EDIT_MODE_ESC = False  # reset the flag
                    edit_node.stop_edit_mode()
                    return self.render()

                # Get resulting contents
                message = box.gather()
                message = message.replace("\n", "").strip()
                # print("=====", message[-1], "=======")

                indent_count = 0
                while message.startswith(">"):
                    indent_count += 1
                    message = message[1:]
                deindent_count = 0
                while message.startswith("<"):
                    deindent_count += 1
                    message = message[1:]
                # indent_count = message.startswith(">")
                # deindent = message.startswith("<")
                # message = message.lstrip(">")
                # message = message.lstrip("<")
                message = message.strip()

                message = re.sub(r"{YMD}", datetime.now().strftime("%Y-%m-%d"), message)
                message = re.sub(
                    r"{NOW}", datetime.now().strftime("%Y %B %d %I:%M %p"), message
                )

                edit_node.text = message
                edit_node.stop_edit_mode()

                if edit_node.text:
                    self.has_unsaved_operations = True

                    if indent_count:
                        self.indent(count=indent_count)
                    elif deindent_count:
                        self.deindent(count=deindent_count)
                else:
                    self.delete_focus_node()

                return self.render()

        self.stdscr.move(curses.LINES - 1, curses.COLS - 1)

        return

    def refresh(self):
        self.index_nodes()
        self.visible_node_list = self.context_node.get_node_list(only_visible=True)
        self.has_unsaved_operations = True
        self.render(command_mode=False)

    def add_plugin(self, cls):
        self.plugins.append(cls(self))

    def run_plugins(self):
        for p in self.plugins:
            p.run()


def command_edit_validator(ch):
    # make it so that when the user presses enter, it's the same as ctrl-G (finish editing)
    if ch in [7, 10]:
        return 7
    return ch


def edit_validator(ch):
    global EDIT_MODE_ESC
    if ch == 9:  # tab
        return ">"
    if ch == 353:  # shift-tab
        return "<"
    # print(ch)

    if ch in [7, 10, 27]:  # 27 == esc
        if ch == 27:
            EDIT_MODE_ESC = True
        return 7

    return ch


def add_subtree(node, tree):
    for k, v in tree.items():
        child = node.add_child(k)
        if v:
            add_subtree(child, v)


def insert_nested_list(node, nested_list):
    for item in nested_list:
        if isinstance(item, str):
            _ = node.add_child(item)
        else:
            child = node.add_child(item[0])
            insert_nested_list(child, item[1])


# def add_scamper_structure(node):
#     tree = {
#         "SCAMPER": {
#             "Substitute": None,
#             "Combine": {
#                 "With Blah": None,
#                 "Or NAH": None,
#             },
#             "Adapt": None,
#             "Magnify/Modify": None,
#             "Put to other use": None,
#             "Eliminate": None,
#             "Rearrange/Reverse": None
#         }
#     }

#     add_subtree(node, tree)
