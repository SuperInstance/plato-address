"""Room addressing and navigation protocol."""
import time
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

@dataclass
class RoomAddress:
    name: str
    domain: str = "general"
    parent: str = ""
    children: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

@dataclass
class NavEntry:
    room: str
    timestamp: float = field(default_factory=time.time)
    action: str = "enter"

class NavHistory:
    def __init__(self, max_size: int = 100):
        self._history: deque = deque(maxlen=max_size)
        self._position = -1

    def push(self, room: str, action: str = "enter"):
        self._history.append(NavEntry(room=room, action=action))
        self._position = len(self._history) - 1

    def back(self) -> Optional[str]:
        if self._position > 0:
            self._position -= 1
            return self._history[self._position].room
        return None

    def forward(self) -> Optional[str]:
        if self._position < len(self._history) - 1:
            self._position += 1
            return self._history[self._position].room
        return None

    def current(self) -> Optional[str]:
        if self._history:
            return self._history[self._position].room
        return None

    def breadcrumbs(self, n: int = 10) -> list[str]:
        return [e.room for e in list(self._history)[-n:]]

    @property
    def stats(self) -> dict:
        return {"entries": len(self._history), "position": self._position}

class AddressBook:
    def __init__(self):
        self._rooms: dict[str, RoomAddress] = {}

    def add_room(self, name: str, domain: str = "", parent: str = "", **meta) -> RoomAddress:
        addr = RoomAddress(name=name, domain=domain, parent=parent, metadata=meta)
        self._rooms[name] = addr
        if parent and parent in self._rooms:
            if name not in self._rooms[parent].children:
                self._rooms[parent].children.append(name)
        return addr

    def get_room(self, name: str) -> Optional[RoomAddress]:
        return self._rooms.get(name)

    def children_of(self, name: str) -> list[str]:
        room = self._rooms.get(name)
        return room.children if room else []

    def path_to(self, name: str) -> list[str]:
        path = []
        current = name
        while current:
            path.append(current)
            room = self._rooms.get(current)
            current = room.parent if room else None
        return list(reversed(path))

    def search(self, query: str) -> list[RoomAddress]:
        q = query.lower()
        return [r for n, r in self._rooms.items() if q in n.lower() or q in r.domain.lower()]

    @property
    def stats(self) -> dict:
        roots = sum(1 for r in self._rooms.values() if not r.parent)
        return {"rooms": len(self._rooms), "roots": roots}
