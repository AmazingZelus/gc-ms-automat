"""Screenshots of the app's chromatogram for the documentation (needs playwright + Chrome).

Run from the repository root after make_data.py:  python tools/doc_examples/screenshots.py
Writes build/doc/img/*.png.
"""
import os
os.makedirs("build/doc/img", exist_ok=True)
import json, os, subprocess, sys, time, shutil
from playwright.sync_api import sync_playwright
SHOTS = [  # (out, scenario file, params, row RT to click, zoom-out clicks)
 ("01_dvojhrb_auto", "dvojhrb", {}, 5.0, 0),
 ("02_hrbol_spolecna", "hrbol", {"integration_baseline": "drop"}, 4.85, 1),
 ("03_hrbol_auto", "hrbol", {}, 4.85, 1),
 ("04_dvojhrb_na_hrbolu_spolecna", "dvojhrb_na_hrbolu", {"integration_baseline": "drop"}, 5.0, 1),
 ("05_dvojhrb_na_hrbolu_auto", "dvojhrb_na_hrbolu", {}, 5.0, 1),
 ("06_chvost_auto", "chvost", {}, 5.2, 0),
]
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for out, scen, params, rt, zo in SHOTS:
        shutil.rmtree("runtime", ignore_errors=True)
        env = dict(os.environ, GCMS_NO_BROWSER="1")
        proc = subprocess.Popen([sys.executable, "app/main.py"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if os.path.exists("runtime/server.json"): break
            time.sleep(0.2)
        time.sleep(0.3); info = json.load(open("runtime/server.json"))
        page = b.new_page(viewport={"width": 1300, "height": 1000}, device_scale_factor=2)
        page.goto(info["url"]); page.wait_for_selector("#p-min_snr")
        page.set_input_files("#file-in", [f"build/doc/cdf/{scen}.CDF"]); page.locator("#files .file").first.wait_for()
        for k, v in params.items():
            el = page.locator(f"#p-{k}")
            if el.evaluate("e => e.tagName") == "SELECT": el.select_option(v)
            else: el.fill(str(v)); el.press("Tab")
        page.click("#run"); page.wait_for_selector("#results tbody tr")
        rows = page.locator("#results tbody tr")
        target = None
        for i in range(rows.count()):
            cells = rows.nth(i).locator("td")
            if abs(float(cells.nth(2).inner_text()) - rt) < 0.03: target = rows.nth(i); break
        target.click(); time.sleep(0.6)
        for _ in range(zo): page.click("#zoom-out"); time.sleep(0.5)
        page.locator("#chrom").screenshot(path=f"build/doc/img/{out}.png")
        print(out, "ok")
        page.click("#btn-quit"); page.close(); proc.wait(timeout=10)
    b.close()
