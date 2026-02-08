import json
import os
import random
import re
import textwrap
import time
from datetime import datetime

# from encryption_manager import encryption_manager
from node import Node
from utils import (MONTH_ORDER, convert_to_nested_list,
                   determine_state_filename, normalize_indentation,
                   trigram_similarity)

# import pyclip


class NoteTree:
    def __init__(self, filename):
        self.filename = filename

        self.state_filename = determine_state_filename(filename)

        self.root = Node(parent=None, text=filename)

        with open(self.filename, "r") as f:
            lines = f.read().splitlines()

            cur_node = self.root

            prev_depth = -1
            for l in lines:
                # print("Line:", l)
                if not l.strip():
                    # print("\tskipping")
                    continue

                depth = len(l) - len(l.lstrip())

                # handle the case where we accidentally indent a little too much
                if depth > prev_depth:
                    depth = prev_depth + 1
                # print(f"\tdepth = {depth}")

                text = l.strip()
                text = text.lstrip("- ")

                if depth > prev_depth:
                    # print(f"\tDEEPER. Adding child")
                    child = cur_node.add_child(text)
                    cur_node = child
                elif depth == prev_depth:
                    # print(f"\tSAME DEPTH. Adding sibling")
                    sibling = cur_node.parent.add_child(text)
                    cur_node = sibling
                elif depth < prev_depth:
                    # prev_depth = 1, depth = 3
                    nb_steps = prev_depth - depth
                    # print(f"\tSHALLOWER BY {nb_steps}")
                    for _ in range(nb_steps):
                        cur_node = cur_node.parent
                    node = cur_node.parent.add_child(text)
                    cur_node = node

                prev_depth = depth

        # controls whether to hide all notes marked as done
        self.hide_done = False

        node_list = self.index_nodes()

        self.journal = None
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
                                max(index - 15, 0),
                                min(index + 15, len(node_list)),
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

        self.has_unsaved_operations = False
        self.context_node = context_node or self.root
        self.update_visible_node_list()

    def save(self):
        # apply encryption where needed
        # self.encrypt()

        # self.remove_expired_notes()

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

    def update_visible_node_list(self):
        self.visible_node_list = self.context_node.get_node_list(
            only_visible=True,
            hide_done=self.hide_done,
        )

    def toggle_collapse(self, node: None):
        if node.children:
            node.toggle_collapse()
            self.update_visible_node_list()
            # self.has_unsaved_operations = True

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

    def index_nodes(self):
        node_list = self.get_node_list(only_visible=False)
        for i, node in enumerate(node_list):
            node.index = i
        return node_list

    def get_node_list(self, only_visible=False):
        return self.root.get_node_list(
            only_visible=only_visible, hide_done=self.hide_done
        )

    def contextual_add_new_note(self, focus_node):
        is_context = focus_node == self.context_node
        mode = ""
        if (
            focus_node.children and not focus_node.is_collapsed
        ) or not focus_node.parent:
            new_node = focus_node.add_child("", top=True)
            # mode = "child"
        else:
            new_node = focus_node.add_directly_below(is_context=is_context)
            # mode = "sibling"

        # return new_node, mode

        if new_node:
            # self.focus_index += 1
            new_node.text = "NEW NODE"  # start_edit_mode()
            self.index_nodes()
            self.update_visible_node_list()
            self.has_unsaved_operations = True

            return new_node

    def move_line(self, node: Node, direction: str):
        siblings = node.parent.children
        visible = [s for s in siblings if not (self.hide_done and s.is_done())]
        vi = visible.index(node)

        if direction == "up" and vi > 0:
            target = visible[vi - 1]
            siblings.remove(node)
            siblings.insert(siblings.index(target), node)
            self.has_unsaved_operations = True
        elif direction == "down" and vi < len(visible) - 1:
            target = visible[vi + 1]
            siblings.remove(node)
            siblings.insert(siblings.index(target) + 1, node)
            self.has_unsaved_operations = True

        self.update_visible_node_list()

    def deindent(self, focus_node, count=1):
        for _ in range(count):

            # we can only deindent if the focus node is not a direct child of the context node, otherwise,
            #   deindenting will make it move outside of the current context window
            if focus_node.parent != self.context_node:
                focus_node.move_shallower()
                self.index_nodes()
                self.has_unsaved_operations = True

        self.update_visible_node_list()

    def indent(self, focus_node, count=1):
        for _ in range(count):
            focus_node.move_deeper(done_are_hidden=self.hide_done)
            self.index_nodes()
        self.has_unsaved_operations = True
        self.update_visible_node_list()

    def delete_focus_node(self, focus_node):
        # TODO: what if we accidentally delete the context node?
        if focus_node.is_collapsed:
            focus_node.delete_branch()
        else:
            focus_node.delete_single()
        self.index_nodes()
        self.has_unsaved_operations = True
        self.update_visible_node_list()

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

        years = [c.text.split()[0] for c in self.journal.children]
        if not year in years:
            year_node = self.journal.add_child(year)
            self.journal.children = sorted(self.journal.children, key=lambda c: c.text)
        else:
            year_node = self.journal.children[years.index(year)]

        months = [c.text.split()[0] for c in year_node.children]
        if not month in months:
            month_node = year_node.add_child(month)
            year_node.children = sorted(
                year_node.children,
                key=lambda c: MONTH_ORDER.index(c.text.split()[0]),
            )
        else:
            month_node = year_node.children[months.index(month)]

        date_str = now.strftime("%Y-%m-%d %H:%M")
        entry = f"[{date_str}] {entry}"
        new_node = month_node.add_child(entry)

        self.index_nodes()
        self.update_visible_node_list()

        self.has_unsaved_operations = True

        return new_node

    def update_context(self, node, expand=False):
        self.context_node = node
        if expand:
            self.context_node.is_collapsed = False
        self.update_visible_node_list()

        # self.has_unsaved_operations = True

    def jump_to_bookmark(self, index) -> Node | None:
        if index in self.bookmarks:

            focus_node = self.bookmarks[index]
            self.bookmark_last_use_times[index] = datetime.now()

            # if focus_node.parent:
            #     self.update_context(focus_node.parent, expand=True)
            # else:
            #     self.update_context(focus_node, expand=True)
            if not focus_node.children:
                self.update_context(focus_node.parent, expand=True)
            else:
                self.update_context(focus_node, expand=True)

            return focus_node

    def toggle_bookmark(self, node: Node):
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

    def determine_if_bookmarked(self, node: None):
        return node in self.bookmarks.values()

    def find_matches(self, query, global_scope=True, match_path=False):
        # find the node in the tree that best matches the query string

        if global_scope:
            node_list = self.get_node_list()
        else:
            node_list = self.context_node.get_node_list(
                only_visible=False, hide_done=self.hide_done
            )

        matching_nodes = []

        for n in node_list:
            if match_path:
                text = ">".join(n.get_path(include_self=True))
            else:
                text = n.text

            text = text.replace("-", " ").lower()  # remove dashes due to hashtags
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

    def get_entries_matching_regex(
        self, regex_str: str, group_index=0
    ) -> list[Node, str]:
        node_list = self.get_node_list()

        matching_nodes = []

        for n in node_list:
            text = n.text
            match = re.search(regex_str, text)
            if match:
                matching_nodes.append((n, match.group(group_index)))

        matching_nodes = sorted(matching_nodes, key=lambda el: el[1])
        return matching_nodes

    def update_wells(self) -> None:
        # locate any well nodes and update children position and statuses
        # TODO: if we last updated wells recently, skip? maybe do in separate thread?
        # TODO: add corresponding logic to node.toggle_done() to update hashtags
        well_roots = [n for n in self.get_node_list() if n.is_well_root()]

        for well_root in well_roots:
            for node in well_root.children:
                # get each node to see if the #DONE tag can be removed (if present)
                node.check_well_status()

            # sort nodes by... (now - resurface time)
            well_root.children = sorted(
                well_root.children, key=lambda n: -n.get_well_sort_value()
            )
