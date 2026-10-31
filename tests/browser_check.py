"""Manual browser audit: pip install playwright, then python tests/browser_check.py.

Uses installed Chrome headlessly; output is written to artifacts/ui-check/.
All analyst reviews go to a temporary database, never the user's live database.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts/ui-check"
expect.set_options(timeout=30000)


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    report = {"checks": [], "page_errors": []}
    def passed(name):
        report["checks"].append(name)
        print("PASS:", name, flush=True)
    with tempfile.TemporaryDirectory(prefix="ews-browser-") as folder:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "app/main.py"),
            "--server.headless=true", "--server.address=127.0.0.1", f"--server.port={port}"],
            cwd=ROOT, env={**os.environ, "EWS_DB_PATH": str(Path(folder)/"audit.sqlite3")},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1):
                        break
                except OSError:
                    time.sleep(.2)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                page.set_default_timeout(15000)
                try:
                    page.goto(f"http://127.0.0.1:{port}")
                    sidebar = page.locator('[data-testid="stSidebar"]')
                    def settle():
                        page.wait_for_function("document.querySelector('[data-testid=stApp]')?.getAttribute('data-test-script-state') === 'notRunning'", timeout=120000)
                        expect(page.locator('[data-stale="true"]')).to_have_count(0)
                    def ready(title):
                        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible(timeout=30000)
                        settle()
                        expect(page.locator('[data-testid="stException"]')).to_have_count(0)
                    def nav(label, title):
                        sidebar.get_by_text(label, exact=True).click()
                        ready(title)
                        page.locator('[data-testid="stMain"]').evaluate('(el)=>el.scrollTop=0')
                    def choose(label, text):
                        page.get_by_role("combobox", name=label, exact=True).click()
                        page.get_by_role("option", name=text, exact=True).click()
                    def screenshot(name):
                        settle()
                        page.screenshot(path=str(ARTIFACTS / name), full_page=True)
                    ready("Data workspace")
                    screenshot("desktop-data.png")
                    page.get_by_role("button", name="Load dataset", exact=True).click()
                    expect(page.get_by_text("Dataset loaded. Review validation results before scoring.", exact=True)).to_be_visible(timeout=30000)
                    page.get_by_role("button", name="Score portfolio", exact=True).click()
                    expect(page.get_by_text("Saved scoring run with 500 customer alerts. Open Watchlist.", exact=True)).to_be_visible(timeout=120000)
                    passed("India: load and real scoring")
                    nav("Watchlist", "Risk watchlist")
                    expect(page.locator('[data-testid="stDataFrame"]')).to_have_count(1)
                    choose("Band", "Insufficient data")
                    expect(page.get_by_text("12 customers | Highest risk first", exact=True)).to_be_visible()
                    screenshot("desktop-thin-history.png")
                    passed("Watchlist band filter includes thin history")
                    # Remove the selected chip, then search for one customer.
                    page.get_by_role("combobox", name="Band", exact=True).press("Backspace")
                    page.get_by_role("combobox", name="Band", exact=True).press("Escape")
                    expect(page.get_by_text("500 customers | Highest risk first", exact=True)).to_be_visible()
                    page.get_by_role("textbox", name="Search customers", exact=True).fill("C0001")
                    page.get_by_role("textbox", name="Search customers", exact=True).press("Enter")
                    expect(page.get_by_text("1 customer | Highest risk first", exact=True)).to_be_visible()
                    screenshot("desktop-watchlist.png")
                    table = page.locator('[data-testid="stDataFrame"] canvas').first
                    table.scroll_into_view_if_needed()
                    box = table.bounding_box()
                    page.mouse.click(box["x"]+18, box["y"]+54)
                    ready("Customer detail")
                    passed("Watchlist search and actual row-checkbox selection")
                    page.locator('[data-testid="stMain"]').evaluate('(el)=>el.scrollTop=0')
                    expect(page.locator(".customer-dashboard .cd-card")).to_have_count(6)
                    expect(page.locator(".cd-gauge")).to_be_visible()
                    expect(page.locator(".cd-gauge")).to_contain_text("Not scored")
                    assert len(page.locator(".cd-grid").evaluate("el=>getComputedStyle(el).gridTemplateColumns").split()) == 3
                    screenshot("desktop-customer-evidence.png")
                    page.get_by_role("tab", name="Account activity", exact=True).click()
                    expect(page.get_by_role("heading", name="Monthly inflows and outflows", exact=True)).to_be_visible()
                    screenshot("desktop-customer-activity.png")
                    passed("Customer account charts render")
                    page.get_by_role("tab", name="Analyst review", exact=True).click()
                    page.get_by_role("button", name="Record review", exact=True).click()
                    expect(page.get_by_text("Choose a valid decision and supply a reason and analyst name", exact=True)).to_be_visible()
                    page.get_by_role("textbox", name="Analyst name (required)", exact=True).fill("Browser audit")
                    page.get_by_role("textbox", name="Reason (required)", exact=True).fill("Verified account evidence in Chrome")
                    page.get_by_role("button", name="Record review", exact=True).click()
                    expect(page.get_by_text("Review appended to history.", exact=True)).to_be_visible()
                    choose("Decision", "Monitor")
                    page.get_by_role("textbox", name="Analyst name (required)", exact=True).fill("Browser audit")
                    page.get_by_role("textbox", name="Reason (required)", exact=True).fill("Follow-up decision retains original evidence")
                    page.get_by_role("button", name="Record review", exact=True).click()
                    expect(page.get_by_text("Review appended to history.", exact=True)).to_be_visible()
                    screenshot("desktop-review.png")
                    passed("Review validation and two successive decisions")
                    # Scroll the content and ensure its title bar is not fixed.
                    page.locator('[data-testid="stMain"]').evaluate('(el)=>el.scrollTop=0')
                    before = page.locator('.customer-dashboard').bounding_box()["y"]
                    page.locator('[data-testid="stMain"]').evaluate('(el)=>el.scrollTop=400')
                    after = page.locator('.customer-dashboard').bounding_box()["y"]
                    assert after < before - 100, (before, after)
                    assert page.locator('[data-testid="stHeader"]').evaluate('(el)=>getComputedStyle(el).pointerEvents') == "none"
                    passed("Title bar scrolls and native header does not intercept content")
                    nav("Portfolio", "Portfolio overview")
                    expect(page.locator('[data-testid="stDataFrame"]')).to_have_count(2)
                    screenshot("desktop-portfolio.png")
                    table = page.locator('[data-testid="stDataFrame"]').nth(1).locator('canvas').first
                    table.scroll_into_view_if_needed()
                    box = table.bounding_box()
                    page.mouse.click(box["x"]+18, box["y"]+54)
                    ready("Customer detail")
                    passed("Portfolio chart, cluster list and customer drill-down")
                    nav("Saved evidence", "Saved evidence")
                    expect(page.get_by_role("combobox", name="Scoring run", exact=True)).to_be_visible()
                    passed("Saved evidence is accessible")
                    nav("Data", "Data workspace")
                    choose("Sample portfolio", "Gulf-Islamic")
                    expect(sidebar.get_by_role("combobox", name="Region", exact=True)).to_have_value("Gulf-Islamic")
                    page.get_by_role("button", name="Load dataset", exact=True).click()
                    expect(page.get_by_text("Dataset loaded. Review validation results before scoring.", exact=True)).to_be_visible()
                    page.get_by_role("button", name="Score portfolio", exact=True).click()
                    expect(page.get_by_text("Saved scoring run with 400 customer alerts. Open Watchlist.", exact=True)).to_be_visible(timeout=120000)
                    nav("Portfolio", "Portfolio overview")
                    screenshot("desktop-gulf-portfolio.png")
                    passed("Gulf sample, matching profile and real assessment")
                    nav("Customer detail", "Customer detail")
                    page.set_viewport_size({"width": 1672, "height": 1100})
                    expect(page.locator(".customer-dashboard .cd-card")).to_have_count(6)
                    assert "out of 100" in page.locator(".cd-gauge").get_attribute("aria-label")
                    screenshot("customer-dashboard.png")
                    page.locator(".customer-dashboard").screenshot(path=str(ARTIFACTS / "customer-dashboard-cards.png"))
                    page.get_by_role("tab", name="SME indicators", exact=True).click()
                    expect(page.get_by_role("heading", name="SME business indicators", exact=True)).to_be_visible()
                    passed("Reference-style customer cards, actual risk gauge and SME detail")
                    # Actual mobile viewport and sidebar interactions, after transitions settle.
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(800)
                    opener = page.get_by_role("button", name="Expand sidebar", exact=True)
                    expect(opener).to_be_visible()
                    opener.click()
                    page.wait_for_timeout(500)
                    expect(sidebar.get_by_text("Customer detail", exact=True)).to_be_visible()
                    sidebar.get_by_text("Customer detail", exact=True).click()
                    ready("Customer detail")
                    page.wait_for_timeout(500)
                    # On a narrow screen, selecting navigation should leave the content usable.
                    if page.get_by_role("button", name="Collapse sidebar", exact=True).is_visible():
                        page.get_by_role("button", name="Collapse sidebar", exact=True).click()
                    page.locator('[data-testid="stMain"]').evaluate('(el)=>el.scrollTop=0')
                    page.wait_for_timeout(500)
                    screenshot("mobile-customer.png")
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    assert len(page.locator(".cd-grid").evaluate("el=>getComputedStyle(el).gridTemplateColumns").split()) == 1
                    opener = page.get_by_role("button", name="Expand sidebar", exact=True)
                    expect(opener).to_be_visible()
                    opener.click()
                    page.wait_for_timeout(500)
                    sidebar.get_by_text("Data", exact=True).click()
                    ready("Data workspace")
                    if page.get_by_role("button", name="Collapse sidebar", exact=True).is_visible():
                        page.get_by_role("button", name="Collapse sidebar", exact=True).click()
                    page.wait_for_timeout(500)
                    screenshot("mobile-data.png")
                    passed("Mobile: navigation, sidebar opener and no page overflow")
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    page.wait_for_timeout(500)
                    choose("Sample dataset", "dirty")
                    page.get_by_role("button", name="Load dataset", exact=True).click()
                    expect(page.get_by_text("Action counts", exact=False)).to_be_visible()
                    expect(page.get_by_text("Repaired:", exact=False)).to_be_visible()
                    screenshot("desktop-dirty-data.png")
                    passed("Dirty sample displays validation actions and quarantine")
                    assert not report["page_errors"], report["page_errors"]
                    report["status"] = "passed"
                except Exception as error:
                    report["status"] = "failed"
                    report["failure"] = str(error)
                    page.screenshot(path=str(ARTIFACTS / "failure.png"), full_page=True)
                    raise
                finally:
                    (ARTIFACTS / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=15)

if __name__ == "__main__":
    main()
