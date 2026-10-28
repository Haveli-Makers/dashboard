import re
import time

import streamlit as st

from frontend.st_utils import get_server_cache_key

FALLBACK_CONNECTORS = ["binance_perpetual", "binance", "gate_io", "gate_io_perpetual", "kucoin", "kucoin_perpetual", "okx"]
FALLBACK_INTERVALS = ["1m", "3m", "5m", "15m", "1h", "4h", "1d", "1s"]
UNAVAILABLE_CONNECTORS = {"ascend_ex"}

# Suffixes of connectors that trade against a live exchange's market but have no candle feed of their own
NO_FEED_SUFFIXES = ("_paper_trade", "_testnet")

PAIR_FORMAT = re.compile(r"^[A-Z0-9]+-[A-Z0-9]+$")
INTERVAL_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "M": 2592000}
INTERVAL_PATTERN = re.compile(r"^(\d+)([smhdwM])$")


def is_valid_pair(pair):
    """Hummingbot candle feeds split pairs on '-', so only BASE-QUOTE is accepted."""
    return bool(PAIR_FORMAT.match(pair))


UNKNOWN_PAIR_ERRORS = ("invalid pair", "invalid symbol", "invalid trading pair", "-1121", "not found",
                       "unknown symbol", "unknown pair", "bad symbol", "market not found")


def candles_error(trading_pair, connector, raw_error):
    """Translate raw exchange/API errors from a candles request into a message a user can act on."""
    return market_data_error(trading_pair, connector, raw_error, data="candles")


def market_data_error(trading_pair, connector, raw_error, data="market data"):
    """Translate raw exchange/API errors into a message a user can act on. `data` names what was being
    fetched, e.g. "candles" or "the order book"."""
    error = str(raw_error).lower()
    if "not enough values to unpack" in error or "invalid pair format" in error:
        return f"{trading_pair} is not in BASE-QUOTE format. Enter it like USDT-INR or BTC-USDT."
    if any(marker in error for marker in UNKNOWN_PAIR_ERRORS):
        return f"{trading_pair} is not available on {connector}. Check the pair name or pick another exchange."
    if "no historical data" in error:
        return f"No {data} found for {trading_pair} in the selected date range."
    if "429" in error or "too many requests" in error or "rate limit" in error:
        return f"{connector} is rate limiting requests. Please wait a minute and try again."
    if "timeout" in error or "timed out" in error:
        return f"The request for {trading_pair} timed out. Try a shorter date range or try again later."
    if "connect" in error or "503" in error or "502" in error or "unavailable" in error:
        return f"Could not reach {connector} right now. Please try again later."
    return f"Could not fetch {data} for {trading_pair} on {connector}."


def interval_to_seconds(interval):
    """Convert an interval like '15m' or '4h' into seconds; None if unrecognised."""
    match = INTERVAL_PATTERN.match(str(interval))
    if not match:
        return None
    return int(match.group(1)) * INTERVAL_SECONDS[match.group(2)]


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_candle_connectors(_client, server):
    connectors = _client.market_data.get_available_candle_connectors()
    if not connectors:
        raise ValueError("No candle connectors returned")
    return sorted(connectors)


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_candle_intervals(_client, server, connector):
    intervals = [i for i in (_client.market_data.get_candle_intervals(connector) or []) if interval_to_seconds(i)]
    if not intervals:
        raise ValueError(f"No candle intervals returned for {connector}")
    return intervals


@st.cache_data(ttl=15, show_spinner=False)
def _fetch_candles(_client, server, connector, trading_pair, interval, start_time, end_time):
    candles = _client.market_data.get_historical_candles(
        connector_name=connector,
        trading_pair=trading_pair,
        interval=interval,
        start_time=start_time,
        end_time=end_time,
    )
    if isinstance(candles, dict):
        raise ValueError(candles.get("error", "Unexpected response from backend"))
    return candles or []


def clear_candles_cache():
    for cached_fetch in (_fetch_candle_connectors, _fetch_candle_intervals, _fetch_candles):
        cached_fetch.clear()


def get_candle_connectors(client):
    """Connectors with a candle feed on the active server, or FALLBACK_CONNECTORS if it can't be reached."""
    try:
        connectors = _fetch_candle_connectors(client, get_server_cache_key())
    except Exception:
        connectors = FALLBACK_CONNECTORS
    return [c for c in connectors if c not in UNAVAILABLE_CONNECTORS]


def get_candle_intervals(client, connector):
    try:
        return _fetch_candle_intervals(client, get_server_cache_key(), connector)
    except Exception:
        return FALLBACK_INTERVALS


def default_candle_source(connector, candle_connectors):
    """The connector itself if it has a feed, else its live counterpart (binance_paper_trade -> binance)."""
    if connector in candle_connectors:
        return connector
    for suffix in NO_FEED_SUFFIXES:
        if connector.endswith(suffix) and connector[:-len(suffix)] in candle_connectors:
            return connector[:-len(suffix)]
    return None


def fetch_candles(client, connector, trading_pair, interval, start_time, end_time):
    """Fetch candles for [start_time, end_time] (Unix seconds); returns (records, raw_error)."""
    try:
        return _fetch_candles(client, get_server_cache_key(), connector, trading_pair, interval,
                              int(start_time), int(end_time)), None
    except Exception as e:
        return [], str(e)


def fetch_recent_candles(client, connector, trading_pair, interval, count):
    """Fetch the last `count` candles; returns (records, raw_error)."""
    end_time = int(time.time()) // 60 * 60 + 60
    start_time = max(0, end_time - interval_to_seconds(interval) * count)
    candles, error = fetch_candles(client, connector, trading_pair, interval, start_time, end_time)
    return candles[-count:], error
