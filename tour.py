#!/usr/bin/env python3
"""flex tour: show off the niri + noctalia desktop on camera.

Beats: fastfetch + btop in their own kitty windows, a wallpaper/theme
ripple, a sweep across every workspace, the overview, dock + widgets +
launcher toggles, caffeine, then wrap up and stop recording.

Recording goes to ~/Videos/flex-YYYYmmdd-HHMMSS.mp4 (disable with --no-rec).
"""
import argparse, os, subprocess, sys, time, signal, datetime

NI = ["niri", "msg", "action"]
MZWALL = os.path.expanduser("~/Documents/proj/muzwall/cli.py")

def run(cmd, **kw):
    return subprocess.run(cmd, **kw)

def niri(*args):
    run(NI + list(args), check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def noctalia(*args):
    run(["noctalia", "msg"] + list(args), check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def notify(title, body=""):
    run(["notify-send", "-a", "flex", title, body], check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def hold(sec):
    time.sleep(sec)

WORKSPACES = ["1 Terminal", "2 Dev", "3 Web", "4 Chat", "5 Media", "6 Misc", "7 VPN"]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hold", type=float, default=2.0, help="seconds per workspace beat")
    p.add_argument("--settle", type=float, default=3.0, help="wait after theme change")
    p.add_argument("--no-rec", action="store_true", help="don't record with wf-recorder")
    p.add_argument("--out", default=os.path.expanduser("~/Videos"))
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    procs = []          # kitty windows we spawned
    rec = None          # wf-recorder
    rec_path = None

    try:
        notify("🎬 flex tour", "starting desktop showcase")

        if not args.no_rec:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            rec_path = os.path.join(args.out, f"flex-{stamp}.mp4")
            rec = subprocess.Popen(["wf-recorder", "-f", rec_path])
            hold(1.0)

        # --- fastfetch in its own terminal ---
        niri("focus-workspace", "1 Terminal"); hold(0.8)
        procs.append(subprocess.Popen([
            "kitty", "--class", "kitty-shell", "--title", "fastfetch",
            "-o", "remember_window_size=false", "-o", "initial_window_width=1000",
            "-e", "fastfetch"]))
        hold(args.hold + 1)

        # --- btop, floating task-manager window ---
        procs.append(subprocess.Popen([
            "kitty", "--class", "kitty-btop", "--title", "btop",
            "-o", "remember_window_size=false", "-o", "initial_window_width=1200",
            "-o", "initial_window_height=720", "-e", "btop"]))
        hold(args.hold + 1.5)

        # --- theme/wallpaper ripple (muzwall cascades through niri + kitty) ---
        run([MZWALL, "next"], check=False)
        hold(max(args.settle, 4.0))

        # --- workspace sweep ---
        for ws in WORKSPACES:
            niri("focus-workspace", ws)
            print(f"  workspace: {ws}")
            hold(args.hold)

        # --- overview peek ---
        niri("toggle-overview"); hold(args.hold)
        niri("toggle-overview"); hold(0.6)

        # --- dock / widgets / panels ---
        noctalia("dock-hide"); hold(1.2)
        noctalia("dock-show"); hold(1.2)
        noctalia("desktop-widgets-toggle"); hold(1.4)   # hide
        noctalia("desktop-widgets-toggle"); hold(1.4)   # show
        noctalia("panel-toggle", "launcher"); hold(args.hold)
        noctalia("panel-toggle", "launcher"); hold(0.6)
        noctalia("panel-toggle", "clipboard"); hold(args.hold)
        noctalia("panel-toggle", "clipboard"); hold(0.6)

        # --- caffeine on, so the flex clip never idles to black ---
        noctalia("caffeine-enable"); notify("☕ caffeine on")
        hold(args.hold)

        # --- land back on the terminal beat ---
        niri("focus-workspace", "1 Terminal"); hold(args.hold)

    finally:
        for proc in procs:
            try: proc.terminate()
            except Exception: pass
        for proc in procs:
            try: proc.wait(timeout=3)
            except Exception:
                try: proc.kill()
                except Exception: pass
        if rec is not None:
            rec.send_signal(signal.SIGINT)
            try: rec.wait(timeout=10)
            except Exception: rec.kill()
        # leave the desktop as we found it
        noctalia("caffeine-disable")
        noctalia("dock-show")
        # close any panel we may have left open mid-beat; panel-close with a
        # named id only acts when it is the active one, so this is safe.
        noctalia("panel-close", "launcher")
        noctalia("panel-close", "clipboard")

        if rec_path:
            notify("🎬 flex done", rec_path)
            print(f"\n🎬 {rec_path}")
        else:
            notify("🎬 flex done")

if __name__ == "__main__":
    main()
