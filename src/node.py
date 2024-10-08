import re
import subprocess
from datetime import datetime, timedelta
from pytimeparse import parse

from encryption_manager import encryption_manager


class Node:
    def __init__(self, parent, text, depth=0, is_collapsed=False):
        self.parent = parent
        self.text = text
        self.children = []
        self.depth = depth
        self.is_collapsed = is_collapsed
        self.edit_mode = False

        self.creation_time = datetime.now()

        self.index = 0

        # TODO: find a nice way to make sure the number of highlights is synched between the palette file and this list
        self.HIGHLIGHT_HASHTAGS = [f"#HL{i+1}" for i in range(3)]
        self.highlight_index = None
        for w in self.text.split()[-3:]:
            if w in self.HIGHLIGHT_HASHTAGS:
                self.highlight_index = int(w[-1]) - 1
                break

        self.expiry_datetime = None
        self.extract_expiry()

    def remove_expired_notes(self):

        if self.parent is None:
            for child in self.children:
                child.remove_expired_notes()
        else:
            if self.expiry_datetime and datetime.now() > self.expiry_datetime:
                self.delete_branch()
            else:
                for child in self.children:
                    child.remove_expired_notes()

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

    def get_key(self):
        """
        The "key" for a node is a unique identifier used when saving/loading the state file. We need to be able to attach metadata to notes
          even when multiple nearby notes might be identical
        """
        path = self.get_path(include_self=False)
        return ">".join([p[-10:] for p in path] + [self.text[-30:]])

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

    def is_highlighted(self):
        return self.highlight_index is not None

    def is_self_deleting(self):
        return self.get_expiry() is not None

    def get_expiry(self):
        if self.expiry_datetime:
            return self.expiry_datetime
        if self.parent is None:
            return None
        return self.parent.get_expiry()

    def extract_expiry(self):
        words = self.text.split()
        self.expiry_datetime = None
        for w in words:
            # if w.startswith("#EXPIRY-"):
            #     time_str = w.split("-", 1)[1]
            #     try:
            #         dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S")
            #         self.expiry_datetime = dt
            #     except ValueError:
            #         pass
            #     break
            if w.startswith("#T-"):
                time_str = w.split("-", 1)[1]
                if "-" in time_str:
                    try:
                        dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S")
                        self.expiry_datetime = dt
                    except ValueError:
                        pass
                    break
                else:
                    duration = time_str
                    duration_seconds = parse(duration)
                    if duration_seconds is not None:
                        self.expiry_datetime = datetime.now() + timedelta(
                            seconds=duration_seconds
                        )
                        words.remove(w)
                        words.append(
                            self.expiry_datetime.strftime("#T-%Y-%m-%dT%H:%M:%S")
                        )
                        self.text = " ".join(words)
                    break

    def get_days_remaining(self):
        return (self.get_expiry() - datetime.now()).days

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

    def cycle_highlight(self):
        if encryption_manager.is_encrypted(self.text):
            return

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

    # def cycle_expiry(self):
    #     if encryption_manager.is_encrypted(self.text):
    #         return

    #     EXPIRY_OPTIONS = ["#T-1d", "#T-7d", "#T-30d"]

    #     words = self.text.split()

    #     if not self.is_self_deleting():
    #         words.append(EXPIRY_OPTIONS[0])
    #         dur = parse(EXPIRY_OPTIONS[0].split("-")[1])
    #         self.expiry_datetime = datetime.now() + timedelta(seconds=dur)
    #     else:
    #         for w in words:
    #             if w.startswith("#T-"):
    #                 if w in EXPIRY_OPTIONS:
    #                     self.expiry_datetime = None
    #                     i = EXPIRY_OPTIONS.index(w)
    #                     words.remove(w)
    #                     if i < len(EXPIRY_OPTIONS) - 1:
    #                         words.append(EXPIRY_OPTIONS[i+1])
    #                         dur = parse(EXPIRY_OPTIONS[i+1].split("-")[1])
    #                         self.expiry_datetime = datetime.now() + timedelta(seconds=dur)
    #                 break  # if it's a custom expiry, leave it alone

    #     self.text = " ".join(words)

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

        if "#T-" in self.text:
            words = text.split()
            words = [w for w in words if not w.startswith("#T-")]
            text = " ".join(words)

        if indentation:
            return "► " + text  # "- "+text #
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
        self.extract_expiry()  # check if the expiry has changed

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

    def run_command(self):
        # first check if there is a command -- indicated by .. !
        if not self.text.startswith("!"):
            return

        command = self.text[1:] + " > /dev/null 2>&1 &"

        # cmdStr=WEB_BROWSER+" https://www.youtube.com/results?search_query="+youtubeStr.replace(' ','+')+" > /dev/null 2>&1 &"
        subprocess.call(command, shell=True)
