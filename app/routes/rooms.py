from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket

from app.auth import require_user_from_request, verify_supabase_access_token
from app.rooms_store import RoomsStore
from app.settings import feature_enabled

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ws_json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _limit_text(text: str, limit: int = 4000) -> str:
    t = (text or "").strip()
    if len(t) > limit:
        return t[:limit]
    return t


async def _broadcast(app, room_id: str, message: dict[str, Any]) -> None:
    payload = _ws_json(message)
    lock: asyncio.Lock = app.state.rooms_lock
    async with lock:
        peers = app.state.rooms_connections.get(room_id, {})
        websockets = [ws for ws in peers.values() if ws is not None]
    for ws in websockets:
        try:
            await ws.send_text(payload)
        except Exception:
            continue


@router.get("/api/rooms")
async def list_rooms(http_request: Request):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    store: RoomsStore = http_request.app.state.rooms_store
    rooms = await store.list_rooms_for_user(user_id)
    return {"rooms": rooms}


@router.post("/api/rooms")
async def create_room(body: dict[str, Any], http_request: Request):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    name = str((body or {}).get("name") or "Room")
    store: RoomsStore = http_request.app.state.rooms_store
    room = await store.create_room(user_id=user_id, name=name)
    return {"ok": True, "room": room.to_public(for_user_id=user_id)}


@router.post("/api/rooms/join")
async def join_room(body: dict[str, Any], http_request: Request):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    room_id = str((body or {}).get("roomId") or "").strip()
    if not room_id:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "roomId is required"})
    store: RoomsStore = http_request.app.state.rooms_store
    room = await store.get_room(room_id)
    if room and user_id in room.banned:
        raise HTTPException(status_code=403, detail={"code": "banned", "message": "You are banned from this room"})
    room = await store.join_room(room_id=room_id, user_id=user_id)
    if not room:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown roomId"})
    return {"ok": True, "room": room.to_public(for_user_id=user_id)}


@router.post("/api/rooms/{room_id}/leave")
async def leave_room(room_id: str, http_request: Request):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    store: RoomsStore = http_request.app.state.rooms_store
    ok = await store.leave_room(room_id=room_id, user_id=user_id)
    return {"ok": True, "left": ok}


@router.get("/api/rooms/{room_id}/messages")
async def room_messages(room_id: str, http_request: Request, limit: int = 50):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    store: RoomsStore = http_request.app.state.rooms_store
    room = await store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown roomId"})
    if user_id not in room.members:
        raise HTTPException(status_code=403, detail={"code": "not_member", "message": "Join the room first"})
    messages = await store.read_messages(room_id=room_id, limit=limit)
    return {"messages": messages}


@router.get("/api/rooms/{room_id}/members")
async def room_members(room_id: str, http_request: Request):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    store: RoomsStore = http_request.app.state.rooms_store
    room = await store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown roomId"})
    if user_id not in room.members:
        raise HTTPException(status_code=403, detail={"code": "not_member", "message": "Join the room first"})
    members = await store.list_members(room_id=room_id)
    return {"members": members or [], "myRole": room.roles.get(user_id, "member")}


@router.post("/api/rooms/{room_id}/kick")
async def room_kick(room_id: str, body: dict[str, Any], http_request: Request):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    actor_id = str(user.get("id") or "")
    target_id = str((body or {}).get("userId") or "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "userId is required"})
    store: RoomsStore = http_request.app.state.rooms_store
    room = await store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown roomId"})
    if actor_id not in room.members:
        raise HTTPException(status_code=403, detail={"code": "not_member", "message": "Join the room first"})
    actor_role = (room.roles.get(actor_id) or "member").lower()
    if actor_role not in {"owner", "moderator"}:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Insufficient privileges"})
    if target_id == room.owner_user_id:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Cannot kick the owner"})
    ok = await store.kick_member(room_id=room_id, user_id=target_id)
    return {"ok": True, "kicked": ok}


@router.post("/api/rooms/{room_id}/ban")
async def room_ban(room_id: str, body: dict[str, Any], http_request: Request):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    actor_id = str(user.get("id") or "")
    target_id = str((body or {}).get("userId") or "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "userId is required"})
    store: RoomsStore = http_request.app.state.rooms_store
    room = await store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown roomId"})
    if actor_id not in room.members:
        raise HTTPException(status_code=403, detail={"code": "not_member", "message": "Join the room first"})
    actor_role = (room.roles.get(actor_id) or "member").lower()
    if actor_role not in {"owner", "moderator"}:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Insufficient privileges"})
    if target_id == room.owner_user_id:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Cannot ban the owner"})
    ok = await store.ban_member(room_id=room_id, user_id=target_id)
    return {"ok": True, "banned": ok}


@router.put("/api/rooms/{room_id}/roles")
async def room_set_role(room_id: str, body: dict[str, Any], http_request: Request):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    actor_id = str(user.get("id") or "")
    target_id = str((body or {}).get("userId") or "").strip()
    role = str((body or {}).get("role") or "").strip().lower()
    if not target_id or not role:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "userId and role are required"})
    store: RoomsStore = http_request.app.state.rooms_store
    room = await store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown roomId"})
    if actor_id not in room.members:
        raise HTTPException(status_code=403, detail={"code": "not_member", "message": "Join the room first"})
    actor_role = (room.roles.get(actor_id) or "member").lower()
    if actor_role != "owner":
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Owner privileges required"})
    ok = await store.set_role(room_id=room_id, user_id=target_id, role=role)
    return {"ok": True, "updated": ok}


@router.get("/api/rooms/{room_id}/peers")
async def room_peers(room_id: str, http_request: Request):
    if not feature_enabled("rooms"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Rooms are disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    store: RoomsStore = http_request.app.state.rooms_store
    room = await store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown roomId"})
    if user_id not in room.members:
        raise HTTPException(status_code=403, detail={"code": "not_member", "message": "Join the room first"})
    lock: asyncio.Lock = http_request.app.state.rooms_lock
    async with lock:
        peers = http_request.app.state.rooms_connections.get(room_id, {})
        return {"peers": sorted(peers.keys())}


@router.websocket("/ws/rooms")
async def websocket_rooms(websocket: WebSocket):
    await websocket.accept()

    if not feature_enabled("rooms"):
        await websocket.send_text(_ws_json({"type": "error", "message": "rooms_disabled"}))
        await websocket.close()
        return

    token = (websocket.query_params.get("token") or "").strip()
    room_id = (websocket.query_params.get("roomId") or "").strip()
    device_id = (websocket.query_params.get("deviceId") or "").strip()

    if not token:
        await websocket.send_text(_ws_json({"type": "error", "message": "missing_token"}))
        await websocket.close()
        return
    if not room_id:
        await websocket.send_text(_ws_json({"type": "error", "message": "missing_room_id"}))
        await websocket.close()
        return
    if not device_id:
        await websocket.send_text(_ws_json({"type": "error", "message": "missing_device_id"}))
        await websocket.close()
        return
    if len(device_id) > 80:
        await websocket.send_text(_ws_json({"type": "error", "message": "invalid_device_id"}))
        await websocket.close()
        return

    try:
        user = await verify_supabase_access_token(token)
    except HTTPException:
        await websocket.send_text(_ws_json({"type": "error", "message": "unauthorized"}))
        await websocket.close()
        return

    user_id = str(user.get("id") or "")
    store: RoomsStore = websocket.app.state.rooms_store
    room = await store.get_room(room_id)
    if room and user_id in room.banned:
        await websocket.send_text(_ws_json({"type": "error", "message": "banned"}))
        await websocket.close()
        return
    room = await store.join_room(room_id=room_id, user_id=user_id)
    if not room:
        await websocket.send_text(_ws_json({"type": "error", "message": "unknown_room"}))
        await websocket.close()
        return

    lock: asyncio.Lock = websocket.app.state.rooms_lock
    async with lock:
        peers = websocket.app.state.rooms_connections.setdefault(room_id, {})
        peers[device_id] = websocket
        snapshot = sorted(peers.keys())

    await websocket.send_text(_ws_json({"type": "presence.snapshot", "roomId": room_id, "peers": snapshot}))
    await _broadcast(websocket.app, room_id, {"type": "presence.join", "roomId": room_id, "deviceId": device_id})

    try:
        while True:
            raw = await websocket.receive_text()
            raw = (raw or "").strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                await websocket.send_text(_ws_json({"type": "error", "message": "invalid_json"}))
                continue
            if not isinstance(msg, dict):
                continue

            mtype = str(msg.get("type") or "").strip()
            if mtype == "chat.send":
                text = _limit_text(str(msg.get("text") or ""))
                if not text:
                    continue
                client_id = str(msg.get("clientId") or "").strip()
                if not client_id or len(client_id) > 120:
                    client_id = str(uuid.uuid4())
                chat_msg = {
                    "type": "chat.message",
                    "id": client_id,
                    "roomId": room_id,
                    "ts": _now_iso(),
                    "fromDeviceId": device_id,
                    "text": text,
                }
                await store.append_message(room_id=room_id, message=chat_msg)
                await _broadcast(websocket.app, room_id, chat_msg)
            elif mtype == "signal":
                to_device = str(msg.get("toDeviceId") or "").strip()
                payload = msg.get("payload")
                if not isinstance(payload, dict):
                    continue
                forward = {
                    "type": "signal",
                    "roomId": room_id,
                    "fromDeviceId": device_id,
                    "toDeviceId": to_device or None,
                    "payload": payload,
                }
                if not to_device:
                    await _broadcast(websocket.app, room_id, forward)
                    continue
                async with lock:
                    peers = websocket.app.state.rooms_connections.get(room_id, {})
                    target = peers.get(to_device)
                if target is not None:
                    try:
                        await target.send_text(_ws_json(forward))
                    except Exception:
                        pass
            else:
                await websocket.send_text(_ws_json({"type": "error", "message": "unknown_type"}))
    finally:
        async with lock:
            peers = websocket.app.state.rooms_connections.get(room_id, {})
            if peers.get(device_id) is websocket:
                peers.pop(device_id, None)
            if not peers:
                websocket.app.state.rooms_connections.pop(room_id, None)
        await _broadcast(websocket.app, room_id, {"type": "presence.leave", "roomId": room_id, "deviceId": device_id})
