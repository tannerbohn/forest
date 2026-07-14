"""Browser-style back/forward history of context changes.

Pure data structure: stores a flat list of visited ``(context_node, cursor_node)``
positions plus an index into it (like a browser's session history). Committed
navigations append a destination (truncating any forward entries); back/forward
just move the index. Liveness of stored nodes is validated by the caller.
"""


class ContextHistory:
    def __init__(self, max_depth: int = 50):
        self._max_depth = max_depth
        self._entries: list[tuple] = []
        self._index: int = -1

    def seed(self, context_node, cursor_node):
        """Initialize the first entry (the position present at load)."""
        self._entries = [(context_node, cursor_node)]
        self._index = 0

    def mark_leaving(self, context_node, cursor_node):
        """Refresh the current entry's cursor to where it actually sits in the
        context we're about to leave, so stepping back restores that position
        rather than the (stale) cursor captured when we first arrived.

        Guarded by context identity: if the current context no longer matches
        the current entry (e.g. a search preview has drifted the context), the
        entry is left untouched.
        """
        if 0 <= self._index < len(self._entries):
            ctx, _ = self._entries[self._index]
            if ctx is context_node:
                self._entries[self._index] = (context_node, cursor_node)

    def record(self, context_node, cursor_node):
        """Append a committed destination.

        Skips consecutive duplicates, drops any forward entries (a new
        navigation abandons the forward path), and caps the list length.
        """
        entry = (context_node, cursor_node)
        if (
            0 <= self._index < len(self._entries)
            and self._entries[self._index] == entry
        ):
            return
        del self._entries[self._index + 1 :]
        self._entries.append(entry)
        self._index = len(self._entries) - 1
        if len(self._entries) > self._max_depth:
            drop = len(self._entries) - self._max_depth
            del self._entries[:drop]
            self._index -= drop

    def back(self):
        """Step back one entry. Returns ``(context, cursor)`` or ``None``."""
        if self._index > 0:
            self._index -= 1
            return self._entries[self._index]
        return None

    def forward(self):
        """Step forward one entry. Returns ``(context, cursor)`` or ``None``."""
        if self._index < len(self._entries) - 1:
            self._index += 1
            return self._entries[self._index]
        return None
