#!/usr/bin/env python3
import unittest
import os
import json
import sys
import tempfile
import time
from unittest.mock import patch, mock_open, MagicMock

# Import the modules we want to test
from core.config import ConfigManager, CONFIG_PATH
from core.cache import CacheManager
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

    def setUp(self):
        # set_wallpaper() prunes its scratch dir in a finally block. Without this
        # the tests would reach into the real /dev/shm/muzwall and delete the
        # live session's blur frames -- which is exactly what happened the first
        # time this ran.
        self._ram = tempfile.TemporaryDirectory()
        self.addCleanup(self._ram.cleanup)
        p = patch.object(KDEWallpaperSetter, "get_ram_dir", return_value=self._ram.name)
        p.start()
        self.addCleanup(p.stop)

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

    def test_corrupt_candidates_are_skipped(self):
        """Validation has to reject junk, not just accept good input. Before the
        validator was shared, a truncated download would be handed straight to
        the decoder and crash the rotation."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            for name, ok in (("good.jpg", True), ("junk.jpg", False), ("later.png", True)):
                path = os.path.join(directory, name)
                if ok:
                    Image.new("RGB", (8, 8), (20, 30, 40)).save(path)
                else:
                    # Plausible size and extension, but not an image at all.
                    with open(path, "wb") as f:
                        f.write(b"<html><body>502 Bad Gateway</body></html>")

            source = LocalFolderSource(directory, order="sequential", persist_history=False)
            chosen = {source.fetch_next() for _ in range(4)}
            self.assertNotIn(os.path.join(directory, "junk.jpg"), chosen)

class TestBlurCachePruning(unittest.TestCase):

    """set_wallpaper() writes generated blur frames into /dev/shm and nothing
    ever deleted them. Because filenames derive from the wallpaper basename, a
    given wallpaper overwrote its own frame, which made the leak look bounded
    right up until the library outgrew the rotation window."""

    def _frame(self, directory, name, age_seconds=0):
        from PIL import Image
        path = os.path.join(directory, name)
        Image.new("RGB", (8, 8), (10, 20, 30)).save(path)
        mtime = time.time() - age_seconds
        os.utime(path, (mtime, mtime))
        return path

    def test_removes_stale_frames_but_keeps_the_live_one(self):
        with tempfile.TemporaryDirectory() as directory:
            live = self._frame(directory, "blur_0_live.jpg", age_seconds=7200)
            stale = self._frame(directory, "blur_0_stale.jpg", age_seconds=7200)
            fresh = self._frame(directory, "blur_1_fresh.jpg", age_seconds=5)

            with patch.object(KDEWallpaperSetter, "get_ram_dir", return_value=directory):
                removed = KDEWallpaperSetter._prune_blur_cache([live])

            self.assertEqual(removed, 1, "only the frame past the grace window goes")
            self.assertTrue(os.path.exists(live), "the frame just handed to the compositor stays")
            self.assertFalse(os.path.exists(stale))
            self.assertTrue(os.path.exists(fresh), "grace window still protecting it")

    def test_hard_cap_bounds_spamming_next(self):
        """The grace window alone only bounds growth by rotation *rate*. Ten
        `next` calls inside one window used to leave ten frames in RAM."""
        with tempfile.TemporaryDirectory() as directory:
            for i in range(10):
                self._frame(directory, f"blur_{i}_f{i}.jpg", age_seconds=1)

            with patch.object(KDEWallpaperSetter, "get_ram_dir", return_value=directory):
                removed = KDEWallpaperSetter._prune_blur_cache([])

            self.assertEqual(removed, 6)
            self.assertEqual(len(os.listdir(directory)), 4)
            newest = sorted(os.listdir(directory))
            self.assertEqual(newest, ["blur_6_f6.jpg", "blur_7_f7.jpg",
                                      "blur_8_f8.jpg", "blur_9_f9.jpg"],
                             "the newest frames survive, oldest are shed")

    def test_live_frames_are_never_shed_by_the_cap(self):
        """A multi-monitor setup keeps several frames referenced at once. The
        cap must never delete one the compositor is actively displaying."""
        with tempfile.TemporaryDirectory() as directory:
            frames = [self._frame(directory, f"blur_{i}_f{i}.jpg", age_seconds=1) for i in range(10)]
            live = frames[-3:]  # the three oldest of the set, deliberately

            with patch.object(KDEWallpaperSetter, "get_ram_dir", return_value=directory):
                KDEWallpaperSetter._prune_blur_cache(live, max_retained=4)

            # 10 frames, cap 4 -> oldest 6 are surplus; the 3 "live" frames are
            # the oldest of the remaining four and must survive anyway.
            self.assertEqual(sorted(os.listdir(directory)),
                             sorted([os.path.basename(f) for f in live] + ["blur_6_f6.jpg"]))

    def test_grace_window_protects_a_recent_frame(self):
        """The shell we handed the path to may still be reading it, so a frame
        inside the grace window must survive even when it is not in `keep`."""
        with tempfile.TemporaryDirectory() as directory:
            recent = self._frame(directory, "blur_0_recent.jpg", age_seconds=60)
            with patch.object(KDEWallpaperSetter, "get_ram_dir", return_value=directory):
                KDEWallpaperSetter._prune_blur_cache([])
            self.assertTrue(os.path.exists(recent))

    def test_only_touches_its_own_files(self):
        """The scratch dir is shared with the download cache on systems without
        /dev/shm, so pruning must never reach beyond the blur_ prefix."""
        with tempfile.TemporaryDirectory() as directory:
            bystander = os.path.join(directory, "wallhaven-abc123.jpg")
            with open(bystander, "wb") as f:
                f.write(b"not ours")
            os.utime(bystander, (time.time() - 99999, time.time() - 99999))

            with patch.object(KDEWallpaperSetter, "get_ram_dir", return_value=directory):
                KDEWallpaperSetter._prune_blur_cache([])

            self.assertTrue(os.path.exists(bystander), "pruning must not eat the download cache")

    def test_a_directory_named_like_a_frame_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            trap = os.path.join(directory, "blur_0_trap.jpg")
            os.makedirs(trap)
            os.utime(trap, (time.time() - 99999, time.time() - 99999))

            with patch.object(KDEWallpaperSetter, "get_ram_dir", return_value=directory):
                KDEWallpaperSetter._prune_blur_cache([])
            self.assertTrue(os.path.isdir(trap))

class TestCacheManager(unittest.TestCase):

    """The download cache had no image validation and no size cap, and only
    trimmed itself on the success path."""

    def _cache(self, directory, **kwargs):
        with patch("core.config.ConfigManager.load", return_value={}):
            return CacheManager(cache_dir=directory, **kwargs)

    def test_cache_trims_itself_on_the_failure_path(self):
        """Cleanup used to live inside the success branch, so a paused daemon
        or an exhausted source queue left the cache above its own limit."""
        with tempfile.TemporaryDirectory() as directory:
            for i in range(6):
                with open(os.path.join(directory, f"old{i}.jpg"), "wb") as f:
                    f.write(b"x")

            cache = self._cache(directory, max_size=3)
            with patch.object(cache, "_download", return_value=None) as mock_dl:
                cache.download("https://example.invalid/nope.jpg", retries=1)

            self.assertEqual(mock_dl.call_count, 1)
            self.assertEqual(len(os.listdir(directory)), 3, "cleanup must run even when download fails")

    def test_byte_ceiling_sheds_oldest_first(self):
        """A count cap says nothing about disk use when file sizes vary."""
        with tempfile.TemporaryDirectory() as directory:
            for name, size in (("big.jpg", 4000), ("mid.jpg", 3000), ("small.jpg", 1000)):
                with open(os.path.join(directory, name), "wb") as f:
                    f.write(b"x" * size)
            cache = self._cache(directory, max_size=100, max_total_bytes=5000)
            # Oldest first, so the 4000-byte file is the one that gets shed.
            for name, when in (("big.jpg", 100), ("mid.jpg", 200), ("small.jpg", 300)):
                os.utime(os.path.join(directory, name), (when, when))
            cache._clean_old_files()

            self.assertFalse(os.path.exists(os.path.join(directory, "big.jpg")))
            self.assertTrue(os.path.exists(os.path.join(directory, "small.jpg")))

    def test_byte_ceiling_leaves_a_fitting_cache_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "keep.jpg")
            with open(path, "wb") as f:
                f.write(b"x" * 100)

            cache = self._cache(directory, max_size=100, max_total_bytes=5000)
            cache._clean_old_files()
            self.assertTrue(os.path.exists(path))

    def test_declared_oversize_is_rejected_before_any_write(self):
        """Content-Length above the cap must not start a download at all."""
        with tempfile.TemporaryDirectory() as directory:
            cache = self._cache(directory, max_file_bytes=1000)
            response = MagicMock()
            response.getcode.return_value = 200
            response.info.return_value = {"Content-Length": "5000"}
            response.read.side_effect = AssertionError("must not read the body")

            opener = MagicMock()
            opener.open.return_value.__enter__.return_value = response
            with patch("urllib.request.build_opener", return_value=opener):
                result = cache.download("https://example.invalid/huge.jpg", retries=1)

            self.assertIsNone(result)
            self.assertEqual(os.listdir(directory), [], "nothing should have been written")

    def test_lying_content_length_is_still_capped_mid_transfer(self):
        """A server that under-reports the length must not stream forever."""
        with tempfile.TemporaryDirectory() as directory:
            cache = self._cache(directory, max_file_bytes=40000)

            # Announces 1000 bytes, then keeps going: 400 KB of nothing.
            chunks = iter([b"x" * 8192 for _ in range(50)])
            response = MagicMock()
            response.getcode.return_value = 200
            response.info.return_value = {"Content-Length": "1000"}
            response.read.side_effect = lambda _n: next(chunks, b"")

            opener = MagicMock()
            opener.open.return_value.__enter__.return_value = response
            with patch("urllib.request.build_opener", return_value=opener):
                result = cache.download("https://example.invalid/liar.jpg", retries=1)

            self.assertIsNone(result)
            self.assertEqual(os.listdir(directory), [], "the oversized partial must be removed")

    def test_undecodable_payload_is_discarded_and_retried(self):
        """EOF does not mean success. A proxy error page arrives with a 200 and
        a plausible length, and used to be written and then handed to the
        decoder."""
        with tempfile.TemporaryDirectory() as directory:
            cache = self._cache(directory, max_file_bytes=1_000_000)
            body = b"<html><body>rate limited</body></html>"

            attempts = {"n": 0}

            def open_side_effect(*_a, **_kw):
                attempts["n"] += 1
                response = MagicMock()
                response.getcode.return_value = 200
                response.info.return_value = {"Content-Length": str(len(body))}
                remaining = [body]

                def read(_n):
                    return remaining.pop(0) if remaining else b""

                response.read.side_effect = read
                return MagicMock(__enter__=lambda self_: response)

            opener = MagicMock()
            opener.open.side_effect = open_side_effect
            with patch("urllib.request.build_opener", return_value=opener), \
                 patch("time.sleep"):
                result = cache.download("https://example.invalid/page.jpg", retries=2)

            self.assertIsNone(result)
            self.assertEqual(attempts["n"], 2, "a junk payload should be re-fetched, not returned")
            self.assertEqual(os.listdir(directory), [], "junk must not linger in the cache")

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