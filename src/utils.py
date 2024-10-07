import os

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
