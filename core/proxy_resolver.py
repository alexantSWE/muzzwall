"""Resolve a working local VPN/proxy URL at runtime.

The static `settings.proxy` in config.json rots every time nekobox/windscribe
changes port (or when the tunnel is up, direct access already works). This
module probes live candidates instead of trusting the config value.

Order: explicit config value (if alive) -> local ports listening on
nekobox/windscribe/clash/xray/sing-box processes -> common defaults ->
"" (direct, i.e. TUN routing does the job).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request

_CONFIG = os.path.expanduser("~/Documents/proj/muzwall/config.json")
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


def _alive(proxy_url: str) -> bool:
    try:
        scheme = "socks5h://" if proxy_url.startswith("socks") else None
        url = proxy_url
        if scheme:
            url = proxy_url
        handler = urllib.request.ProxyHandler({"http": url, "https": url})
        opener = urllib.request.build_opener(handler)
        for probe in _PROBE_URLS:
            try:
                req = urllib.request.Request(probe, headers=_UA)
                with opener.open(req, timeout=5) as r:
                    if r.status < 400:
                        return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def _config_value() -> str:
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            return (json.load(f).get("settings", {}).get("proxy", "") or "").strip()
    except Exception:
        return ""


def _listening_proxy_ports() -> list[int]:
    ports = []
    try:
        out = subprocess.run(
            ["ss", "-lntup"], capture_output=True, text=True, timeout=4
        ).stdout
        for line in out.splitlines():
            if not re.search(
                r"nekobox|windscribe|clash|mihomo|v2ray|xray|sing|hiddify|nekoray|"
                r"qv2ray|trojan|hysteria|tuic|gost|brook|openvpn|proton|warp",
                line,
                re.IGNORECASE,
            ):
                continue
            m = re.search(r"127\.0\.0\.1:(\d+)|0\.0\.0\.0:(\d+)|\[::1\]:(\d+)|\[::\]:(\d+)", line)
            if m:
                p = next(int(g) for g in m.groups() if g)
                if p not in ports:
                    ports.append(p)
    except Exception:
        pass
    return ports


def resolve_proxy_url() -> str:
    cfg = _config_value()
    if cfg and cfg.lower() == "none":
        return ""

    candidates = []
    if cfg:
        candidates.append(cfg)
    for port in _listening_proxy_ports():
        candidates.append(f"http://127.0.0.1:{port}")
        candidates.append(f"socks5h://127.0.0.1:{port}")
    for default in ("http://127.0.0.1:1080", "http://127.0.0.1:2080", "http://127.0.0.1:7890"):
        candidates.append(default)

    for cand in candidates:
        if _alive(cand):
            return cand
    # Nothing alive: direct access (TUN/routing should handle it).
    return ""
