"""obase: 物理具身通信网关 (基于 MQTT 协议)。不依赖上层模块。"""

from __future__ import annotations

import json
import logging
from typing import Any

__all__ = ["MQTTEdgeGateway", "MQTTGatewayError"]

logger = logging.getLogger(__name__)


class MQTTGatewayError(RuntimeError):
    """MQTT 网关错误."""


class MQTTEdgeGateway:
    """MQTT 边缘硬件通信网关.

    封装底层 MQTT 客户端，管理与物理硬件节点之间的持久化连接。
    支持 publish/subscribe，QoS 0/1/2，自动重连。
    惰性 import paho-mqtt（未安装时优雅降级）。
    """

    def __init__(
        self,
        broker_host: str = "127.0.0.1",
        port: int = 1883,
        client_id: str = "veya_embodied_core",
    ) -> None:
        self.broker_host = broker_host
        self.port = port
        self.client_id = client_id
        self.connected = False
        self._mqtt_available: bool | None = None
        self._client: Any = None

    @property
    def mqtt_available(self) -> bool:
        if self._mqtt_available is None:
            try:
                import paho.mqtt.client as _mqtt  # noqa: F401
                self._mqtt_available = True
            except ImportError:
                self._mqtt_available = False
        return self._mqtt_available

    def connect(self) -> bool:
        """连接到 MQTT Broker.

        Returns:
            True 如果连接成功
        """
        if not self.mqtt_available:
            logger.warning("paho-mqtt 未安装，MQTT 网关不可用")
            return False
        try:
            import paho.mqtt.client as mqtt
            self._client = mqtt.Client(client_id=self.client_id)
            self._client.connect(self.broker_host, self.port, keepalive=60)
            self._client.loop_start()
            self.connected = True
            return True
        except Exception as e:
            logger.error(f"Hardware Gateway connection failed: {e}")
            self.connected = False
            return False

    def publish(self, topic: str, payload: bytes, qos: int = 1) -> bool:
        """向物理节点发送序列化后的字节级硬件指令.

        Args:
            topic: MQTT 主题
            payload: 二进制载荷
            qos: QoS 级别 (0/1/2)

        Returns:
            True 如果发布成功
        """
        if not self.connected or self._client is None:
            return False
        try:
            result = self._client.publish(topic, payload, qos=qos)
            result.wait_for_publish(timeout=3.0)
            return result.is_published()
        except Exception as e:
            logger.error(f"MQTT publish failed: {e}")
            return False

    def subscribe(self, topic: str, qos: int = 1) -> bool:
        """订阅主题."""
        if not self.connected or self._client is None:
            return False
        try:
            self._client.subscribe(topic, qos=qos)
            return True
        except Exception:
            return False

    def disconnect(self) -> None:
        """断开连接并清理资源."""
        if self.connected and self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self.connected = False
            self._client = None

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self.connected else "disconnected",
            "broker": f"{self.broker_host}:{self.port}",
            "connected": self.connected,
            "mqtt_available": self.mqtt_available,
        }
