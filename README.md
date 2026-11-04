# Muzwall

Muzwall changes your desktop wallpaper on a timer, it can pick pictures from a folder on your computer or find and download them from Wallhaven, and it chooses a wallpaper tool that looks like it belongs to your desktop so you do not have to keep setting that up yourself, and if theme sync is turned on it can also make some of your desktop and app colors follow the picture.

## Getting it running

Install the Python packages from this project, and then either start the daemon in your terminal or install it as a user service which makes it start in the background and after login too:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python daemon.py
```

Or, to have systemd keep it running for you, run this instead of the last command:

```bash
.venv/bin/python install_service.py
```

The main settings live in `config.json`, and `MUZWALL_CONFIG` can point to a different file if you want to keep another setup around, and you can ask what Muzwall is doing with `python cli.py status` or look at the changing log with `python cli.py logs`.

## Wallpapers and rotation

The `active_plugin` setting picks `local_folder` or `wallhaven`, and for the local folder you set `plugins.local_folder.path` to where your pictures live, `order` can be `random` or `sequential`, `recursive` lets it look into folders inside that folder, and `persist_history` remembers the order and previous pictures across daemon restarts so the back button can still work.

The usual `settings` options are what makes the rotation act differently, and most can also be changed with `python cli.py config`:

- `interval_seconds` is how many seconds to show each wallpaper, so `1800` means about half an hour, and it must be greater than zero.
- `scale_mode` can be `fill`, `fit`, `stretch`, `center`, `tile`, or `smart`, where smart looks at the image and screen shape and tries to choose a sensible one.
- `border_color` can be a hex color like `#203040`, `dynamic` to pick a color from the image, or `blur` to fill empty space with a blurred copy of the picture.
- `show_notifications` shows a desktop note after the wallpaper changes, and `theme_sync` updates the supported local theme files from the new picture as well.
- `unique_wallpapers` asks for different pictures for different screens or desktops when the selected wallpaper backend can assign them separately, which works best with Plasma or an X11 setup using feh.
- `wallpaper_backend` is normally `auto`, which tries the backends available in your session, or you can ask for `portal`, `layer-shell`, `x11`, `plasma`, or the `command` fallback yourself.
- `wallpaper_command` can hold a command for a wallpaper tool that Muzwall does not know directly, using placeholders such as `{image}`, `{images}`, and `{mode}`; shell mode is off by default so the template is run as arguments.

For example, this changes the folder, rotates every half hour, scans inside folders, and uses smart scaling with a color chosen from each picture:

```bash
python cli.py config --folder ~/Pictures/Wallpapers --interval 1800 --recursive true --mode smart --border dynamic
```

The other everyday controls are `python cli.py next`, `python cli.py prev`, `python cli.py pause`, `python cli.py resume`, and `python cli.py toggle`, and pause only stops automatic rotation so you can still use next and previous by hand.

## Wallhaven

For online wallpapers set `active_plugin` to `wallhaven` and edit the `plugins.wallhaven` section in `config.json`, where `query` is the search words, `categories` selects General/Anime/People, `sorting` can be random or a sort such as latest or toplist, and `max_size_mb` limits how large an image Muzwall will download. Put your own API key in `api_key` when the Wallhaven search settings need one and keep the config file private, because the key is a secret and does not belong in screenshots or shared copies of the file.

The `purity` option controls which results are allowed, and `settings.purity_multipliers` can make some kinds stay on screen longer, so the usual `sfw: 1`, `sketchy: 2`, and `nsfw: 3` values mean a sketchy picture stays twice the normal interval and an NSFW picture stays three times as long, and those labels come from Wallhaven result data rather than from Muzwall guessing by looking at the image.

You can change the online settings from the command line too, for example `python cli.py config --wh-query nature --wh-purity 100 --wh-sorting latest --wh-maxsize 10`, and `--proxy none` clears a saved proxy if you want Wallhaven to connect directly.

## Theme sync and night wallpaper

When theme sync is on Muzwall checks which theme adapters make sense on this computer and writes the palette for those that are available, which can include the KDE Plasma color scheme, Klassy window borders and decorations, GTK 3 and GTK 4 color tokens, Kitty terminal colors, Niri focus rings and tab highlights, Fastfetch text colors and its little cat, and the btop terminal monitor theme, and it skips apps that are not installed or do not have a suitable config rather than making every app setting appear out of nowhere. Some apps pick up their new colors after reload or when next opened, and each app decides how much of the generated colors it uses.

You can make a theme from one local picture or set a hue by hand, and `--no-activate` writes the theme files without asking running apps to reload them:

```bash
python cli.py theme --sync ~/Pictures/Wallpapers/example.jpg
python cli.py theme --hue 210 --no-activate
```

The optional nightlight command makes a darker, cooler copy of the current wallpaper and moves the theme colors toward night too, then `--day` restores the daytime picture that was there before:

```bash
python cli.py theme --moon
python cli.py theme --moon 0.8
python cli.py theme --day
```

Nightlight strength goes from `0` to `1`, with `0.65` used when no number is given, and ImageMagick needs to be installed for it to create the picture.
