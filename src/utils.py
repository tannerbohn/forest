import logging
import os
import random
import re
import urllib.request
from datetime import datetime

from playsound3 import playsound

_ASSETS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "sound_effects")
)

_SOUNDS = {
    "intro": [
        os.path.join(_ASSETS_DIR, "wave_1.wav"),
        os.path.join(_ASSETS_DIR, "wave_2.mp3"),
        os.path.join(_ASSETS_DIR, "wave_3.mp3"),
        os.path.join(_ASSETS_DIR, "wave_4.wav"),
    ],
    "timer": [os.path.join(_ASSETS_DIR, "notification_1.mp3")],
}


def play_sound_effect(name):
    """Play a sound effect by name. Supported: 'intro', 'timer'."""
    if name not in _SOUNDS:
        logging.warning(f"Unknown sound effect: {name}")
        return
    path = random.choice(_SOUNDS[name])

    try:
        playsound(path, block=False)
    except Exception as e:
        logging.warning(f"Could not play {name} sound: {e}")


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


def compose_clock_notify_contents(location=None):
    now = datetime.now()
    tz = now.astimezone().strftime("%Z")
    title = now.strftime("%I:%M %p").lstrip("0") + " " + tz

    # Date and day-of-year
    day_of_year = now.timetuple().tm_yday
    year = now.year
    total_days = (
        366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    )
    days_remaining = total_days - day_of_year

    body = now.strftime("%a, %b %d, %Y")
    # body += f"\n{year} is {100*day_of_year/total_days:.1f}% over."

    # if location:
    #     title = f"{title} - {location}"
    #     try:
    #         loc_encoded = urllib.request.quote(location)
    #         url = f"https://wttr.in/{loc_encoded}?format=%C+%t+%m+%S+%s"
    #         resp = urllib.request.urlopen(url, timeout=3)
    #         parts = resp.read().decode().strip()
    #         # Format: "Condition +Temp MoonEmoji Sunrise Sunset"
    #         # Split from the right to isolate sunrise/sunset times
    #         tokens = parts.rsplit(" ", 2)
    #         if len(tokens) == 3:
    #             weather_and_moon, sunrise, sunset = tokens
    #             body += f"\n{location}: {weather_and_moon}"
    #             body += f"\nSunrise {sunrise}  Sunset {sunset}"
    #         else:
    #             body += f"\n{location}: {parts}"
    #     except Exception as e:
    #         logging.error(f"Failed to get weather: {e}")

    return title, body


def extract_path_references(text: str) -> list[str]:
    """Extract all ((path)) references from text.

    Returns:
        List of path strings found within (( ))
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


def determine_state_filename(filepath):
    path_parts = os.path.split(filepath)
    filename = path_parts[-1]
    filename_without_ext = filename.rsplit(".", 1)[0]

    return os.path.join(
        *path_parts[:-1], "states", f"{filename_without_ext}_state.json"
    )


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
