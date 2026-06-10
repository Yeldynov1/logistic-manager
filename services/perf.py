"""Замір часу операцій і мережевої затримки (діагностика для admin)."""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

_MAX_ENTRIES = 100

_PING_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("Nova Poshta API", "POST", "https://api.novaposhta.ua/v2.0/json/"),
    ("Укрпошта", "GET", "https://www.ukrposhta.ua/"),
    ("Rozetka API", "GET", "https://api-seller.rozetka.com.ua/"),
    ("Prom.ua API", "GET", "https://my.prom.ua/"),
    ("Епіцентр API", "GET", "https://merchant-api.epicentrm.com.ua/"),
)


def _log() -> list[dict[str, Any]]:
    import streamlit as st

    items = st.session_state.get("perf_log")
    if not isinstance(items, list):
        items = []
        st.session_state.perf_log = items
    return items


def clear() -> None:
    _log().clear()
    import streamlit as st

    st.session_state.pop("perf_ping_results", None)


def host_from_url(url: str) -> str:
    try:
        host = urlparse(str(url or "")).netloc
        return host or str(url)[:48]
    except Exception:
        return str(url)[:48]


def record(label: str, ms: float, **meta: Any) -> None:
    entry: dict[str, Any] = {
        "label": str(label or "—")[:140],
        "ms": round(float(ms), 1),
        "ts": time.time(),
    }
    for key, val in meta.items():
        if val is None:
            continue
        entry[key] = val
    items = _log()
    items.insert(0, entry)
    del items[_MAX_ENTRIES:]


@contextmanager
def timed(label: str, **meta: Any) -> Iterator[None]:
    t0 = time.perf_counter()
    err = ""
    try:
        yield
    except Exception as exc:
        err = str(exc)[:200]
        raise
    finally:
        record(label, (time.perf_counter() - t0) * 1000, ok=not err, error=err or None, **meta)


def entries(limit: int = 40) -> list[dict[str, Any]]:
    items = _log()
    try:
        n = max(1, min(int(limit), _MAX_ENTRIES))
    except (TypeError, ValueError):
        n = 40
    return list(items[:n])


def summary_by_prefix(prefix: str = "HTTP ") -> list[tuple[str, float, int]]:
    """Сума мс і кількість викликів за останніми записами (група за label)."""
    totals: dict[str, list[float]] = {}
    for row in _log():
        label = str(row.get("label") or "")
        if prefix and not label.startswith(prefix):
            continue
        totals.setdefault(label, []).append(float(row.get("ms") or 0))
    ranked = [
        (label, round(sum(vals), 1), len(vals))
        for label, vals in totals.items()
    ]
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:20]


def run_network_ping() -> list[dict[str, Any]]:
    """Затримка до ключових API (не тест швидкості каналу, а час відгуку)."""
    import utils

    results: list[dict[str, Any]] = []
    for name, method, url in _PING_TARGETS:
        t0 = time.perf_counter()
        status = 0
        err = ""
        try:
            if method.upper() == "POST":
                resp = utils.make_request(
                    "POST",
                    url,
                    json={"apiKey": "ping", "modelName": "Common", "calledMethod": "getServiceTypes"},
                    timeout=12,
                    _perf_skip=True,
                )
            else:
                resp = utils.make_request("GET", url, timeout=12, _perf_skip=True)
            if resp is None:
                err = utils.get_last_request_error() or "немає відповіді"
            else:
                status = int(getattr(resp, "status_code", 0) or 0)
        except Exception as exc:
            err = str(exc)[:160]
        ms = round((time.perf_counter() - t0) * 1000, 1)
        row = {"name": name, "host": host_from_url(url), "ms": ms, "status": status, "error": err}
        results.append(row)
        record(f"ping:{name}", ms, status=status, error=err or None)
    import streamlit as st

    st.session_state.perf_ping_results = results
    return results
