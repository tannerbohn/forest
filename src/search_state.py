from dataclasses import dataclass, field


@dataclass
class SearchState:
    matches: list = field(default_factory=list)
    index: int = 0
    query: str = ""
    context_node: object = None
    is_local: bool = False
    pre_search_position: tuple = (None, None)

    @property
    def active(self) -> bool:
        return bool(self.matches)

    def clear(self) -> None:
        self.matches = []
        self.index = 0
        self.query = ""
        self.context_node = None
        self.is_local = False
        self.pre_search_position = (None, None)

    def cycle(self, delta: int) -> None:
        if self.matches:
            self.index = (self.index + delta) % len(self.matches)

    @property
    def current_node(self):
        if self.matches:
            return self.matches[self.index % len(self.matches)]
        return None
