from .preflight import needed_space


def fit(items, free):
    chosen = []
    left = []
    room = free
    for item in sorted(items, key=lambda entry: entry.size, reverse=True):
        needed = needed_space(item.size)
        if needed <= room:
            chosen.append(item)
            room -= needed
        else:
            left.append(item)
    return chosen, left
