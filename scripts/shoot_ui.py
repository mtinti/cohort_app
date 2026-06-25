#!/usr/bin/env python3
"""Autonomous screenshot harness for the Streamlit requirement-builder UI.

Launches the app headless, waits for Streamlit to actually render (not just the
shell), screenshots it (full page) to ui_shots/, tears everything down.
Screenshots only — no interaction (Playwright used purely for reliable
render-wait + capture).

    python3 scripts/shoot_ui.py [app.py] [--name smoke] [--port 8765] [--width 1600]
"""
import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "ui_shots")


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    apps = [a for a in sys.argv[1:] if not a.startswith("--")]
    app = apps[0] if apps else "scripts/mockup.py"
    name = arg("--name", os.path.splitext(os.path.basename(app))[0])
    port = int(arg("--port", "8765"))
    width = int(arg("--width", "1600"))
    os.makedirs(OUT, exist_ok=True)

    proc = subprocess.Popen(
        ["streamlit", "run", app, "--server.headless", "true",
         "--server.port", str(port), "--browser.gatherUsageStats", "false"],
        cwd=ROOT, stdout=open("/tmp/streamlit_shoot.log", "w"), stderr=subprocess.STDOUT,
    )
    url = f"http://localhost:{port}/"
    try:
        for _ in range(40):                       # wait for the HTTP server
            try:
                urllib.request.urlopen(url, timeout=1); break
            except Exception:
                time.sleep(0.5)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": width, "height": 1100},
                            device_scale_factor=2)
            pg.goto(url, wait_until="networkidle", timeout=30000)
            # wait for the real app body, not just the shell
            pg.wait_for_selector("[data-testid='stAppViewContainer']", timeout=30000)
            pg.wait_for_timeout(1500)             # let widgets settle
            path = os.path.join(OUT, f"{name}.png")
            pg.screenshot(path=path, full_page=True)
            b.close()
        print(f"wrote {os.path.relpath(path, ROOT)}  ({os.path.getsize(path)//1024} KB)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
