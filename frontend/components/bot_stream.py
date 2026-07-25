"""Background MQTT-over-WebSocket subscriber for live bot/controller data.

Hummingbot instances publish per-controller updates to the broker (EMQX) on three topics:

    <prefix>/<bot_name>/controllers/<controller_id>/account_data
    <prefix>/<bot_name>/controllers/<controller_id>/market_data
    <prefix>/<bot_name>/controllers/<controller_id>/performance_data

This module maintains a single process-wide subscriber (paho's network loop runs on its own
daemon thread). Received payloads are cached in a module-level dict guarded by a lock. The
Streamlit render thread reads deep-copied snapshots via ``get_bot_data``.

IMPORTANT: the cache lives at module scope, NOT in ``st.session_state`` — paho's callbacks run on
a background thread that cannot touch Streamlit session state. The singleton survives Streamlit
reruns because the module stays imported, so reruns reuse the same socket rather than opening new
ones.
"""

import copy
import json
import threading
import time

import paho.mqtt.client as mqtt

from CONFIG import BROKER_HOST, BROKER_PASSWORD, BROKER_PORT, BROKER_TOPIC_PREFIX, BROKER_USERNAME, BROKER_WS_PATH

# Topic suffixes we understand.
DATA_KINDS = ("account_data", "market_data", "performance_data")

# Seconds after which a controller's last message is considered "stale".
STALE_AFTER_SECONDS = 8.0

_lock = threading.Lock()
_stream = None  # singleton BotDataStream


class BotDataStream:
    """Singleton MQTT subscriber caching the latest payload per (bot, controller, kind)."""

    def __init__(self):
        # data[bot_name][controller_id][kind] = {"payload": dict, "_ts": monotonic}
        self._data = {}
        self._data_lock = threading.Lock()
        self._connected = False
        self._last_error = None

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            transport="websockets",
        )
        self._client.ws_set_options(path=BROKER_WS_PATH)
        if BROKER_USERNAME:
            self._client.username_pw_set(BROKER_USERNAME, BROKER_PASSWORD)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._topic_filter = f"{BROKER_TOPIC_PREFIX}/#"

    def start(self):
        """Connect (async) and start the network loop on paho's daemon thread."""
        try:
            self._client.connect_async(BROKER_HOST, BROKER_PORT)
            self._client.loop_start()
        except Exception as e:  # pragma: no cover - defensive
            self._last_error = str(e)

    # -- paho callbacks (run on the network thread) --------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self._connected = True
            self._last_error = None
            client.subscribe(self._topic_filter)
        else:
            self._connected = False
            self._last_error = f"connect failed: {reason_code}"

    def _on_disconnect(self, client, userdata, *args):
        # paho auto-reconnects because loop_start() is running; just flip the flag.
        self._connected = False

    def _on_message(self, client, userdata, msg):
        topic_parts = msg.topic.split("/")
        # Expected: <prefix>/<bot>/controllers/<controller>/<kind>
        if len(topic_parts) != 5 or topic_parts[2] != "controllers":
            return
        _, bot_name, _, controller_id, kind = topic_parts
        if kind not in DATA_KINDS:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        with self._data_lock:
            self._data.setdefault(bot_name, {}).setdefault(controller_id, {})[kind] = {
                "payload": payload,
                "_ts": time.monotonic(),
            }

    # -- read API (called from the Streamlit render thread) -------------------------------

    def get_bot_data(self, bot_name):
        """Return a deep-copied snapshot for one bot.

        Shape: {controller_id: {kind: payload, "_ts": <newest message age source>}}
        Each controller dict also carries ``_age`` (seconds since its most recent message).
        Returns an empty dict if nothing has been received for the bot yet.
        """
        with self._data_lock:
            bot = copy.deepcopy(self._data.get(bot_name, {}))
        now = time.monotonic()
        result = {}
        for controller_id, kinds in bot.items():
            flat = {}
            newest_ts = None
            for kind, entry in kinds.items():
                flat[kind] = entry["payload"]
                ts = entry["_ts"]
                if newest_ts is None or ts > newest_ts:
                    newest_ts = ts
            flat["_age"] = (now - newest_ts) if newest_ts is not None else None
            result[controller_id] = flat
        return result

    def is_connected(self):
        return self._connected

    @property
    def last_error(self):
        return self._last_error


def get_stream() -> BotDataStream:
    """Return the process-wide subscriber, starting it on first use (idempotent)."""
    global _stream
    with _lock:
        if _stream is None:
            _stream = BotDataStream()
            _stream.start()
        return _stream
