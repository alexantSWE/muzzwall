#!/usr/bin/env python3
import unittest
import os
import json
from unittest.mock import patch, mock_open, MagicMock

# Import the modules we want to test
from core.config import ConfigManager, CONFIG_PATH
from core.setter import KDEWallpaperSetter
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

    @patch("builtins.open", new_callable=mock_open)
    def test_save_success(self, mock_file):
        test_data = {"test": "data"}
        result = ConfigManager.save(test_data)
        self.assertTrue(result)
        mock_file.assert_called_once_with(CONFIG_PATH, "w")

class TestKDEWallpaperSetter(unittest.TestCase):

    def test_hex_to_rgb(self):
        self.assertEqual(KDEWallpaperSetter.hex_to_rgb("#000000"), "0,0,0")
        self.assertEqual(KDEWallpaperSetter.hex_to_rgb("#FFFFFF"), "255,255,255")

    @patch("os.path.exists")
    @patch("subprocess.run")
    def test_set_wallpaper_success(self, mock_subprocess, mock_exists):
        mock_exists.return_value = True
        result = KDEWallpaperSetter.set_wallpaper("/fake/path.jpg", mode="fit")
        self.assertTrue(result)
        mock_subprocess.assert_called_once()
        
    @patch("os.path.exists")
    def test_get_current_wallpaper(self, mock_exists):
        fake_appletsrc = """
[Containments][1][Wallpaper][org.kde.image][General]
Color=45,60,75
FillMode=1
Image=file:///home/user/pic.png
"""
        mock_exists.return_value = True
        with patch("builtins.open", mock_open(read_data=fake_appletsrc)):
            state = KDEWallpaperSetter.get_current_wallpaper()

        self.assertEqual(state.get("image"), "/home/user/pic.png")
        self.assertEqual(state.get("mode"), "fit")

class TestLocalFolderSource(unittest.TestCase):

    @patch("os.path.exists")
    @patch("os.listdir")
    def test_fetch_next_sequential(self, mock_listdir, mock_exists):
        mock_exists.return_value = True
        mock_listdir.return_value = ["a.jpg", "b.png"]
        
        # persist_history=False so the test strictly uses memory without trying to hit the OS filesystem logic
        source = LocalFolderSource("/fake/folder", order="sequential", persist_history=False)
        # Ensure it loops correctly
        self.assertEqual(source.fetch_next(), "/fake/folder/a.jpg")
        self.assertEqual(source.fetch_next(), "/fake/folder/b.png")
        self.assertEqual(source.fetch_next(), "/fake/folder/a.jpg")
        
        # Ensure prev goes back correctly
        self.assertEqual(source.fetch_prev(), "/fake/folder/b.png")

class TestWallhavenSource(unittest.TestCase):

    def test_init_defaults(self):
        source = WallhavenSource()
        self.assertEqual(source.max_size_bytes, 20.0 * 1024 * 1024)

    @patch("urllib.request.urlopen")
    def test_fetch_api_batch_filtering(self, mock_urlopen):
        mock_response = MagicMock()
        # Mock JSON: one 5MB image (kept), one 25MB image (discarded based on 20MB limit)
        fake_json = json.dumps({
            "data": [
                {"path": "https://fake/1.jpg", "file_size": 5 * 1024 * 1024},
                {"path": "https://fake/2.jpg", "file_size": 25 * 1024 * 1024}
            ]
        })
        mock_response.read.return_value = fake_json.encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        # We set sorting to "toplist" to force the pagination code block to execute (testing the str() fix)
        source = WallhavenSource(max_size_mb=20.0, sorting="toplist")
        source._fetch_api_batch()
        
        # Ensure the queue only contains the valid image that was under the size limit
        self.assertEqual(len(source.image_queue), 1)
        self.assertEqual(source.image_queue[0], "https://fake/1.jpg")
        # Ensure the page iterator advanced successfully
        self.assertEqual(source.current_page, 2)

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
        import argparse
        mock_load.return_value = {}
        # Simulate the argparse namespace exactly as it comes from CLI
        args = argparse.Namespace(
            interval=None, mode=None, border=None, notify=None, unique=None, plugin=None,
            folder=None, order=None, recursive=None, persist=None,
            wh_query="cyberpunk", wh_categories=None, wh_purity=None, wh_sorting=None, 
            wh_apikey=None, wh_maxsize=30.0
        )
        cli.handle_config(args)
        
        mock_save.assert_called_once()
        saved_config = mock_save.call_args[0][0]
        
        self.assertEqual(saved_config["plugins"]["wallhaven"]["query"], "cyberpunk")
        self.assertEqual(saved_config["plugins"]["wallhaven"]["max_size_mb"], 30.0)

if __name__ == "__main__":
    unittest.main()