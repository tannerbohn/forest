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

    return os.path.join(*path_parts[:-1], "states", f"{filename_without_ext}_state.json")


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
