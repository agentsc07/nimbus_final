"""Switchable local MQTT transport for Nimbus.

Supports the six canonical topics defined in contracts/topics.md:
  nimbus/{cluster_id}/lease       (cloud -> edge)
  nimbus/{cluster_id}/renewal     (cloud -> edge)
  nimbus/{cluster_id}/probe       (cloud -> edge)
  nimbus/{cluster_id}/notice      (cloud -> edge)
  nimbus/{cluster_id}/escalation  (edge -> cloud)
  nimbus/{cluster_id}/checkin     (edge -> cloud)

Can connect to a local broker (e.g. Mosquitto via paho-mqtt) or use an
in-process stand-in broker when paho is missing or NIMBUS_MQTT_STANDIN=1 is set.
The paho client connects in plaintext without credentials, so it suits a local
Mosquitto only; AWS IoT Core (TLS + X.509) is not supported by this module.
While disconnected, publishes wait in a bounded buffer (MAX_PENDING messages);
when it is full the oldest message is dropped, counted in `dropped_messages`
and logged as a warning.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Callable

logger = logging.getLogger("nimbus.mqtt")

CANONICAL_MESSAGE_TYPES = ("lease", "escalation", "checkin", "renewal", "probe", "notice")


def canonical_topic(cluster_id: str, message_type: str) -> str:
    """Format one of the five canonical topic names."""
    if message_type not in CANONICAL_MESSAGE_TYPES:
        raise ValueError(f"unknown canonical message type: {message_type}")
    return f"nimbus/{cluster_id}/{message_type}"


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT topic matching with single-level wildcard '+'."""
    pattern_parts = pattern.split("/")
    topic_parts = topic.split("/")
    if len(pattern_parts) != len(topic_parts):
        return False
    for p, t in zip(pattern_parts, topic_parts):
        if p == "+":
            continue
        if p != t:
            return False
    return True


class InMemoryBroker:
    """Thread-safe in-process stand-in broker for zero-dependency local runs and tests."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: list[tuple[str, Callable[[str, bytes], None]]] = []

    def subscribe(self, pattern: str, callback: Callable[[str, bytes], None]) -> None:
        with self._lock:
            self._subscribers.append((pattern, callback))

    def unsubscribe(self, callback: Callable[[str, bytes], None]) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s[1] != callback]

    def publish(self, topic: str, payload: bytes) -> None:
        with self._lock:
            targets = [cb for pat, cb in self._subscribers if topic_matches(pat, topic)]
        for cb in targets:
            try:
                cb(topic, payload)
            except Exception as exc:
                logger.warning("Error in stand-in MQTT subscriber for %s: %s", topic, exc)

    def reset(self) -> None:
        with self._lock:
            self._subscribers.clear()


_GLOBAL_STANDIN_BROKER = InMemoryBroker()

MAX_PENDING = 500  # messages buffered while disconnected; beyond this the oldest is dropped


class _OfflineBuffer:
    """Bounded, ordered buffer for messages published while the client is disconnected."""

    connected: bool

    def _init_buffer(self) -> None:
        self._pending_messages: list[tuple[str, bytes]] = []
        self._pending_lock = threading.Lock()
        self.dropped_messages = 0  # buffered messages evicted because the buffer was full

    def _buffer_if_offline(self, topic: str, raw: bytes, force: bool = False) -> bool:
        """Buffer the message when disconnected (or when `force`); False means the caller should send it now."""
        evicted = None
        with self._pending_lock:
            if self.connected and not force:
                return False
            if len(self._pending_messages) >= MAX_PENDING:
                evicted = self._pending_messages.pop(0)
                self.dropped_messages += 1
            self._pending_messages.append((topic, raw))
            depth, dropped = len(self._pending_messages), self.dropped_messages
        if evicted is not None:
            logger.warning("MQTT offline buffer full (%d); dropped the oldest message, for %s (%d dropped so far)",
                           MAX_PENDING, evicted[0], dropped)
        logger.info("MQTT disconnected; buffered message for %s (pending: %d)", topic, depth)
        return True

    def _flush_then_mark_connected(self, send: Callable[[str, bytes], None]) -> None:
        """Send the buffer in order, then mark the client connected. Messages published while the buffer is being
        sent are buffered behind it and go out in the next round, so a new message never overtakes an older one."""
        while True:
            with self._pending_lock:
                batch = list(self._pending_messages)
                self._pending_messages.clear()
                if not batch:
                    self.connected = True
                    return
            for topic, raw in batch:
                try:
                    send(topic, raw)
                except Exception as exc:
                    logger.warning("Error flushing pending message to %s: %s", topic, exc)


class StandinMQTTClient(_OfflineBuffer):
    """Client backed by the in-memory broker."""

    def __init__(self, broker: InMemoryBroker | None = None):
        self.broker = broker or _GLOBAL_STANDIN_BROKER
        self._subscriptions: list[tuple[str, Callable[[str, dict], None]]] = []
        self._subs_lock = threading.Lock()
        self._running = False
        self.connected = True
        self._init_buffer()

    def subscribe(self, pattern: str, handler: Callable[[str, dict], None]) -> None:
        with self._subs_lock:
            self._subscriptions.append((pattern, handler))
        if self._running and self.connected:
            self._register(pattern, handler)

    def _register(self, pattern: str, handler: Callable[[str, dict], None]) -> None:
        def _wrapper(topic: str, payload_bytes: bytes) -> None:
            try:
                data = json.loads(payload_bytes.decode("utf-8"))
            except Exception as e:
                logger.warning("Failed to parse JSON on topic %s: %s", topic, e)
                return
            handler(topic, data)

        self.broker.subscribe(pattern, _wrapper)

    def publish(self, topic: str, payload: dict | str | bytes) -> None:
        if isinstance(payload, dict):
            raw = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, str):
            raw = payload.encode("utf-8")
        else:
            raw = payload

        if self._buffer_if_offline(topic, raw):
            return

        self.broker.publish(topic, raw)

    def disconnect_broker(self) -> None:
        """Simulate broker disconnection for resilience testing."""
        self.connected = False

    def reconnect_broker(self) -> None:
        """Simulate broker reconnection and flush buffered messages (oldest first)."""
        self._flush_then_mark_connected(self.broker.publish)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for pattern, handler in self._subscriptions:
            self._register(pattern, handler)

    def stop(self) -> None:
        self._running = False


class PahoMQTTClient(_OfflineBuffer):
    """Client wrapping paho-mqtt for connection to real local Mosquitto."""

    def __init__(self, host: str = "localhost", port: int = 1883):
        import paho.mqtt.client as paho_mqtt

        self.host = host
        self.port = port
        if hasattr(paho_mqtt, "CallbackAPIVersion"):
            self._client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
        else:
            self._client = paho_mqtt.Client()

        self._handlers: list[tuple[str, Callable[[str, dict], None]]] = []
        self._handlers_lock = threading.Lock()
        self._init_buffer()
        self._stopping = False
        self._reconnect_thread: threading.Thread | None = None

        self._client.on_message = self._on_message
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self.connected = False

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        is_ok = (rc == 0) if isinstance(rc, int) else (not getattr(rc, "is_failure", True))
        if is_ok:
            logger.info("Connected to MQTT broker at %s:%s", self.host, self.port)
            with self._handlers_lock:
                for pattern, _ in self._handlers:
                    try:
                        self._client.subscribe(pattern, qos=1)
                    except Exception as e:
                        logger.warning("Failed subscribing to %s: %s", pattern, e)

            # Flush the messages buffered while disconnected, oldest first, before new publishes go out directly.
            self._flush_then_mark_connected(lambda topic, raw: self._client.publish(topic, raw, qos=1))

    def _on_disconnect(self, client, userdata, rc, properties=None) -> None:
        self.connected = False
        if not self._stopping:
            logger.warning("Disconnected from MQTT broker (%s:%s); auto-reconnect active", self.host, self.port)

    def _on_message(self, client, userdata, msg) -> None:
        topic = msg.topic
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            logger.warning("Paho MQTT payload parse error on %s: %s", topic, e)
            return

        with self._handlers_lock:
            handlers = list(self._handlers)

        for pattern, handler in handlers:
            if topic_matches(pattern, topic):
                try:
                    handler(topic, data)
                except Exception as ex:
                    logger.warning("Handler error on %s: %s", topic, ex)

    def subscribe(self, pattern: str, handler: Callable[[str, dict], None]) -> None:
        with self._handlers_lock:
            self._handlers.append((pattern, handler))
        if self.connected:
            try:
                self._client.subscribe(pattern, qos=1)
            except Exception as e:
                logger.warning("Failed subscribing to %s: %s", pattern, e)

    def publish(self, topic: str, payload: dict | str | bytes) -> None:
        if isinstance(payload, dict):
            raw = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, str):
            raw = payload.encode("utf-8")
        else:
            raw = payload

        if self._buffer_if_offline(topic, raw):
            return

        try:
            self._client.publish(topic, raw, qos=1)
        except Exception as exc:
            logger.warning("Failed to publish to MQTT topic %s: %s; buffering", topic, exc)
            self._buffer_if_offline(topic, raw, force=True)

    def start(self) -> None:
        self._stopping = False
        try:
            self._client.connect_async(self.host, self.port, 60)
            self._client.loop_start()
            logger.info("Paho MQTT background loop started for %s:%s", self.host, self.port)
        except Exception as exc:
            self.connected = False
            logger.warning(
                "Initial connection to MQTT broker at %s:%s failed (%s); starting background reconnect",
                self.host, self.port, exc
            )
            self._start_reconnect_loop()

    def _start_reconnect_loop(self) -> None:
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        def _loop():
            import time
            delay = 1.0
            while not self._stopping and not self.connected:
                time.sleep(delay)
                try:
                    self._client.connect(self.host, self.port, 60)
                    self._client.loop_start()
                    break  # _on_connect flushes the buffer and then sets connected
                except Exception:
                    delay = min(10.0, delay * 1.5)
        self._reconnect_thread = threading.Thread(target=_loop, daemon=True, name="MQTT-Reconnect")
        self._reconnect_thread.start()

    def stop(self) -> None:
        self._stopping = True
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass


class MQTTTransport:
    """Unified MQTT transport providing pub/sub across the five canonical topics."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 1883,
        force_standin: bool = False,
        broker: InMemoryBroker | None = None,
    ):
        self.host = host
        self.port = port
        self.is_standin = force_standin
        self.client: StandinMQTTClient | PahoMQTTClient

        if not force_standin:
            try:
                self.client = PahoMQTTClient(host=host, port=port)
            except Exception as e:
                # A broker was asked for (the stand-in was not forced), so falling back is a misconfiguration:
                # nothing published from here reaches the broker or any other process.
                logger.warning("MQTT broker %s:%s requested but paho-mqtt is unavailable or failed to initialize (%s); "
                               "using the in-process stand-in broker, so no message leaves this process", host, port, e)
                self.is_standin = True
                self.client = StandinMQTTClient(broker=broker)
        else:
            self.client = StandinMQTTClient(broker=broker)

    def subscribe(self, pattern: str, handler: Callable[[str, dict], None]) -> None:
        self.client.subscribe(pattern, handler)

    def publish(self, topic: str, payload: dict | str | bytes) -> None:
        self.client.publish(topic, payload)

    def start(self) -> None:
        self.client.start()

    @property
    def is_connected(self) -> bool:
        return getattr(self.client, "connected", False)

    def stop(self) -> None:
        self.client.stop()


def is_mqtt_enabled() -> bool:
    """Returns True if NIMBUS_TRANSPORT is explicitly set to 'mqtt'."""
    return os.environ.get("NIMBUS_TRANSPORT", "http").lower() == "mqtt"


def make_mqtt_transport_from_env(broker: InMemoryBroker | None = None) -> MQTTTransport:
    """Create transport using environment configuration."""
    host = os.environ.get("NIMBUS_MQTT_HOST", "localhost")
    port = int(os.environ.get("NIMBUS_MQTT_PORT", "1883"))
    force_standin = os.environ.get("NIMBUS_MQTT_STANDIN", "0").lower() in ("1", "true", "yes")
    return MQTTTransport(host=host, port=port, force_standin=force_standin, broker=broker)
