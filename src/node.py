import logging
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta

from pytimeparse import parse

logger = logging.getLogger(__name__)


class Node:
    def __init__(self, parent, text, depth=0, is_collapsed=False):
        self.parent = parent
        self.text = text
        self.children = []
        self.depth = depth
        self.is_collapsed = is_collapsed
        self.creation_time = datetime.now()

        self.doodle_id: int | None = None

        self.index = 0

        # TODO: find a nice way to make sure the number of highlights is synched between the palette file and this list
        self.HIGHLIGHT_HASHTAGS = [f"#HL{i+1}" for i in range(3)]
        self.highlight_index = None
        if "#HL" in self.text:
            for w in self.text.split()[-3:]:
                if w in self.HIGHLIGHT_HASHTAGS:
                    self.highlight_index = int(w[-1]) - 1
                    break

        self.expiry_datetime = None
        self.expiry_duration = None
        # Whether this note's #T- timer auto-renews on expiry (marker "#T-*").
        self.expiry_recurring = False
        # Whether an expiry notification has already fired for the current
        # expiry window (reset when the timer is renewed / not yet expired).
        self.expiry_notified = False
        self.extract_expiry()

        self.value_dict: dict = {}
        self.extract_values()

    def extract_values(self) -> None:
        self.value_dict = {}
        if "$" not in self.text:
            return
        for key, value in re.findall(
            r"\$([a-zA-Z_]+)\s?=\s?([\-\+]?[\d.]+)", self.text
        ):
            try:
                value = float(value)
            except ValueError:
                continue
            self.value_dict[key.lower()] = value

    def ensure_path(self, text_list):
        if not text_list:
            return self

        for node in self.children:
            if node.text == text_list[0]:
                return node.ensure_path(text_list[1:])

        return self.add_child(text_list[0]).ensure_path(text_list[1:])

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

    def get_highlight_hashtag(self):
        matches = re.findall(r"\B#(HL[123])", self.text)
        if matches:
            return matches[0]
        else:
            return None

    def get_path(self, include_self):
        parts = []
        if include_self:
            parts.append(self.text)
        cur_node = self.parent
        while cur_node:
            parts.append(cur_node.text)
            cur_node = cur_node.parent

        return parts[::-1]

    def get_path_string(self, width: int = 50):
        parts = self.get_path(include_self=True)[1:]

        if not parts:
            return ""

        separator = " › "
        sep_total = len(separator) * (len(parts) - 1)
        available = width - sep_total
        min_part = 4  # minimum chars per part (3 visible + "…")

        lengths = [len(p) for p in parts]

        if sum(lengths) <= available:
            return separator.join(parts)

        # Distribute available space: short parts keep full length,
        # long parts share the remainder equally.
        allocs = lengths[:]
        for _ in range(len(parts)):
            # Find the cap where long parts (those above cap) split the
            # space left after short parts (those at or below cap).
            # Sort to find the right threshold.
            sorted_lens = sorted(allocs)
            remaining = available
            settled = 0
            cap = available
            for i, l in enumerate(sorted_lens):
                slots = len(parts) - i
                fair_share = remaining // slots if slots else remaining
                if l <= fair_share:
                    remaining -= l
                    settled += 1
                else:
                    cap = max(fair_share, min_part)
                    break
            else:
                cap = max(remaining // max(len(parts) - settled, 1), min_part)

            new_allocs = [min(l, cap) for l in lengths]
            if sum(new_allocs) <= available:
                allocs = new_allocs
                break
            allocs = new_allocs

        truncated = []
        for p, a in zip(parts, allocs):
            if len(p) <= a:
                truncated.append(p)
            else:
                truncated.append(p[: max(a - 1, 1)] + "…")
        path_str = separator.join(truncated)

        if len(path_str) > width:
            path_str = "…" + path_str[-(width - 1) :]
        return path_str

    def is_done(self, consider_parent=True):
        done = False
        if "#DONE" in self.text:
            done = True
        if (
            not done
            and consider_parent
            and self.parent
            and self.parent.is_done(consider_parent=True)
        ):
            done = True

        return done

    def is_archived(self, consider_parent=True):
        if "#ARCHIVE" in self.text:
            return True
        if (
            consider_parent
            and self.parent
            and self.parent.is_archived(consider_parent=True)
        ):
            return True
        return False

    def is_highlighted(self):
        return self.highlight_index is not None

    def get_expiry(self):
        if self.expiry_datetime:
            return self.expiry_datetime
        if self.parent is None:
            return None
        return self.parent.get_expiry()

    def extract_expiry(self):
        # Token forms (see reset_expiry / expiry_status):
        #   #T-<duration>@<expiry-iso>  -- current form; keeps duration for reset
        #   #T-<duration>               -- relative; computed + migrated in place
        self.expiry_datetime = None
        self.expiry_duration = None
        self.expiry_recurring = False
        if "#T-" not in self.text:
            return
        words = self.text.split()
        for i, w in enumerate(words):
            if not w.startswith("#T-"):
                continue
            spec = w[3:]  # everything after "#T-"
            # Optional leading "*" marks an auto-renewing (recurring) timer.
            self.expiry_recurring = spec.startswith("*")
            if self.expiry_recurring:
                spec = spec[1:]
            if "@" in spec:
                dur_str, _, exp_str = spec.partition("@")
                self.expiry_duration = dur_str or None
                try:
                    self.expiry_datetime = datetime.strptime(
                        exp_str, "%Y-%m-%dT%H:%M:%S"
                    )
                except ValueError:
                    pass
            else:
                # Relative duration -> compute expiry and migrate the token so
                # the duration is preserved for later resets.
                duration_seconds = extended_parse(spec)
                if duration_seconds is not None:
                    self.expiry_duration = spec
                    self.expiry_datetime = datetime.now() + timedelta(
                        seconds=duration_seconds
                    )
                    marker = "*" if self.expiry_recurring else ""
                    words[i] = self.expiry_datetime.strftime(
                        f"#T-{marker}{spec}@%Y-%m-%dT%H:%M:%S"
                    )
                    self.text = " ".join(words)
            break

    def reset_expiry(self) -> bool:
        """Restart this note's own #T- countdown for its original duration.

        Returns True if the timer was reset, or False if the note has no
        resettable duration of its own (an inherited expiry, or no timer at
        all)."""
        if not self.expiry_duration:
            return False
        duration_seconds = extended_parse(self.expiry_duration)
        if duration_seconds is None:
            return False
        self.expiry_datetime = datetime.now() + timedelta(seconds=duration_seconds)
        marker = "*" if self.expiry_recurring else ""
        new_token = self.expiry_datetime.strftime(
            f"#T-{marker}{self.expiry_duration}@%Y-%m-%dT%H:%M:%S"
        )
        words = self.text.split()
        for i, w in enumerate(words):
            if w.startswith("#T-"):
                words[i] = new_token
                break
        self.text = " ".join(words)
        return True

    def is_expired(self) -> bool:
        expiry = self.get_expiry()
        return expiry is not None and datetime.now() > expiry

    def expiry_status(self):
        """For a note that owns a #T- timer, return (expired, label) where
        `label` is a compact magnitude of the time until/since expiry
        ('2d' / '5h' / '12m'). Returns None for notes without their own timer."""
        if self.expiry_datetime is None:
            return None
        delta = self.expiry_datetime - datetime.now()
        expired = delta.total_seconds() < 0
        seconds = int(abs(delta.total_seconds()))
        if seconds >= 86400:
            label = f"{seconds // 86400}d"
        elif seconds >= 3600:
            label = f"{seconds // 3600}h"
        else:
            label = f"{max(1, seconds // 60)}m"
        return expired, label

    def toggle_done(self):

        words = self.text.split()

        if not self.is_done():
            words.append("#DONE")

            # look through value dict for anything to increment or decrement
            for k, v in self.value_dict.items():
                delta = 0
                if k.endswith("_inc"):
                    delta = 1
                elif k.endswith("_dec"):
                    delta = -1
                if delta:
                    old_word = [w for w in words if w.lower().startswith("$" + k)][0]
                    words[words.index(old_word)] = f"${k}={v+delta}"

            self.text = " ".join(words)
            self.post_text_update()
        else:
            if "#DONE" in words:
                words.remove("#DONE")
                self.text = " ".join(words)
            else:
                words.append("#DONE")
                self.text = " ".join(words)
            # if it is done, but there's no #DONE in the text, it means that a parent/ancestor is marked as done,
            #   in which case, don't do anything

    def cycle_highlight(self):
        words = self.text.split()

        if not self.is_highlighted():
            words.append(self.HIGHLIGHT_HASHTAGS[0])
            self.highlight_index = 0

        else:
            words.remove(self.HIGHLIGHT_HASHTAGS[self.highlight_index])
            self.highlight_index = self.highlight_index + 1
            if self.highlight_index >= len(self.HIGHLIGHT_HASHTAGS):
                self.highlight_index = None

            if self.highlight_index is not None:
                words.append(self.HIGHLIGHT_HASHTAGS[self.highlight_index])

        self.text = " ".join(words)

    def get_days_old(self, recurse=False):
        days = (datetime.now() - self.creation_time).days
        if self.is_collapsed or recurse:
            return min([days] + [c.get_days_old(recurse=True) for c in self.children])
        else:
            return days

    def get_text(self):
        text = self.text

        if "#T-" in self.text:
            words = text.split()
            words = [w for w in words if not w.startswith("#T-")]
            text = " ".join(words)

        # if self.is_collapsed:
        #     text = text + " [•••]"

        hashtags = self.get_hashtags()
        if "sum" in hashtags:
            if branch_values := self.get_branch_values():
                values_str = "|".join(
                    [f"Σ{k}={sum(v)}" for k, v in branch_values.items()]
                )
                text += f" ({values_str})"
        if "max" in hashtags:
            if branch_values := self.get_branch_values():
                values_str = "|".join(
                    [f"max({k})={max(v)}" for k, v in branch_values.items()]
                )
                text += f" ({values_str})"
        if "min" in hashtags:
            if branch_values := self.get_branch_values():
                values_str = "|".join(
                    [f"min({k})={min(v)}" for k, v in branch_values.items()]
                )
                text += f" ({values_str})"
        if "avg" in hashtags:
            if branch_values := self.get_branch_values():
                values_str = "|".join(
                    [f"avg({k})={sum(v)/len(v)}" for k, v in branch_values.items()]
                )
                text += f" ({values_str})"

        return text

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        if not self.children:
            self.is_collapsed = False

    def paste_node_here(self, node, as_sibling=False):
        if node == self:
            return
        # Check that self is not a descendant of node (would create a cycle)
        ancestor = self.parent
        while ancestor:
            if ancestor == node:
                return
            ancestor = ancestor.parent
        node.parent.children.remove(node)

        if as_sibling and self.parent is not None:
            new_parent = self.parent
            insert_index = new_parent.children.index(self) + 1
            new_parent.children.insert(insert_index, node)
            node.parent = new_parent
            new_parent.update_child_depth()
        else:
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

    def move_deeper(self, done_are_hidden=False):
        parent = self.parent
        if parent is None:
            return

        # if done nodes are hidden, we want to find the first non-done sibling-of-parent node
        siblings = [s for s in parent.children if not (done_are_hidden and s.is_done())]

        sibling_index = siblings.index(self)
        if sibling_index == 0:
            return

        prev_sibling = siblings[sibling_index - 1]

        parent.children.remove(self)

        self.depth += 1
        self.update_child_depth()
        self.parent = prev_sibling
        prev_sibling.children.append(self)

    def show(self):
        indentation = "\t" * self.depth
        print(f"{indentation}{self.get_text()}")
        for c in self.children:
            c.show()

    def get_node_list(self, only_visible=False, hide_done=False, hide_archive=False):

        if hide_done and self.is_done():
            return []

        if hide_archive and "#ARCHIVE" in self.text:
            return []

        l = [self]
        if (not only_visible) or (only_visible and not self.is_collapsed):
            for c in self.children:
                l.extend(
                    c.get_node_list(
                        only_visible=only_visible,
                        hide_done=hide_done,
                        hide_archive=hide_archive,
                    )
                )
        return l

    def post_text_update(self):
        self.extract_expiry()  # check if the expiry has changed
        self.extract_values()

    def run_command(self):
        # first check if there is a command -- indicated by .. !
        if not self.text.startswith("!"):
            logger.info(f"Invalid command: '{self.text}'")
            return

        # Drop Forest control tokens (timer / done / highlight) so they are not
        # passed to the shell -- relevant when a command note also carries #T-.
        words = [
            w
            for w in self.text[1:].split()
            if not w.startswith("#T-")
            and w != "#DONE"
            and w not in self.HIGHLIGHT_HASHTAGS
        ]
        command = " ".join(words).strip() + " > /dev/null 2>&1 &"

        # cmdStr=WEB_BROWSER+" https://www.youtube.com/results?search_query="+youtubeStr.replace(' ','+')+" > /dev/null 2>&1 &"
        subprocess.call(command, shell=True)
        logger.info("Ran command")

    def get_branch_values(self) -> defaultdict:
        """
        Recursively collect all of the values defined in notes ($variable=value)
        """

        all_values = defaultdict(list)
        for k, v in self.value_dict.items():
            all_values[k].append(v)

        for n in self.children:
            for k, v in n.get_branch_values().items():
                all_values[k].extend(v)

        return all_values


def lca_distance(node_a, node_b):
    """Compute the LCA (Lowest Common Ancestor) distance between two nodes.

    Returns the total number of edges traversed: steps from node_a up to the
    LCA plus steps from node_b up to the LCA.  E.g. shared parent = 2.
    """
    ancestors_a = {}
    cur = node_a
    steps = 0
    while cur is not None:
        ancestors_a[id(cur)] = steps
        cur = cur.parent
        steps += 1

    cur = node_b
    steps_b = 0
    while cur is not None:
        if id(cur) in ancestors_a:
            return ancestors_a[id(cur)] + steps_b
        cur = cur.parent
        steps_b += 1

    # No common ancestor (shouldn't happen in a single tree)
    return float("inf")


def extended_parse(input_str: str) -> int | None:
    """extend pytimeparse.parse to work with years and months"""
    if not input_str:
        return None
    seconds = parse(input_str)
    if seconds is not None:
        return seconds
    if input_str[-1] == "y":
        try:
            years = float(input_str[:-1])
            days = years * 365
            return parse(f"{days}d")
        except:
            return None
    if input_str[-2:] == "mo":
        try:
            months = float(input_str[:-2])
            days = months * 30
            return parse(f"{days}d")
        except:
            return None
    return None
