"""Resolve a proxy URL without guessing on every request.

The old implementation probed a list of public country endpoints on every
download, even when no proxy was configured. That made a wallpaper rotation
hang for seconds, leaked traffic, and defeated tests that mocked
``urllib.request.build_opener``. It also hard-coded the author's checkout path.

Policy now:

* an explicit ``settings.proxy`` (or ``MUZWALL_PROXY``) is used as-is;
* ``settings.proxy: "none"`` means direct;
* with no configured proxy the answer is "direct" and no network is touched;
* ``settings.proxy_autodetect`` opts into scanning local proxy ports;
* ``settings.proxy_probe`` opts into verifying candidates over the network.

The result is memoised briefly so one rotation does not repeat the work for the
API call and every image download.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import urllib.request

_UA = {"User-Agent": "Mozilla/5.0"}

_PROBE_URLS = [
    "https://ipinfo.io/country",
    "https://freeipapi.com/api/json",
    "https://ip-api.com/json/?fields=countryCode",
    "https://api.country.is/",
    "https://api.bigdatacloud.net/data/reverse-geocode-client",
    "https://ipwho.is/",
    "https://ifconfig.io/country",
]

_CANDIDATE_DEFAULTS = (
    "http://127.0.0.1:1080",
    "http://127.0.0.1:2080",
    "http://127.0.0.1:7890",
)

_PROXY_PROCESSES = re.compile(
    r"nekobox|windscribe|clash|mihomo|v2ray|xray|sing|hiddify|nekoray|"
    r"qv2ray|trojan|hysteria|tuic|gost|brook|openvpn|proton|warp",
    re.IGNORECASE,
)

_CACHE_TTL = 30.0
_cache_key: tuple[str, bool, bool] | None = None
_cache_value = ""
_cache_at = 0.0


def _settings() -> dict:
    try:
        from core.config import ConfigManager

        config = ConfigManager.load() or {}
        settings = config.get("settings", {}) or {}
        return settings if isinstance(settings, dict) else {}
    except Exception:
        return {}


def _config_value(settings: dict) -> str:
    explicit = os.environ.get("MUZWALL_PROXY")
    if explicit is not None:
        return explicit.strip()
    return str(settings.get("proxy", "") or "").strip()


def _alive(proxy_url: str) -> bool:
    try:
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(handler)
        for probe in _PROBE_URLS:
            try:
                request = urllib.request.Request(probe, headers=_UA)
                with opener.open(request, timeout=3) as response:
                    if response.status < 400:
                        return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def _listening_proxy_ports() -> list[int]:
    if shutil.which("ss") is None:
        return []
    ports: list[int] = []
    try:
        out = subprocess.run(
            ["ss", "-lntup"], capture_output=True, text=True, timeout=4
        ).stdout
        for line in out.splitlines():
            if not _PROXY_PROCESSES.search(line):
                continue
            match = re.search(
                r"127\.0\.0\.1:(\d+)|0\.0\.0\.0:(\d+)|\[::1\]:(\d+)|\[::\]:(\d+)",
                line,
            )
            if match:
                port = next(int(group) for group in match.groups() if group)
                if port not in ports:
                    ports.append(port)
    except Exception:
        pass
    return ports


def resolve_proxy_url(*, force: bool = False) -> str:
    """Return a proxy URL, or ``""`` for a direct connection."""
    global _cache_key, _cache_value, _cache_at

    settings = _settings()
    configured = _config_value(settings)
    autodetect = bool(settings.get("proxy_autodetect", False))
    probe = bool(settings.get("proxy_probe", False))
    key = (configured, autodetect, probe)

    now = time.monotonic()
    if not force and key == _cache_key and (now - _cache_at) < _CACHE_TTL:
        return _cache_value

    if configured.lower() == "none":
        answer = ""
    elif configured:
        answer = configured if (not probe or _alive(configured)) else ""
    elif not autodetect:
        # No proxy configured: prefer direct access. TUN-style VPNs already
        # route the traffic, and probing random ports is both slow and wrong.
        answer = ""
    else:
        candidates: list[str] = []
        for port in _listening_proxy_ports():
            candidates.append(f"http://127.0.0.1:{port}")
            candidates.append(f"socks5h://127.0.0.1:{port}")
        candidates.extend(_CANDIDATE_DEFAULTS)

        if probe:
            answer = next((item for item in candidates if _alive(item)), "")
        else:
            answer = candidates[0] if candidates else ""

    _cache_key = key
    _cache_value = answer
    _cache_at = now
    return answer
