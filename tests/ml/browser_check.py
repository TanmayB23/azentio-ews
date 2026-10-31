"""Optional real-browser ML smoke check; requires installed Chrome and playwright."""
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

ROOT=Path(__file__).resolve().parents[2]
ARTIFACTS=ROOT/"artifacts/ui-check"


def main():
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ews-ml-browser-") as folder:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        env={**os.environ,"EWS_VAR_DIR":folder,"EWS_DB_PATH":str(Path(folder)/"evidence.sqlite3")}
        server=subprocess.Popen([sys.executable,"-m","api","--port",str(port)],cwd=ROOT,env=env,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        base=f"http://127.0.0.1:{port}"
        def request(path,payload=None):
            raw=None if payload is None else json.dumps(payload).encode()
            req=urllib.request.Request(base+path,data=raw,headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=120) as response:
                return json.load(response)
        try:
            for _ in range(100):
                try:
                    request("/api/health");break
                except OSError:time.sleep(.2)
            assert request("/api/ml/model")["available"]
            dataset=request("/api/datasets/sample",{"profile":"gcc_islamic","variant":"clean"})
            run=request("/api/runs",{"dataset_id":dataset["dataset_id"],"profile":"gcc_islamic"})
            rid=run["run_id"]
            rows=request(f"/api/runs/{rid}/watchlist?page_size=500")["rows"]
            thin=next(r["customer_id"] for r in rows if r["status"]=="Insufficient data")
            already=next(r["customer_id"] for r in rows if r["current_dpd"] is not None and r["current_dpd"]>=30 and r["status"]=="Scored")
            cid="C0001"
            original=request(f"/api/runs/{rid}/customers/{cid}/alert.json")
            forecast=request(f"/api/runs/{rid}/customers/{cid}/ml")
            assert forecast["status"]=="predicted",forecast
            with sync_playwright() as p:
                browser=p.chromium.launch(channel="chrome",headless=True)
                page=browser.new_page(viewport={"width":1512,"height":1100})
                page.add_init_script("localStorage.setItem('ews.activeRun',"+json.dumps(rid)+")")
                errors=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                page.goto(base+f"/customers/{cid}",wait_until="networkidle")
                expect(page.get_by_role("heading",name="Rule-based assessment",exact=True)).to_be_visible()
                card=page.locator(".ml-card")
                expect(card.get_by_text("model-estimated chance",exact=True)).to_be_visible()
                expect(card.get_by_text("Synthetic-data prototype:",exact=False)).to_be_visible()
                card.screenshot(path=str(ARTIFACTS/"ml-forecast-card.png"))
                page.screenshot(path=str(ARTIFACTS/"ml-customer-desktop.png"),full_page=True)
                card.get_by_text("Model, evaluation and limitations",exact=True).click()
                expect(card.get_by_text("constant-rate baseline",exact=False)).to_be_visible()
                card.screenshot(path=str(ARTIFACTS/"ml-model-details.png"))
                if card.get_by_role("button",name="Show all model factors").count():
                    card.get_by_role("button",name="Show all model factors").click()
                page.set_viewport_size({"width":390,"height":844})
                card.scroll_into_view_if_needed()
                card.screenshot(path=str(ARTIFACTS/"ml-mobile-card.png"))
                page.goto(base+f"/customers/{thin}",wait_until="networkidle")
                expect(page.locator(".ml-card").get_by_text("Insufficient history",exact=True)).to_be_visible()
                page.goto(base+f"/customers/{already}",wait_until="networkidle")
                expect(page.locator(".ml-card").get_by_text("Already 30+ DPD",exact=True)).to_be_visible()
                assert not errors,errors
                browser.close()
            assert request(f"/api/runs/{rid}/customers/{cid}/alert.json")==original
            history=request(f"/api/runs/{rid}/customers/{cid}/ml/history")
            assert len(history)==1 and history[0]["prediction_id"]==forecast["prediction_id"]
            report={"status":"passed","page_errors":errors,"model_id":forecast["model_id"],
                "checks":["Actual trained artifact and API","Forecast alongside unchanged rule score","Synthetic-data disclosure",
                    "Local model factors and diagnostics","Desktop/mobile rendering","Insufficient history",
                    "Already 30+ DPD","Original alert unchanged and forecast reused"]}
            (ARTIFACTS/"ml-browser-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
            print(json.dumps(report,indent=2),flush=True)
        finally:
            server.terminate();server.wait(timeout=15)

if __name__=="__main__":main()
