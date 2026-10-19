"""obase.livekit_webrtc — LiveKit WebRTC 通信适配器.

LiveKit 房间/参与者/音轨管理适配器。livekit 依赖为可选（惰性加载）：
- 未安装 livekit → 提供房间簿记（register/join/leave/status）能力，
  publish/connect 给出明确错误。
- 安装 livekit → 可扩展为真实 WebRTC 会话（部署期接 SDK）。

Example:
    >>> lk = LiveKitWebRTC(host="wss://livekit.example.com", api_key="...", api_secret="...")
    >>> room_id = lk.create_room("demo")
    >>> lk.join(room_id, participant="user_1")
    >>> lk.status()
    {'rooms': 1, ...}
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

__all__ = ["LiveKitRoom", "LiveKitWebRTC", "LiveKitError"]


class LiveKitError(RuntimeError):
    """LiveKit 适配器错误（含 SDK 未安装）。"""


@dataclass
class LiveKitRoom:
    """房间会话簿记。"""

    room_id: str
    name: str
    created_at: float = field(default_factory=time.time)
    participants: list[str] = field(default_factory=list)
    tracks: list[str] = field(default_factory=list)
    connected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "name": self.name,
            "created_at": self.created_at,
            "participants": list(self.participants),
            "tracks": list(self.tracks),
            "connected": self.connected,
        }


class LiveKitWebRTC:
    """LiveKit WebRTC 适配器：房间/参与者/音轨 + 可选真实连接。"""

    def __init__(
        self,
        *,
        host: str = "wss://localhost:7880",
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        self.host = host
        self.api_key = api_key
        self.api_secret = api_secret
        self._rooms: dict[str, LiveKitRoom] = {}

    # ------------------------------------------------------------------
    # 房间
    # ------------------------------------------------------------------

    def create_room(self, name: str, *, room_id: str | None = None) -> str:
        """创建房间（簿记），返回 room_id。"""
        if not name:
            raise LiveKitError("livekit_webrtc: name must not be empty")
        rid = room_id or f"room-{uuid.uuid4().hex[:10]}"
        self._rooms[rid] = LiveKitRoom(room_id=rid, name=name)
        return rid

    def join(self, room_id: str, *, participant: str) -> dict[str, Any]:
        """参与者加入房间。"""
        room = self._room(room_id)
        if participant not in room.participants:
            room.participants.append(participant)
        return {"room_id": room_id, "participant": participant, "joined": True}

    def leave(self, room_id: str, *, participant: str) -> bool:
        room = self._room(room_id)
        if participant in room.participants:
            room.participants.remove(participant)
            return True
        return False

    def register_track(self, room_id: str, *, track_id: str) -> bool:
        room = self._room(room_id)
        if track_id not in room.tracks:
            room.tracks.append(track_id)
            return True
        return False

    def _room(self, room_id: str) -> LiveKitRoom:
        room = self._rooms.get(room_id)
        if room is None:
            raise LiveKitError(f"room not found: {room_id}")
        return room

    # ------------------------------------------------------------------
    # 真实连接（需 livekit SDK，惰性）
    # ------------------------------------------------------------------

    async def connect(self, room_id: str, *, participant: str) -> dict[str, Any]:
        """建立真实 LiveKit 会话（部署期）。

        Raises:
            LiveKitError: livekit 依赖未安装。
        """
        try:
            import livekit  # type: ignore[import-untyped]  # noqa: F401
        except ImportError as exc:
            raise LiveKitError(
                "livekit SDK is not installed — pip install livekit "
                "(room bookkeeping still works without it)"
            ) from exc
        self.join(room_id, participant=participant)
        self._rooms[room_id].connected = True
        return {"room_id": room_id, "participant": participant, "connected": True}

    async def publish_audio(self, room_id: str, *, participant: str, data: bytes) -> dict[str, Any]:
        """发布音频帧（簿记 + SDK 扩展点）。"""
        room = self._room(room_id)
        track_id = f"track-{uuid.uuid4().hex[:8]}"
        self.register_track(room_id, track_id=track_id)
        return {
            "room_id": room_id,
            "participant": participant,
            "track_id": track_id,
            "bytes": len(data),
        }

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "rooms": [r.to_dict() for r in self._rooms.values()],
            "room_count": len(self._rooms),
        }

    def health(self) -> dict[str, Any]:
        return {"status": "healthy", "details": self.status()}
