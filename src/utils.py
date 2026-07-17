import difflib
import logging
import os
import random
import re
import urllib.request
from datetime import datetime

try:
    from playsound3 import playsound
except Exception:
    playsound = None

_ASSETS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "sound_effects")
)

_SOUNDS = {
    "timer": [os.path.join(_ASSETS_DIR, "notification_1.mp3")],
}


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def three_way_merge(base, local, disk):
    """Line-level 3-way merge of three lists of lines.

    `base` is the common ancestor (the file content at the last point Forest and
    disk agreed). `local` is Forest's current serialized tree; `disk` is the
    externally-edited file. Returns ``(merged_lines, ok)``:

    - ``ok=True``: local and disk changes touched disjoint regions (or made the
      same change); ``merged_lines`` contains both.
    - ``ok=False``: local and disk changed the same region differently (a true
      conflict). ``merged_lines`` is still populated (disk wins in the conflicting
      hunk) but callers typically discard it and fall back to disk wholesale.

    Standard diff3-style algorithm: anchor on base lines matched in *both* sides,
    and for each chunk between anchors take whichever side changed relative to
    base (or either, if they agree).
    """

    def base_map(other):
        # base index -> other index for lines that compare equal
        m = {}
        for i, j, n in difflib.SequenceMatcher(
            a=base, b=other, autojunk=False
        ).get_matching_blocks():
            for k in range(n):
                m[i + k] = j + k
        return m

    ml = base_map(local)
    md = base_map(disk)

    # Anchors: base indices present (and thus aligned) in both sides. Because
    # matching blocks are monotonic, iterating base order keeps local/disk
    # indices monotonically increasing too.
    anchors = [i for i in range(len(base)) if i in ml and i in md]

    merged = []
    ok = True
    prev_b, prev_l, prev_d = -1, -1, -1

    # Walk each real anchor, then a final sentinel covering the tail.
    for a_b in anchors + [None]:
        if a_b is None:
            b1, l1, d1 = len(base), len(local), len(disk)
        else:
            b1, l1, d1 = a_b, ml[a_b], md[a_b]

        base_chunk = base[prev_b + 1 : b1]
        local_chunk = local[prev_l + 1 : l1]
        disk_chunk = disk[prev_d + 1 : d1]

        if local_chunk == base_chunk:
            merged.extend(disk_chunk)  # only disk changed here
        elif disk_chunk == base_chunk:
            merged.extend(local_chunk)  # only local changed here
        elif local_chunk == disk_chunk:
            merged.extend(local_chunk)  # both made the same change
        else:
            ok = False  # both changed this region differently
            merged.extend(disk_chunk)

        if a_b is not None:
            merged.append(base[a_b])  # == local[l1] == disk[d1]
            prev_b, prev_l, prev_d = a_b, l1, d1

    return merged, ok


def play_sound_effect(name):
    """Play a sound effect by name. Supported: 'timer'."""
    if name not in _SOUNDS:
        logging.warning(f"Unknown sound effect: {name}")
        return
    path = random.choice(_SOUNDS[name])

    if playsound is None:
        return
    try:
        playsound(path, block=False)
    except Exception as e:
        logging.warning(f"Could not play {name} sound: {e}")


def compose_clock_notify_contents():
    now = datetime.now()
    tz = now.astimezone().strftime("%Z")
    title = now.strftime("%I:%M %p").lstrip("0") + " " + tz

    # Date and day-of-year
    day_of_year = now.timetuple().tm_yday
    year = now.year
    total_days = (
        366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    )
    body = now.strftime("%a, %b %d, %Y")

    return title, body


def extract_path_references(text: str) -> list[str]:
    """Extract all ((path)) references from text.

    Returns:
        List of path strings found within [[ ]]
    """
    return re.findall(r"\[\[(.*?)\]\]", text)


def apply_input_substitutions(text: str) -> str:
    if "{NOW}" in text:
        now_str = datetime.now().strftime("[%Y-%m-%d %H:%M]")
        text = re.sub(r"{NOW}", now_str, text)

    return text


def add_subtree(node, tree):
    for k, v in tree.items():
        child = node.add_child(k)
        if v:
            add_subtree(child, v)


def node_subtree_as_text(node) -> str:
    base_depth = node.depth
    lines = []

    def walk(n):
        lines.append("\t" * (n.depth - base_depth) + "- " + n.text)
        for child in n.children:
            walk(child)

    walk(node)
    return "\n".join(lines)


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


def convert_to_nested_list(lines):
    nested_list = []
    stack = [nested_list]  # Stack to hold the current nested list

    for line in lines:
        # Count the number of leading tabs
        len_a = len(line)
        len_b = len(line.lstrip("\t"))
        level = len_a - len_b
        # Strip leading tabs and any trailing whitespace
        current_entry = line.strip()

        # Ensure the stack is at the correct level
        while len(stack) > level + 1:
            stack.pop()

        # Append the current entry to the correct level
        current_list = stack[-1]
        # If current_entry is not empty, we can append it
        if current_entry:
            new_list = []  # Create a new list for nested items
            current_list.append((current_entry, new_list))  # Append as a tuple
            stack.append(new_list)  # Push new_list onto the stack

    # Convert tuples back into a simple list structure
    def simplify_structure(nested):
        return [
            item[0] if not item[1] else [item[0], simplify_structure(item[1])]
            for item in nested
        ]

    return simplify_structure(nested_list)


def normalize_indentation(lines):
    # first, figure out what indentation method is being used
    space_count = 0
    tab_count = 0

    tab_sizes = set()
    space_sizes = set()
    for line in lines:
        if line.lstrip() == line:
            continue
        nb_leading_spaces = len(line) - len(line.lstrip(" "))
        nb_leading_tabs = len(line) - len(line.lstrip("\t"))

        if nb_leading_spaces:
            space_count += 1
            space_sizes.add(nb_leading_spaces)
        if nb_leading_tabs:
            tab_count += 1
            tab_sizes.add(nb_leading_tabs)

    new_lines = []
    if space_count > tab_count:
        indent_size = min(space_sizes)
        for line in lines:
            nb_leading_spaces = len(line) - len(line.lstrip(" "))
            line = line.strip()
            line = line.lstrip("-*")
            line = (nb_leading_spaces // indent_size) * "\t" + line.strip()
            new_lines.append(line)
    elif tab_count:
        indent_size = min(tab_sizes)
        for line in lines:
            nb_leading_tabs = len(line) - len(line.lstrip("\t"))
            line = line.strip()
            line = line.lstrip("-*")
            line = (nb_leading_tabs // indent_size) * "\t" + line.strip()
            new_lines.append(line)
    else:
        return lines

    return new_lines
