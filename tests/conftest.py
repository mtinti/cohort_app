"""Pytest fixtures: a headless Streamlit server + a Playwright page.

The server is session-scoped (started once); each test gets a fresh browser
context/page, which means a fresh Streamlit session (state re-inits from the
example), so tests are isolated.
"""
import os
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PORT = int(os.environ.get("APP_TEST_PORT", "8799"))
URL = f"http://localhost:{PORT}/"


@pytest.fixture(scope="session")
def app_server():
    subprocess.run(["pkill", "-f", f"--server.port {PORT}"], capture_output=True)
    proc = subprocess.Popen(
        ["streamlit", "run", "app.py", "--server.headless", "true",
         "--server.port", str(PORT), "--browser.gatherUsageStats", "false"],
        cwd=ROOT, stdout=open("/tmp/streamlit_test.log", "w"), stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(URL, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("streamlit did not start; see /tmp/streamlit_test.log")
        yield URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


@pytest.fixture(scope="session")
def _browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def page(app_server, _browser):
    ctx = _browser.new_context(accept_downloads=True, viewport={"width": 1500, "height": 1200})
    pg = ctx.new_page()
    pg.goto(app_server, wait_until="domcontentloaded")
    pg.wait_for_selector("[data-testid='stAppViewContainer']", timeout=30000)
    settle(pg)
    yield pg
    ctx.close()


# --- second server with the samples/biobank UI flag ON -----------------------
PORT_FLAG = int(os.environ.get("APP_TEST_PORT_FLAG", "8798"))
URL_FLAG = f"http://localhost:{PORT_FLAG}/"


@pytest.fixture(scope="session")
def app_server_flag():
    subprocess.run(["pkill", "-f", f"--server.port {PORT_FLAG}"], capture_output=True)
    proc = subprocess.Popen(
        ["streamlit", "run", "app.py", "--server.headless", "true",
         "--server.port", str(PORT_FLAG), "--browser.gatherUsageStats", "false"],
        cwd=ROOT, stdout=open("/tmp/streamlit_test_flag.log", "w"),
        stderr=subprocess.STDOUT,
        env={**os.environ, "COHORT_ENABLE_SAMPLES": "1"},
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(URL_FLAG, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("flag server did not start; see /tmp/streamlit_test_flag.log")
        yield URL_FLAG
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


@pytest.fixture()
def page_flag(app_server_flag, _browser):
    ctx = _browser.new_context(accept_downloads=True, viewport={"width": 1500, "height": 1200})
    pg = ctx.new_page()
    pg.goto(app_server_flag, wait_until="domcontentloaded")
    pg.wait_for_selector("[data-testid='stAppViewContainer']", timeout=30000)
    settle(pg)
    yield pg
    ctx.close()


def settle(pg, ms=1200):
    """Wait for Streamlit to finish a rerun."""
    try:
        pg.wait_for_selector("[data-testid='stStatusWidget']", state="visible", timeout=800)
        pg.wait_for_selector("[data-testid='stStatusWidget']", state="hidden", timeout=15000)
    except Exception:
        pass
    pg.wait_for_timeout(ms)
