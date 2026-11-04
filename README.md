# Muzwall

Muzwall rotates your desktop wallpaper from a local picture folder or Wallhaven. It can also create a color theme from the current picture, and it can make a darker night version and restore the daytime picture later.

## Start here

Create a Python environment, install the requirements, then start the daemon in the terminal:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python daemon.py
```

To run it as a background user service that starts after login, install it with:

```bash
.venv/bin/python install_service.py
```

The settings are in `config.json`. The default source is a local folder, so set `plugins.local_folder.path` to your wallpaper folder if it is different from the one already there. Check the current status with `python cli.py status`.

## Everyday controls

```bash
python cli.py next       # show the next picture
python cli.py prev       # return to the previous picture
python cli.py pause      # pause automatic rotation
python cli.py resume     # resume automatic rotation
python cli.py toggle     # switch between paused and running
python cli.py logs       # follow the daemon log
```

Pausing only stops automatic changes, so `next` and `prev` still work while paused. Service controls are `python cli.py start`, `stop`, and `restart`.

## Main settings

| Setting | What it does |
| --- | --- |
| `interval_seconds` | Seconds to show a wallpaper before rotating. For example, `1800` is 30 minutes. Values must be positive. |
| `scale_mode` | How to fit the picture: `fill`, `fit`, `stretch`, `center`, `tile`, or `smart`. Smart mode chooses based on the picture and screen shape. |
| `border_color` | A hex color such as `#203040`, `dynamic` to use a color from the picture, or `blur` to fill empty space with a blurred copy. |
| `show_notifications` | Show a desktop notification after a wallpaper changes. |
| `theme_sync` | Update supported desktop and app colors from each new wallpaper. |
| `unique_wallpapers` | Use a different picture for each screen or desktop when the selected wallpaper backend supports it. |

Most settings can be changed with `python cli.py config`. For example, this uses a local folder, scans subfolders, and rotates every 30 minutes:

```bash
python cli.py config --folder ~/Pictures/Wallpapers --recursive true --interval 1800 --mode smart --border dynamic
```

For the local folder source, Muzwall reads JPG, PNG, WebP, and BMP pictures, `order` can be `random` or `sequential`, `persist_history` remembers the previous and next pictures across restarts, and `recursive` includes pictures inside subfolders. These are in `plugins.local_folder`; the command options are `--order random|sequential`, `--persist true|false`, and `--recursive true|false`.

## Theme support

When `theme_sync` is enabled, Muzwall checks what is available and updates the matching parts of these apps:

- **KDE Plasma:** desktop color scheme and accent colors.
- **Klassy:** window borders and decoration colors, when the Klassy decoration plugin is installed.
- **GTK 3 and GTK 4 apps:** shared color tokens used by many GTK applications.
- **Kitty:** terminal background, text, cursor, selection, and ANSI colors.
- **Niri:** focus rings, tab indicators, insert hints, and window switcher highlights.
- **Fastfetch:** terminal output colors and the Muzwall cat logo.
- **btop:** the terminal monitor's colors and graphs.

Apps use these theme files in different ways, and some apply changes after a reload or when opened again. Muzwall skips adapters that are not available on the system. To create a theme from a picture by hand, or set its color hue directly, use:

```bash
python cli.py theme --sync ~/Pictures/Wallpapers/example.jpg
python cli.py theme --hue 210
```

Nightlight creates a darker, cooler copy of the current wallpaper and adjusts the theme colors too. `--day` restores the picture that was active before nightlight:

```bash
python cli.py theme --moon       # default strength: 0.65
python cli.py theme --moon 0.8   # strength can be from 0 to 1
python cli.py theme --day
```

Nightlight needs ImageMagick (`magick` or `convert`). Add `--no-activate` to a theme command to write theme files without asking running apps to reload.

For other theme actions, `python cli.py theme --accent-hex` prints the accent color for the current wallpaper, and `python cli.py theme --watch` watches for changes made outside Muzwall and resyncs the theme when it sees one.

<details>
<summary>Wallhaven source and purity timing</summary>

To use online pictures, set `active_plugin` to `wallhaven` and edit `plugins.wallhaven` in `config.json`:

```bash
python cli.py config --plugin wallhaven --wh-query nature --wh-purity 100
```

| Option | Meaning |
| --- | --- |
| `query` | Search words, such as `nature` or `space`. |
| `categories` | Which categories to search. `111` includes General, Anime, and People. |
| `purity` | Which content ratings are allowed. `100` is SFW, `110` is SFW plus sketchy, and `001` is NSFW. |
| `sorting` | `random`, `latest`, `toplist`, or `views`. |
| `max_size_mb` | Maximum size for each downloaded image. |
| `api_key` | Your Wallhaven key; required for NSFW searches. Keep it private. |

The purity labels returned by Wallhaven can change display time through `settings.purity_multipliers`. The usual values are `sfw: 1`, `sketchy: 2`, and `nsfw: 3`, which means a sketchy result stays twice as long as the normal interval and an NSFW result stays three times as long. Muzwall uses Wallhaven's result label for this; it does not decide the rating by inspecting the picture.

These options can also be set with `python cli.py config --wh-query nature --wh-categories 111 --wh-purity 100 --wh-sorting latest --wh-maxsize 10`. Use `--wh-apikey YOUR_KEY` to set a key from the command line, or `--proxy none` to clear a configured proxy and connect directly.

</details>

<details>
<summary>Advanced wallpaper backends and custom commands</summary>

`wallpaper_backend` is normally `auto`, which tries the backends available in the current desktop session and falls back if one fails. You can prefer `portal`, `layer-shell`, `x11`, or `plasma`; `command` runs a user-supplied wallpaper command. `python cli.py status` shows which backends are available.

Set `wallpaper_command` to a command template if your desktop uses a tool Muzwall does not call directly. The supported placeholders are:

- `{image}` — the first wallpaper path.
- `{images}` — all selected wallpaper paths, for tools that support multiple screens.
- `{mode}` — the requested scaling mode.

For example, a swaybg command can be configured as `swaybg -i {image} -m {mode}`. Shell execution is off by default; set `wallpaper_command_shell` to `true` only when the command needs shell features. Use `--wallpaper-command none` to clear the custom command.

The portal backend has a timeout controlled by `portal_timeout`. `wallpaper_query_command` can be set when Muzwall needs a custom command to find the wallpaper that was active before it started, so it can restore it on shutdown.

The `proxy` setting accepts a proxy address or `none`. Advanced `proxy_autodetect` can scan common local proxy ports, and `proxy_probe` can be enabled to check whether a candidate proxy connects before using it. Autodetection and probing are off unless you enable them.

Smart scaling and blur borders need display dimensions for their image work. Muzwall tries to read the active display size, and `MUZWALL_DISPLAY_SIZE=2560x1440` can supply it manually if the desktop tools do not report it.

</details>

<details>
<summary>Theme files and technical notes</summary>

Theme adapters write files under the normal XDG config and data folders. For example, GTK gets generated color tokens, Kitty gets a separate palette file that it can include, Niri gets a separate theme fragment, Fastfetch gets its generated config and logo, and btop gets a theme file plus the setting that selects it. Muzwall avoids changing each app in the same way because their theme support is different, and a theme may only color some parts of an app.

`MUZWALL_CONFIG` can point to a config file other than the project `config.json`. Runtime state and logs use the XDG state folder, theme config uses the XDG config folder, and generated nightlight files use the XDG cache folder. Wallhaven downloads are stored in `~/.cache/muzwall`.

For development, install `requirements-dev.txt` and run the local suite with `python -m pytest -q`.

</details>
