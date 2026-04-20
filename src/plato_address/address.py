"""Room addressing and navigation protocol."""
import time
import fnmatch
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
    last_heartbeat: float = field(default_factory=time.time)
    heartbeat_interval: float = 60.0

    @property
    def is_healthy(self) -> bool:
        """Return True if the room's heartbeat is within its interval."""
        if self.heartbeat_interval <= 0:
            return True
        return (time.time() - self.last_heartbeat) <= self.heartbeat_interval


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


@dataclass
class ServiceRecord:
    name: str
    room: str
    endpoint: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    heartbeat_interval: float = 60.0

    @property
    def is_healthy(self) -> bool:
        """Return True if the service's heartbeat is within its interval."""
        if self.heartbeat_interval <= 0:
            return True
        return (time.time() - self.last_heartbeat) <= self.heartbeat_interval


class AddressBook:
    def __init__(self):
        self._rooms: dict[str, RoomAddress] = {}
        self._services: dict[str, ServiceRecord] = {}
        self._room_services: dict[str, set[str]] = {}

    # ------------------------------------------------------------------ #
    # Room management
    # ------------------------------------------------------------------ #

    def add_room(
        self,
        name: str,
        domain: str = "",
        parent: str = "",
        heartbeat_interval: float = 60.0,
        **meta,
    ) -> RoomAddress:
        if name in self._rooms:
            raise ValueError(f"Address conflict: room '{name}' already exists.")
        addr = RoomAddress(
            name=name,
            domain=domain,
            parent=parent,
            metadata=meta,
            heartbeat_interval=heartbeat_interval,
        )
        self._rooms[name] = addr
        if parent and parent in self._rooms:
            if name not in self._rooms[parent].children:
                self._rooms[parent].children.append(name)
        return addr

    def add_rooms(self, rooms: list[dict]) -> list[RoomAddress]:
        """Bulk-add rooms.

        Each dict should contain keys suitable for ``add_room``:
        ``name``, ``domain``, ``parent``, etc.
        """
        added = []
        for spec in rooms:
            spec = dict(spec)
            name = spec.pop("name")
            added.append(self.add_room(name, **spec))
        return added

    def get_room(self, name: str) -> Optional[RoomAddress]:
        return self._rooms.get(name)

    def get_rooms(self, names: list[str]) -> dict[str, Optional[RoomAddress]]:
        """Bulk lookup rooms by name."""
        return {name: self._rooms.get(name) for name in names}

    def remove_room(self, name: str) -> bool:
        """Remove a room and any services registered to it."""
        if name not in self._rooms:
            return False
        room = self._rooms.pop(name)
        if room.parent and room.parent in self._rooms:
            if room.name in self._rooms[room.parent].children:
                self._rooms[room.parent].children.remove(room.name)
        for svc_name in list(self._room_services.get(name, set())):
            self.deregister_service(svc_name)
        self._room_services.pop(name, None)
        return True

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
        return [
            r for n, r in self._rooms.items()
            if q in n.lower() or q in r.domain.lower()
        ]

    # ------------------------------------------------------------------ #
    # Address resolution (dotted / subnet style)
    # ------------------------------------------------------------------ #

    def resolve(self, dotted: str) -> list[RoomAddress]:
        """Resolve a dotted address pattern.

        Supports exact matches (``general.alpha.1``) and wildcard subnets
        (``general.*``, ``general.alpha.*``).
        """
        parts = dotted.split(".")
        matches = []
        for name, room in self._rooms.items():
            path = self.path_to(name)
            if self._path_matches(path, parts):
                matches.append(room)
        return matches

    @staticmethod
    def _path_matches(path: list[str], pattern_parts: list[str]) -> bool:
        if len(path) < len(pattern_parts):
            return False
        for path_part, pat_part in zip(path, pattern_parts):
            if pat_part == "*":
                continue
            if not fnmatch.fnmatch(path_part, pat_part):
                return False
        return len(path) == len(pattern_parts)

    # ------------------------------------------------------------------ #
    # Heartbeat
    # ------------------------------------------------------------------ #

    def heartbeat_room(self, name: str) -> bool:
        """Record a heartbeat for a room."""
        room = self._rooms.get(name)
        if not room:
            return False
        room.last_heartbeat = time.time()
        return True

    def heartbeat_service(self, svc_name: str) -> bool:
        """Record a heartbeat for a service."""
        svc = self._services.get(svc_name)
        if not svc:
            return False
        svc.last_heartbeat = time.time()
        return True

    def unhealthy_rooms(self) -> list[RoomAddress]:
        """Return rooms whose heartbeat has expired."""
        return [r for r in self._rooms.values() if not r.is_healthy]

    def healthy_rooms(self) -> list[RoomAddress]:
        """Return rooms whose heartbeat is still valid."""
        return [r for r in self._rooms.values() if r.is_healthy]

    # ------------------------------------------------------------------ #
    # Service discovery
    # ------------------------------------------------------------------ #

    def register_service(
        self,
        name: str,
        room: str,
        endpoint: Optional[str] = None,
        heartbeat_interval: float = 60.0,
        **meta,
    ) -> ServiceRecord:
        if name in self._services:
            raise ValueError(f"Address conflict: service '{name}' already registered.")
        if room not in self._rooms:
            raise ValueError(f"Room '{room}' does not exist.")
        svc = ServiceRecord(
            name=name,
            room=room,
            endpoint=endpoint,
            metadata=meta,
            heartbeat_interval=heartbeat_interval,
        )
        self._services[name] = svc
        self._room_services.setdefault(room, set()).add(name)
        return svc

    def register_services(self, services: list[dict]) -> list[ServiceRecord]:
        """Bulk-register services.

        Each dict should contain keys suitable for ``register_service``:
        ``name``, ``room``, ``endpoint``, etc.
        """
        added = []
        for spec in services:
            spec = dict(spec)
            name = spec.pop("name")
            added.append(self.register_service(name, **spec))
        return added

    def deregister_service(self, name: str) -> bool:
        if name not in self._services:
            return False
        svc = self._services.pop(name)
        self._room_services.get(svc.room, set()).discard(name)
        return True

    def find_service(self, name: str) -> Optional[ServiceRecord]:
        return self._services.get(name)

    def find_services(self, names: list[str]) -> dict[str, Optional[ServiceRecord]]:
        """Bulk lookup services by name."""
        return {name: self._services.get(name) for name in names}

    def services_in_room(self, room: str) -> list[ServiceRecord]:
        """Return all services registered to a given room."""
        return [
            self._services[name]
            for name in self._room_services.get(room, set())
            if name in self._services
        ]

    def discover(self, room_pattern: str) -> list[ServiceRecord]:
        """Discover services in rooms matching a dotted address pattern."""
        rooms = self.resolve(room_pattern)
        results = []
        for room in rooms:
            results.extend(self.services_in_room(room.name))
        return results

    def healthy_services(self) -> list[ServiceRecord]:
        return [s for s in self._services.values() if s.is_healthy]

    def unhealthy_services(self) -> list[ServiceRecord]:
        return [s for s in self._services.values() if not s.is_healthy]

    # ------------------------------------------------------------------ #
    # Conflict detection helpers
    # ------------------------------------------------------------------ #

    def room_exists(self, name: str) -> bool:
        return name in self._rooms

    def service_exists(self, name: str) -> bool:
        return name in self._services

    def conflicts(self, room_name: Optional[str] = None, service_name: Optional[str] = None) -> list[str]:
        """Return a list of conflicting names already in use."""
        found = []
        if room_name and room_name in self._rooms:
            found.append(room_name)
        if service_name and service_name in self._services:
            found.append(service_name)
        return found

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #

    @property
    def stats(self) -> dict:
        roots = sum(1 for r in self._rooms.values() if not r.parent)
        return {
            "rooms": len(self._rooms),
            "roots": roots,
            "services": len(self._services),
            "healthy_rooms": len(self.healthy_rooms()),
            "healthy_services": len(self.healthy_services()),
        }
