import copy
import json
import os
import random
import re
import textwrap
import time
from datetime import datetime

from node import Node, lca_distance
from subtrees import SUBTREES
from utils import (
    MONTH_ORDER,
    add_subtree,
    convert_to_nested_list,
    determine_state_filename,
    normalize_indentation,
    trigram_similarity,
)

# import pyclip


class NoteTree:
    def __init__(self, filename, undo_depth=50):
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
                            elif (
                                isinstance(prop, list)
                                and prop[0] == "contextual_highlight"
                            ):
                                matching_node.contextual_highlight = prop[1]

        for n in node_list:
            n.creation_time = creation_time_map.get(n.get_key(), datetime.now())
            # n.creation_time = creation_time_map.get(n.text[-30:], datetime.now())

        if len(self.root.children) == 0:
            add_subtree(self.root, SUBTREES["WELCOME"])
            self.root.children[0].is_collapsed = True

        self.has_unsaved_operations = False
        self.context_node = context_node or self.root
        self.update_visible_node_list()

        self._undo_stack = []
        self._redo_stack = []
        self._undo_depth = undo_depth

    def save(self):
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

                if node.contextual_highlight:
                    properties.append(
                        ("contextual_highlight", node.contextual_highlight)
                    )

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

    # --- Undo/Redo ---
    # Snapshot-based: before each mutation, deepcopy the affected subtree.
    # On undo, swap it back. Redo is the mirror.

    def _get_index_path(self, node):
        """Return path from root as list of child indices, e.g. [2, 0, 3]."""
        path = []
        while node.parent is not None:
            path.append(node.parent.children.index(node))
            node = node.parent
        return list(reversed(path))

    def _resolve_index_path(self, path):
        """Follow an index path from root to find the node. Falls back to root."""
        node = self.root
        for idx in path:
            if idx < len(node.children):
                node = node.children[idx]
            else:
                return self.root
        return node

    def _snapshot_subtree(self, subtree_root):
        """Deepcopy a subtree, temporarily disconnecting parent to avoid copying upward."""
        saved_parent = subtree_root.parent
        subtree_root.parent = None
        subtree_copy = copy.deepcopy(subtree_root)
        subtree_root.parent = saved_parent
        return subtree_copy

    def _make_snapshot(self, subtree_root):
        """Capture the subtree plus context node position for later restoration."""
        return {
            "path": self._get_index_path(subtree_root),
            "subtree": self._snapshot_subtree(subtree_root),
            "context_path": self._get_index_path(self.context_node),
        }

    def push_undo(self, subtree_root):
        """Save a snapshot before a mutation. Clears the redo stack."""
        self._undo_stack.append(self._make_snapshot(subtree_root))
        if len(self._undo_stack) > self._undo_depth:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _swap_subtree(self, snapshot):
        """Replace the subtree at snapshot's path with the snapshot's copy.
        Returns a reverse snapshot of what was replaced (for the opposite stack)."""
        path = snapshot["path"]
        current_node = self._resolve_index_path(path)
        reverse = self._make_snapshot(current_node)

        restored = snapshot["subtree"]
        if not path:
            # Restoring root
            self.root = restored
            self.root.parent = None
        else:
            parent = self._resolve_index_path(path[:-1]) if len(path) > 1 else self.root
            child_idx = path[-1]
            restored.parent = parent
            parent.children[child_idx] = restored
            restored.depth = parent.depth + 1
            restored.update_child_depth()

        # Restore context node via its saved index path
        self.context_node = self._resolve_index_path(snapshot["context_path"])

        self.index_nodes()
        self.update_visible_node_list()
        self.has_unsaved_operations = True
        return reverse

    def pop_undo(self):
        """Undo the last mutation. Returns True if successful."""
        if not self._undo_stack:
            return False
        snapshot = self._undo_stack.pop()
        reverse = self._swap_subtree(snapshot)
        self._redo_stack.append(reverse)
        return True

    def pop_redo(self):
        """Redo the last undone mutation. Returns True if successful."""
        if not self._redo_stack:
            return False
        snapshot = self._redo_stack.pop()
        reverse = self._swap_subtree(snapshot)
        self._undo_stack.append(reverse)
        return True

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

    def _rank_nodes_by_similarity(
        self,
        query_text,
        nodes,
        text_fn=None,
        coverage_weight=0.5,
        threshold=0.05,
        regex_prefilter=None,
    ):
        """Score and rank nodes by trigram similarity to query_text.

        The score is a blend of two trigram metrics (see trigram_similarity):
          - **coverage**: what fraction of the query's trigrams appear in the
            candidate.  High coverage means the candidate "contains" the query.
          - **similarity**: Jaccard overlap of trigram sets.  High similarity
            means the two texts are roughly the same length and content.

        coverage_weight controls the blend:
          - High (e.g. 0.75): favour candidates that contain the query, even
            if they are much longer.  Good for search-by-query, where a short
            query should match inside long notes.
          - Low / balanced (e.g. 0.5): penalise large length mismatches, so
            a long note won't dominate just because it happens to contain the
            query trigrams.  Good for "find me notes that say roughly the same
            thing" (similarity discovery).

        Args:
            query_text: The text to compare against (should be lowercase).
            nodes: Iterable of Node objects to score.
            text_fn: Callable(node) -> str to extract comparison text.
                     Defaults to node.text.
            coverage_weight: Blend between coverage (1.0) and Jaccard
                             similarity (0.0).  See note above.
            threshold: Minimum score to include.
            regex_prefilter: If set, compiled regex. Nodes with short text
                             (< 20 chars) that don't match are skipped.

        Returns:
            List of (node, score) tuples, sorted by score descending.
        """
        if text_fn is None:
            text_fn = lambda n: n.text

        scored = []
        for node in nodes:
            text = text_fn(node)
            if regex_prefilter and len(text) < 20 and not regex_prefilter.search(text):
                continue
            score = trigram_similarity(
                text.lower(), query_text, coverage_weight=coverage_weight
            )
            if score >= threshold:
                scored.append((node, score))

        scored.sort(key=lambda t: -t[1])
        return scored

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

    def find_by_query(self, query, global_scope=True, match_path=False, threshold=0.05):
        """User-initiated search (:? and :?? commands, and :run path resolution).

        Designed for the case where the user types a short query and expects
        to find it *inside* longer notes.  Uses coverage_weight=0.75 so that
        a note containing the query ranks high even if the note is much longer
        than the query.  A regex prefilter fast-rejects very short notes that
        don't literally contain the query pattern, avoiding false positives
        from tiny texts whose few trigrams happen to overlap.

        When match_path=True (triggered by ">" in the query, or :run following
        a [[path]] reference), the full ancestor path of each node is scored
        instead of just node.text.
        """
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        if global_scope:
            nodes = self.get_node_list()
        else:
            nodes = self.context_node.get_node_list(
                only_visible=False, hide_done=self.hide_done
            )

        if match_path:
            text_fn = lambda n: ">".join(n.get_path(include_self=True)).replace(
                "-", " "
            )
        else:
            text_fn = lambda n: n.text.replace("-", " ")

        ranked = self._rank_nodes_by_similarity(
            query.lower(),
            nodes,
            text_fn=text_fn,
            coverage_weight=0.75,
            threshold=threshold,
            regex_prefilter=pattern,
        )
        return [node for node, _score in ranked]

    def find_by_similarity(self, target_node, n=10):
        """Discovery of notes similar to a given note (empty :? command).

        Unlike find_by_query, there is no short query being looked up inside
        longer texts -- both sides are full-length notes, so we want a
        symmetric comparison.  Uses coverage_weight=0.5 (balanced Jaccard) so
        that a 200-word note doesn't dominate a 5-word note just because it
        happens to contain the same trigrams.  No regex prefilter or threshold
        is applied; instead we take the top *n* results regardless of score,
        and let the caller decide a display cutoff.

        Returns up to *n* tuples of:
            (node, similarity, lca_distance, is_in_context)
        sorted by similarity descending.  lca_distance and is_in_context are
        metadata for display (dimming out-of-context results, etc.).
        """
        all_nodes = self.root.get_node_list(only_visible=False)
        nodes = [
            nd
            for nd in all_nodes
            if nd is not target_node
            and nd is not self.root
            and len(nd.text.strip()) >= 3
        ]

        ranked = self._rank_nodes_by_similarity(
            target_node.text,
            nodes,
            coverage_weight=0.1,
            threshold=0.0,
        )[:n]

        results = []
        for node, sim in ranked:
            dist = lca_distance(target_node, node)
            in_context = any(
                cur is self.context_node for cur in self._iter_ancestors(node)
            )
            results.append((node, sim, dist, in_context))
        return results

    @staticmethod
    def _iter_ancestors(node):
        """Yield node and all its ancestors."""
        cur = node
        while cur is not None:
            yield cur
            cur = cur.parent
