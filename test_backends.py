"""Tests for backend selection, failover and state persistence."""

import os
import tempfile
import unittest
from unittest.mock import patch

from core import state
from core.backends import BackendResult, CommandBackend, PlasmaBackend, WallpaperRequest
from core.backends.registry import (
    apply_wallpaper,
    backend_chain,
    normalize_preference,
)


def _request(command="", paths=("/tmp/a.png",)):
    return WallpaperRequest(paths=paths, modes=("fill",), command=command)


class TestRegistry(unittest.TestCase):
    def test_auto_order_is_protocol_based_not_desktop_based(self):
        with patch.object(CommandBackend, "available", return_value=True):
            with patch("core.backends.portal.PortalBackend.available", return_value=True), \
                 patch("core.backends.layer_shell.LayerShellBackend.available", return_value=True), \
                 patch("core.backends.x11.X11Backend.available", return_value=True), \
                 patch("core.backends.plasma.PlasmaBackend.available", return_value=False):
                names = [b.name for b in backend_chain(_request("echo {image}"))]
        self.assertEqual(names, ["portal", "layer-shell", "x11", "command"])

    def test_command_is_only_offered_when_configured(self):
        with patch("core.backends.portal.PortalBackend.available", return_value=True), \
             patch("core.backends.layer_shell.LayerShellBackend.available", return_value=False), \
             patch("core.backends.x11.X11Backend.available", return_value=False), \
             patch("core.backends.plasma.PlasmaBackend.available", return_value=False):
            names = [b.name for b in backend_chain(_request())]
        self.assertEqual(names, ["portal"])

    def test_preferred_backend_runs_first_but_keeps_fallbacks(self):
        with patch("core.backends.portal.PortalBackend.available", return_value=True), \
             patch("core.backends.layer_shell.LayerShellBackend.available", return_value=True), \
             patch("core.backends.x11.X11Backend.available", return_value=True), \
             patch("core.backends.plasma.PlasmaBackend.available", return_value=False):
            names = [b.name for b in backend_chain(_request(), preferred="x11")]
        self.assertEqual(names, ["x11", "portal", "layer-shell"])

    def test_plasma_is_first_choice_for_distinct_desktop_wallpapers(self):
        request = _request(paths=("/tmp/a.png", "/tmp/b.png"))
        with patch("core.backends.portal.PortalBackend.available", return_value=True), \
             patch("core.backends.layer_shell.LayerShellBackend.available", return_value=True), \
             patch("core.backends.x11.X11Backend.available", return_value=True), \
             patch("core.backends.plasma.PlasmaBackend.available", return_value=True):
            names = [backend.name for backend in backend_chain(request)]
        self.assertEqual(names[0], "plasma")

    def test_plasma_assigns_each_path_mode_and_color(self):
        request = WallpaperRequest(
            paths=("/tmp/a.png", "/tmp/b.png"),
            modes=("fill", "fit"),
            colors=("#000000", "#abcdef"),
        )
        completed = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch("core.backends.plasma._session_env", return_value={}), \
             patch("core.backends.plasma.shutil.which", side_effect=lambda name: "/usr/bin/qdbus6" if name == "qdbus6" else None), \
             patch("core.backends.plasma.subprocess.run", return_value=completed) as run:
            outcome = PlasmaBackend.apply(request)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.applied, request.paths)
        script = run.call_args.args[0][-1]
        self.assertIn('"/tmp/a.png", "/tmp/b.png"', script)
        self.assertIn("modes = [0, 1]", script)
        self.assertIn('"#000000", "#abcdef"', script)

    def test_aliases_normalise(self):
        self.assertEqual(normalize_preference("swww"), "layer-shell")
        self.assertEqual(normalize_preference("XDG-Portal"), "portal")
        self.assertEqual(normalize_preference(None), "")

    def test_apply_falls_through_a_failing_backend(self):
        request = _request()
        with patch("core.backends.portal.PortalBackend.available", return_value=True), \
             patch("core.backends.portal.PortalBackend.apply", return_value=BackendResult(False, "portal", message="denied")) as first, \
             patch("core.backends.layer_shell.LayerShellBackend.available", return_value=True), \
             patch("core.backends.layer_shell.LayerShellBackend.apply", return_value=BackendResult(True, "layer-shell", applied=request.paths)) as second, \
             patch("core.backends.x11.X11Backend.available", return_value=False), \
             patch("core.backends.plasma.PlasmaBackend.available", return_value=False):
            outcome = apply_wallpaper(request)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.backend, "layer-shell")
        first.assert_called_once()
        second.assert_called_once()

    def test_apply_reports_every_failure_when_nothing_works(self):
        request = _request()
        with patch("core.backends.portal.PortalBackend.available", return_value=True), \
             patch("core.backends.portal.PortalBackend.apply", side_effect=RuntimeError("bus is gone")), \
             patch("core.backends.layer_shell.LayerShellBackend.available", return_value=False), \
             patch("core.backends.x11.X11Backend.available", return_value=False), \
             patch("core.backends.plasma.PlasmaBackend.available", return_value=False):
            outcome = apply_wallpaper(request)
        self.assertFalse(outcome.ok)
        self.assertIn("bus is gone", outcome.message)

    def test_no_backend_is_a_clear_failure(self):
        request = _request()
        with patch("core.backends.portal.PortalBackend.available", return_value=False), \
             patch("core.backends.layer_shell.LayerShellBackend.available", return_value=False), \
             patch("core.backends.x11.X11Backend.available", return_value=False), \
             patch("core.backends.plasma.PlasmaBackend.available", return_value=False):
            outcome = apply_wallpaper(request)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.backend, "none")
        self.assertIn("wallpaper_command", outcome.message)


class TestCommandBackend(unittest.TestCase):
    def test_images_token_expands_to_all_paths(self):
        request = WallpaperRequest(
            paths=("/tmp/a.png", "/tmp/b.png"),
            command="setter --bg {images}",
        )
        with patch.object(CommandBackend, "_run", return_value=(True, "")) as run:
            outcome = CommandBackend.apply(request)
        self.assertTrue(outcome.ok)
        run.assert_called_once()
        argv = run.call_args.args[0]
        self.assertEqual(argv, ["setter", "--bg", "/tmp/a.png", "/tmp/b.png"])

    def test_path_is_appended_when_no_placeholder(self):
        request = WallpaperRequest(paths=("/tmp/a.png",), command="/usr/bin/wallpaper")
        with patch.object(CommandBackend, "_run", return_value=(True, "")) as run:
            CommandBackend.apply(request)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/wallpaper", "/tmp/a.png"])

    def test_missing_command_is_reported(self):
        outcome = CommandBackend.apply(WallpaperRequest(paths=("/tmp/a.png",)))
        self.assertFalse(outcome.ok)
        self.assertIn("wallpaper_command", outcome.message)


class TestState(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._env = patch.dict(os.environ, {"XDG_STATE_HOME": self._dir.name})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_current_round_trip(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as image:
            self.assertTrue(
                state.write_current([image.name], mode="smart", color="#abcdef", backend="portal")
            )
            current = state.read_current()
        self.assertEqual(current["image"], image.name)
        self.assertEqual(current["mode"], "smart")
        self.assertEqual(current["backend"], "portal")
        self.assertEqual(current["color"], "#abcdef")

    def test_missing_files_are_not_a_current_wallpaper(self):
        state.write_current(["/definitely/gone.png"])
        self.assertEqual(state.read_current(), {})

    def test_pause_flag_round_trip(self):
        self.assertFalse(state.is_paused())
        state.set_paused(True)
        self.assertTrue(state.is_paused())
        state.set_paused(False)
        self.assertFalse(state.is_paused())


if __name__ == "__main__":
    unittest.main()
