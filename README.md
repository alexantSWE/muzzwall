# Muzwall

Muzwall changes your desktop wallpaper for you, it can take pictures from a folder on your computer or get them from Wallhaven over the internet, and it tries to use the wallpaper tool that goes with your desktop so you do not have to pick one every time, and if theme sync is on it can also make some desktop and app colors follow the picture.

## Getting it running

Install the Python packages in this project, then either run the daemon yourself or let the service installer set it up and start it for you:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
python install_service.py
```

The settings are in `config.json`, where you choose the active plugin, the folder or Wallhaven search, how often the picture changes, how it should fit on screen, and the other options that make it behave the way you want, with `python cli.py status` you can see what it thinks is happening and the commands below let you nudge it along:

```bash
python cli.py next
python cli.py prev
python cli.py pause
python cli.py resume
python cli.py config --folder ~/Pictures/Wallpapers --interval 1800 --mode smart --border dynamic
```

For Wallhaven put your own API key in the `wallhaven` section of `config.json` and keep that file private, since the key is needed for some searches and should not be shared around like a wallpaper. The `purity_multipliers` setting makes SFW, sketchy, or NSFW results stay on screen for different amounts of time, so with the usual values a sketchy image stays twice as long and an NSFW one stays three times as long as the normal interval.

You can also make a theme from a local wallpaper or try the night version and return to daytime later, and these use the same wallpaper and theme parts as the daemon so it should mostly feel like one feature even though it is a few commands:

```bash
python cli.py theme --sync ~/Pictures/Wallpapers/example.jpg
python cli.py theme --moon
python cli.py theme --day
```
