#!/usr/bin/env python3
"""Showcase reel: cycle wallpapers, let theme sync ripple, capture each beat."""
import argparse, json, os, subprocess, sys, time, glob

STATUS = os.path.expanduser("~/.config/muzwall_status.json")

def status_ts():
    try:
        with open(STATUS) as f: return json.load(f).get("timestamp", 0)
    except Exception: return 0

def next_wallpaper():
    subprocess.run(["systemctl", "--user", "kill", "-s", "SIGUSR1", "muzwall.service"], check=True)

def wait_for_change(old_ts, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.25)
        if status_ts() > old_ts: return True
    return False

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--frames", type=int, default=6)
    p.add_argument("--hold", type=float, default=2.0, help="seconds to hold each frame")
    p.add_argument("--settle", type=float, default=3.0, help="seconds to let niri/kitty reload after a theme change")
    p.add_argument("--out", default=os.path.expanduser("~/Pictures/showcase"))
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # --- The ripple: real-time clip across one theme change ---
    ripple = os.path.join(args.out, "ripple.mp4")
    rec = subprocess.Popen(["wf-recorder", "-f", ripple])
    time.sleep(1.0)
    next_wallpaper()
    time.sleep(7.0)
    rec.send_signal(2)  # SIGINT so wf-recorder finalizes the mp4
    rec.wait()
    print(f"🌊 ripple clip -> {ripple}")

    frames = []
    for i in range(args.frames):
        old = status_ts()
        next_wallpaper()
        if not wait_for_change(old):
            print(f"frame {i}: daemon didn't respond in time, capturing anyway")
        time.sleep(args.settle)
        path = os.path.join(args.out, f"frame_{i:02d}.png")
        subprocess.run(["grim", path], check=True)
        with open(STATUS) as f:
            img = json.load(f).get("image", "?")
        print(f"[{i+1}/{args.frames}] {os.path.basename(img)} -> {path}")
        frames.append(path)

    # mp4 slideshow with fades
    listfile = os.path.join(args.out, "concat.txt")
    with open(listfile, "w") as f:
        for fr in frames:
            f.write(f"file '{fr}'\nduration {args.hold}\n")
        f.write(f"file '{frames[-1]}'\n")
    mp4 = os.path.join(args.out, "showcase.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
                    "-vf", "fps=30,format=yuv420p", "-pix_fmt", "yuv420p", mp4], check=True)

    # discord-friendly gif
    gif = os.path.join(args.out, "showcase.gif")
    subprocess.run(["ffmpeg", "-y", "-i", mp4, "-vf",
                    "fps=10,scale=1280:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                    gif], check=True)

    # contact sheet for the grid flex
    grid = os.path.join(args.out, "showcase_grid.png")
    subprocess.run(["montage"] + frames + ["-tile", "3x2", "-geometry", "+8+8",
                    "-background", "#111111", grid], check=True)

    print(f"\n🎬 {mp4}\n🎞️  {gif}\n🖼️  {grid}")

if __name__ == "__main__":
    main()
