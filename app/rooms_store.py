from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.storage import global_data_dir


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rooms_path() -> Path:
    return global_data_dir() / "rooms.json"


def _messages_dir() -> Path:
    p = global_data_dir() / "rooms"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _messages_path(room_id: str) -> Path:
    p = _messages_dir() / room_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "messages.jsonl"


@dataclass
class Room:
    id: str
    name: str
    created_at: str
    owner_user_id: str
    members: set[str] = field(default_factory=set)

    def to_public(self, *, for_user_id: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "createdAt": self.created_at,
            "ownerUserId": self.owner_user_id,
            "memberCount": len(self.members),
            "isMember": for_user_id in self.members,
        }


class RoomsStore:
    """
    Minimal shared rooms registry + message persistence.

    - Rooms are stored globally (single-container / HF Space).
    - Membership is enforced server-side for message history and WebSocket access.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rooms: dict[str, Room] = {}
        self._load()

    def _load(self) -> None:
        path = _rooms_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception:
            return
        rooms = data.get("rooms") if isinstance(data, dict) else None
        if not isinstance(rooms, list):
            return
        for r in rooms:
            if not isinstance(r, dict):
                continue
            rid = str(r.get("id") or "").strip()
            name = str(r.get("name") or "Room").strip()
            created_at = str(r.get("createdAt") or _now_iso()).strip()
            owner = str(r.get("ownerUserId") or "").strip()
            members = set(str(x) for x in (r.get("members") or []) if str(x).strip())
            if not rid or not owner:
                continue
            self._rooms[rid] = Room(id=rid, name=name, created_at=created_at, owner_user_id=owner, members=members)

    def _save(self) -> None:
        path = _rooms_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        rooms = []
        for r in self._rooms.values():
            rooms.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "createdAt": r.created_at,
                    "ownerUserId": r.owner_user_id,
                    "members": sorted(r.members),
                }
            )
        payload = {"version": 1, "rooms": rooms}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    async def list_rooms_for_user(self, user_id: str) -> list[dict[str, Any]]:
        uid = str(user_id or "").strip()
        async with self._lock:
            out = []
            for r in self._rooms.values():
                if uid in r.members:
                    out.append(r.to_public(for_user_id=uid))
            out.sort(key=lambda x: str(x.get("createdAt") or ""), reverse=True)
            return out

    async def create_room(self, *, user_id: str, name: str | None = None) -> Room:
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id required")
        room_id = str(uuid.uuid4())
        nm = (name or "Room").strip()[:80] or "Room"
        room = Room(id=room_id, name=nm, created_at=_now_iso(), owner_user_id=uid, members={uid})
        async with self._lock:
            self._rooms[room_id] = room
            self._save()
        return room

    async def get_room(self, room_id: str) -> Room | None:
        rid = str(room_id or "").strip()
        async with self._lock:
            return self._rooms.get(rid)

    async def join_room(self, *, room_id: str, user_id: str) -> Room | None:
        rid = str(room_id or "").strip()
        uid = str(user_id or "").strip()
        if not rid or not uid:
            return None
        async with self._lock:
            room = self._rooms.get(rid)
            if not room:
                return None
            room.members.add(uid)
            self._save()
            return room

    async def leave_room(self, *, room_id: str, user_id: str) -> bool:
        rid = str(room_id or "").strip()
        uid = str(user_id or "").strip()
        if not rid or not uid:
            return False
        async with self._lock:
            room = self._rooms.get(rid)
            if not room:
                return False
            room.members.discard(uid)
            # Owner-less or empty rooms are pruned.
            if not room.members or room.owner_user_id not in room.members:
                self._rooms.pop(rid, None)
            self._save()
            return True

    async def append_message(self, *, room_id: str, message: dict[str, Any]) -> None:
        rid = str(room_id or "").strip()
        if not rid:
            return
        path = _messages_path(rid)
        try:
            path.touch(exist_ok=True)
        except Exception:
            return
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(message, ensure_ascii=False) + "\n")
        except Exception:
            return

    async def read_messages(self, *, room_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rid = str(room_id or "").strip()
        if not rid:
            return []
        path = _messages_path(rid)
        if not path.exists():
            return []
        max_lines = max(1, min(int(limit or 50), 200))
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return []
        out = []
        for line in lines[-max_lines:]:
            line = (line or "").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
        return out
