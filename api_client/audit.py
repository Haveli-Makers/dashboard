import threading
from contextlib import contextmanager

AUDIT_LOG_HEADER = "X-Audit-Log"

_state = threading.local()


def _current():
    """Returns True (force on), False (force off), or None (backend default)."""
    return getattr(_state, "override", None)


def audit_headers() -> dict:
    """Headers to merge into a request; empty unless inside an ``audit_logged`` block."""
    override = _current()
    if override is True:
        return {AUDIT_LOG_HEADER: "1"}
    if override is False:
        return {AUDIT_LOG_HEADER: "0"}
    return {}


@contextmanager
def audit_logged(enabled: bool = True):
    """Force audit logging on (``enabled=True``) or off (``enabled=False``) for
    every API call made inside the block."""
    prev = _current()
    _state.override = enabled
    try:
        yield
    finally:
        _state.override = prev
