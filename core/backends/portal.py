"""Set wallpapers through the standard XDG Desktop Portal.

This is the desktop-environment-independent path. It is implemented by the
portal backends on GNOME, KDE Plasma 6.5+, Deepin, Phosh and Cinnamon. The
portal may ask for permission the first time; after that the same app id can
change the wallpaper without a dialog.

The portal is asynchronous: ``SetWallpaperFile`` returns a Request object and
the real result arrives later as a ``Response`` signal. We wait for that
signal with a bounded timeout so a missing permission dialog can never wedge
the daemon.
"""

from __future__ import annotations

import os
import time
import uuid

from .base import BackendResult, WallpaperBackend, WallpaperRequest, result


def _bus_address() -> str:
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if address:
        return address
    # The daemon is started by systemd and may not have inherited the session
    # bus address. Recover it the same way the rest of Muzwall recovers
    # DISPLAY/WAYLAND_DISPLAY.
    try:
        from core.setter import _session_env

        return _session_env().get("DBUS_SESSION_BUS_ADDRESS") or "SESSION"
    except Exception:
        return "SESSION"


class PortalBackend(WallpaperBackend):
    name = "portal"

    _available: bool | None = None
    _available_at = 0.0
    _AVAILABLE_TTL = 30.0

    @classmethod
    def available(cls) -> bool:
        now = time.monotonic()
        if (
            cls._available is not None
            and (now - cls._available_at) < cls._AVAILABLE_TTL
        ):
            return cls._available

        cls._available = cls._probe()
        cls._available_at = now
        return cls._available

    @classmethod
    def _probe(cls) -> bool:
        """Check for the interface without triggering a permission dialog."""
        try:
            from jeepney import DBusAddress, new_method_call
            from jeepney.io.blocking import open_dbus_connection
        except ImportError:
            return False

        properties = DBusAddress(
            "/org/freedesktop/portal/desktop",
            bus_name="org.freedesktop.portal.Desktop",
            interface="org.freedesktop.DBus.Properties",
        )
        try:
            with open_dbus_connection(bus=_bus_address(), auth_timeout=2.0) as conn:
                reply = conn.send_and_get_reply(
                    new_method_call(
                        properties,
                        "Get",
                        "ss",
                        ("org.freedesktop.portal.Wallpaper", "version"),
                    ),
                    timeout=2.0,
                )
                return bool(reply.body)
        except Exception:
            return False

    @classmethod
    def apply(cls, request: WallpaperRequest) -> BackendResult:
        if not request.path:
            return result(False, cls.name, message="no wallpaper path")
        if len(request.paths) > 1:
            return result(
                False,
                cls.name,
                message="the wallpaper portal accepts one image; use Plasma/X11 for per-display images",
            )

        try:
            from jeepney import DBusAddress, new_method_call
            from jeepney.bus_messages import MatchRule
            from jeepney.io.blocking import open_dbus_connection
            from jeepney.low_level import HeaderFields
        except ImportError:
            return result(
                False,
                cls.name,
                message="jeepney is not installed (pip install jeepney)",
            )

        address = DBusAddress(
            "/org/freedesktop/portal/desktop",
            bus_name="org.freedesktop.portal.Desktop",
            interface="org.freedesktop.portal.Wallpaper",
        )
        set_on = request.set_on if request.set_on in {"background", "lockscreen", "both"} else "background"
        applied: list[str] = []
        timeout = max(1.0, float(request.portal_timeout))
        path = request.path

        try:
            with open_dbus_connection(
                bus=_bus_address(), enable_fds=True, auth_timeout=5.0
            ) as conn:
                # Subscribe before sending: the portal is allowed to answer
                # immediately, and a fast response must not be lost.
                rule = MatchRule(
                    type="signal",
                    interface="org.freedesktop.portal.Request",
                    member="Response",
                    path_namespace="/org/freedesktop/portal/desktop/request/",
                )
                with conn.filter(rule, bufsize=8) as matches:
                    try:
                        fd = os.open(path, os.O_RDONLY)
                    except OSError as error:
                        return result(
                            False,
                            cls.name,
                            applied=applied,
                            message=f"cannot open {path}: {error}",
                        )

                    token = f"muzwall{os.getpid()}{uuid.uuid4().hex}"
                    try:
                        message = new_method_call(
                            address,
                            "SetWallpaperFile",
                            "sha{sv}",
                            (
                                "",
                                fd,
                                {
                                    "handle_token": ("s", token),
                                    "set-on": ("s", set_on),
                                    "show-preview": ("b", False),
                                },
                            ),
                        )
                        reply = conn.send_and_get_reply(message, timeout=5.0)
                        handle = str(reply.body[0])
                    except Exception as error:
                        return result(
                            False,
                            cls.name,
                            applied=applied,
                            message=f"portal request failed for {os.path.basename(path)}: {error}",
                        )
                    finally:
                        try:
                            os.close(fd)
                        except OSError:
                            pass

                    response = cls._wait_for_response(
                        conn,
                        matches,
                        handle,
                        HeaderFields.path,
                        timeout,
                    )
                    if response is None:
                        return result(
                            False,
                            cls.name,
                            applied=applied,
                            message=(
                                "portal did not answer the wallpaper request "
                                "(missing permission dialog, or no portal backend?)"
                            ),
                        )
                    code, _details = response
                    if code != 0:
                        reason = "cancelled" if code == 1 else f"portal error {code}"
                        return result(
                            False,
                            cls.name,
                            applied=applied,
                            message=reason,
                        )
                    applied.append(path)

            return result(True, cls.name, applied=applied)
        except Exception as error:
            return result(
                False,
                cls.name,
                applied=applied,
                message=f"portal unavailable: {error}",
            )

    @staticmethod
    def _wait_for_response(conn, matches, handle: str, path_field, timeout: float):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                message = conn.recv_until_filtered(matches, timeout=remaining)
            except TimeoutError:
                return None
            except Exception:
                return None

            message_path = str(message.header.fields.get(path_field, ""))
            if message_path != handle:
                continue
            body = message.body
            if len(body) != 2:
                return None
            return int(body[0]), body[1]
