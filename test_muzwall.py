#!/usr/bin/env python3
import unittest
import os
import json
import sys
import tempfile
from unittest.mock import patch, mock_open, MagicMock

# Import the modules we want to test
from core.config import ConfigManager, CONFIG_PATH
from core.setter import KDEWallpaperSetter, _session_env, _set_wallpaper_noctalia
from plugins.local_folder import LocalFolderSource
from plugins.wallhaven import WallhavenSource
import cli

class TestConfigManager(unittest.TestCase):

    @patch("os.path.exists")
    def test_load_not_found(self, mock_exists):
        mock_exists.return_value = False
        config = ConfigManager.load()
        self.assertEqual(config, {})

    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data='{"settings": {"interval_seconds": 60}}')
    def test_load_success(self, mock_file, mock_exists):
        mock_exists.return_value = True
        config = ConfigManager.load()
        self.assertIn("settings", config)
        self.assertEqual(config["settings"]["interval_seconds"], 60)

    def test_save_round_trips(self):
        """Save to a real temp path: save() writes a .tmp then os.replace's it,
        and mocking open() made the rename fail against a nonexistent file."""
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "config.json")
            with patch("core.config.CONFIG_PATH", target):
                self.assertTrue(ConfigManager.save({"settings": {"interval_seconds": 60}}))
                self.assertEqual(ConfigManager.load()["settings"]["interval_seconds"], 60)
            self.assertFalse(os.path.exists(target + ".tmp"), "temp file left behind")

    def test_save_reports_failure_instead_of_raising(self):
        with patch("core.config.CONFIG_PATH", "/proc/muzwall-nope/config.json"):
            self.assertFalse(ConfigManager.save({"a": 1}))

class TestWallpaperSetter(unittest.TestCase):

    def test_hex_to_rgb(self):
        self.assertEqual(KDEWallpaperSetter.hex_to_rgb("#000000"), "0,0,0")
        self.assertEqual(KDEWallpaperSetter.hex_to_rgb("#FFFFFF"), "255,255,255")

    @patch("core.setter._running_under_kde", return_value=False)
    @patch("core.setter._set_wallpaper_noctalia", return_value=True)
    @patch("os.path.exists", return_value=True)
    def test_set_wallpaper_uses_noctalia_on_niri(self, _exists, _noctalia, _kde):
        result = KDEWallpaperSetter.set_wallpaper("/fake/path.jpg", mode="fit")
        self.assertTrue(result)
        _noctalia.assert_called_once()

    def test_set_wallpaper_rejects_missing_files(self):
        self.assertFalse(KDEWallpaperSetter.set_wallpaper("/nope/missing.jpg"))

    @patch("core.setter._running_under_kde", return_value=False)
    @patch("shutil.which", return_value=None)
    def test_set_wallpaper_fails_without_a_compositor_bridge(self, _which, _kde):
        """Neither Plasma nor Noctalia available must fail loudly, not silently."""
        self.assertFalse(KDEWallpaperSetter.set_wallpaper("/fake/path.jpg", mode="fit"))

    @patch("core.setter._running_under_kde", return_value=False)
    @patch("os.path.exists")
    @patch("subprocess.run")
    def test_get_current_wallpaper_from_noctalia(self, mock_subprocess, mock_exists, _kde):
        mock_exists.return_value = True
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="/home/user/pic.png\n", stderr=""
        )
        state = KDEWallpaperSetter.get_current_wallpaper()
        self.assertEqual(state.get("image"), "/home/user/pic.png")

    @patch("core.setter._running_under_kde", return_value=False)
    @patch("os.path.exists")
    @patch("subprocess.run")
    def test_get_current_wallpaper_empty_when_bridge_is_silent(self, mock_subprocess, mock_exists, _kde):
        """A bridge that answers with garbage must not be trusted as a path."""
        mock_exists.return_value = True
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="error: not running\n", stderr=""
        )
        self.assertEqual(KDEWallpaperSetter.get_current_wallpaper(), {})


class TestSessionEnv(unittest.TestCase):
    """The daemon's environment bug: systemd gives it no WAYLAND_DISPLAY."""

    def test_recovers_wayland_display_from_systemd(self):
        stdout = "XDG_RUNTIME_DIR=/run/user/1000\nWAYLAND_DISPLAY=wayland-1\nPATH=/usr/bin\n"
        with patch.dict(os.environ, {}, clear=True), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=stdout)):
            env = _session_env()
        self.assertEqual(env.get("WAYLAND_DISPLAY"), "wayland-1")
        self.assertEqual(env.get("XDG_RUNTIME_DIR"), "/run/user/1000")

    def test_never_overwrites_a_value_we_already_have(self):
        """An inherited value wins; a real session must not be second-guessed."""
        stdout = "WAYLAND_DISPLAY=wayland-9\n"
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}, clear=True), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=stdout)):
            env = _session_env()
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-1")

    def test_survives_systemctl_failure(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("subprocess.run", side_effect=FileNotFoundError("systemctl")):
            self.assertIsInstance(_session_env(), dict)

    def test_noctalia_call_is_given_the_recovered_env(self):
        """Regression guard: the fix is only real if env= is actually passed."""
        captured = {}

        def fake_run(cmd, **kwargs):
            if "show-environment" in cmd:
                return MagicMock(returncode=0, stdout="WAYLAND_DISPLAY=wayland-1\n")
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            return MagicMock(returncode=0, stdout="ok\n", stderr="")

        with patch.dict(os.environ, {}, clear=True), \
             patch("shutil.which", return_value="/usr/bin/noctalia"), \
             patch("subprocess.run", side_effect=fake_run):
            self.assertTrue(_set_wallpaper_noctalia(["/tmp/pic.jpg"]))

        self.assertEqual(captured["cmd"][:3], ["/usr/bin/noctalia", "msg", "wallpaper-set"])
        self.assertEqual(captured["env"].get("WAYLAND_DISPLAY"), "wayland-1")

    def test_noctalia_rejection_is_reported(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("shutil.which", return_value="/usr/bin/noctalia"), \
             patch("subprocess.run", return_value=MagicMock(
                 returncode=0, stdout="error: noctalia is not running\n", stderr="")):
            self.assertFalse(_set_wallpaper_noctalia(["/tmp/pic.jpg"]))

class TestLocalFolderSource(unittest.TestCase):

    def test_fetch_next_sequential(self):
        """A real directory, because the scanner uses os.scandir, not os.listdir.

        Mocking os.listdir used to pass while the real code path went through
        os.scandir and hit a nonexistent /fake/folder.
        """
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            names = []
            for name in ("a.jpg", "b.png"):
                path = os.path.join(directory, name)
                # Real pixels: the plugin opens and verifies each candidate, so
                # a stub file header would be rejected as corrupted.
                Image.new("RGB", (8, 8), (20, 30, 40)).save(path)
                names.append(path)

            source = LocalFolderSource(directory, order="sequential", persist_history=False)
            self.assertEqual(source.fetch_next(), names[0])
            self.assertEqual(source.fetch_next(), names[1])
            self.assertEqual(source.fetch_next(), names[0], "should wrap around")
            self.assertEqual(source.fetch_prev(), names[1], "prev must walk backwards")

    def test_missing_folder_yields_nothing(self):
        source = LocalFolderSource("/nonexistent-muzwall-folder", order="sequential", persist_history=False)
        self.assertIsNone(source.fetch_next())

class TestWallhavenSource(unittest.TestCase):

    def test_init_defaults(self):
        source = WallhavenSource()
        self.assertEqual(source.max_size_bytes, 20.0 * 1024 * 1024)

    def test_fetch_api_batch_filtering(self):
        """Two things this test got wrong, both of which made it assert nothing.

        The plugin builds an opener (to honour the proxy setting) and calls
        opener.open(), so patching urllib.request.urlopen never intercepted
        anything -- the request escaped to the network. It also reads the real
        config.json for the proxy, so on a machine with a proxy configured the
        "mocked" call died with Connection refused.
        """
        mock_response = MagicMock()
        fake_json = json.dumps({
            "data": [
                {"path": "https://fake/1.jpg", "file_size": 5 * 1024 * 1024},
                {"path": "https://fake/2.jpg", "file_size": 25 * 1024 * 1024},
            ]
        })
        mock_response.read.return_value = fake_json.encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        opener = MagicMock()
        opener.open.return_value = mock_response

        # sorting="toplist" exercises the pagination advance.
        with patch("urllib.request.build_opener", return_value=opener), \
             patch("core.config.ConfigManager.load", return_value={"settings": {}}):
            source = WallhavenSource(max_size_mb=20.0, sorting="toplist")
            source._fetch_api_batch()

        opener.open.assert_called_once()
        self.assertEqual(source.image_queue, ["https://fake/1.jpg"])
        self.assertEqual(source.current_page, 2)

    def test_fetch_api_batch_survives_network_failure(self):
        """A dead proxy must not raise out of the batch fetch."""
        with patch("urllib.request.build_opener", side_effect=OSError("no proxy")), \
             patch("core.config.ConfigManager.load", return_value={"settings": {}}), \
             patch("time.sleep"):
            source = WallhavenSource(max_size_mb=20.0)
            source._fetch_api_batch()
        self.assertEqual(source.image_queue, [])

class TestCLICommands(unittest.TestCase):

    @patch("subprocess.run")
    def test_send_signal(self, mock_subprocess):
        cli.send_signal("SIGUSR1")
        mock_subprocess.assert_called_with(
            ["systemctl", "--user", "kill", "-s", "SIGUSR1", "muzwall.service"], 
            check=True, capture_output=True, text=True
        )

    @patch("os.path.exists")
    @patch("os.remove")
    @patch("builtins.open", new_callable=mock_open)
    def test_toggle_pause(self, mock_file, mock_remove, mock_exists):
        # Test Pause
        cli.toggle_pause(True)
        mock_file.assert_called_once()
        
        # Test Resume
        mock_exists.return_value = True
        cli.toggle_pause(False)
        mock_remove.assert_called_once()
    @patch("cli.ConfigManager.load")
    @patch("cli.ConfigManager.save")
    def test_handle_config_wallhaven(self, mock_save, mock_load):
        # handle_config() bails out early on an empty config, so hand it a
        # realistic one. This test used to pass {} here and failed on the
        # assert_called_once below rather than on anything it meant to check.
        mock_load.return_value = {"settings": {}, "plugins": {}}
        # Drive the real argument parser instead of hand-listing every attribute.
        # Hand-lists rot the moment a flag is added, and the failure surfaces
        # as an AttributeError on some unrelated flag.
        with patch.object(sys, "argv", [
            "muzwall", "config", "--wh-query", "cyberpunk", "--wh-maxsize", "30.0",
        ]):
            cli.main()

        mock_save.assert_called_once()
        saved_config = mock_save.call_args[0][0]
        
        self.assertEqual(saved_config["plugins"]["wallhaven"]["query"], "cyberpunk")
        self.assertEqual(saved_config["plugins"]["wallhaven"]["max_size_mb"], 30.0)

if __name__ == "__main__":
    unittest.main()