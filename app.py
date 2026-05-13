'''almeno una Under è < 2.5 e almeno una Over è > 1.5'''
import multiprocessing
multiprocessing.freeze_support()

import sys
import os
import ctypes
import asyncio
import webbrowser
import threading
import tkinter as tk
import subprocess
import glob
import shutil
import zipfile
import urllib.request
import json
import time
from flask import Flask, render_template, jsonify, request
from playwright.async_api import async_playwright
from waitress import serve

CHROMIUM_DOWNLOAD_URL = (
    # lo devi prendere da https://github.com/microsoft/playwright/blob/main/packages/playwright-core/browsers.json 
    "https://www.googleapis.com/download/storage/v1/b/chromium-browser-snapshots/o/Win_x64%2F1551223%2Fchrome-win.zip?alt=media"
)

def _single_instance_or_exit():
    if sys.platform != "win32":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, "Global\\AppScraperSingleInstance")
    if ctypes.get_last_error() == 183:
        sys.exit(0)
    _single_instance_or_exit._mutex_handle = handle

_single_instance_or_exit()

def resource_path(*parts):
    base = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)

def exe_dir():
    if hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_chromium_path():
    candidates = [
        os.path.join(exe_dir(), "chromium", "chrome.exe"),
        os.path.join(exe_dir(), "chromium", "chrome-win", "chrome.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    search_roots = [
        os.path.join(exe_dir(), "ms-playwright"),
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright"),
        os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright"),
    ]
    patterns = [
        os.path.join("chromium-*", "chrome-win", "chrome.exe"),
        os.path.join("chromium-*", "chrome-linux", "chrome"),
    ]
    for root in search_roots:
        for pat in patterns:
            found = glob.glob(os.path.join(root, pat))
            if found:
                return found[0]
    return None

class SplashScreen:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0f0f0f")
        W, H = 400, 200
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
        self._status_var = tk.StringVar(value="Sto preparando tutto...")
        tk.Label(self.root, textvariable=self._status_var, bg="#0f0f0f", fg="#888888", font=("Helvetica", 10)).pack()
        self._progress_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self._progress_var, bg="#0f0f0f", fg="#4f9ef8", font=("Helvetica", 9)).pack()
        self._canvas = tk.Canvas(self.root, width=320, height=4, bg="#1e1e1e", highlightthickness=0)
        self._canvas.pack(pady=16)
        self._bar = self._canvas.create_rectangle(0, 0, 0, 4, fill="#4f9ef8", outline="")
        self._pos = 0
        self._direction = 1
        self._animating = True
        self._animate()

    def _animate(self):
        if not self._animating:
            return
        BAR_W, MAX = 70, 320
        self._pos += self._direction * 6
        if self._pos + BAR_W >= MAX or self._pos <= 0:
            self._direction *= -1
        self._canvas.coords(self._bar, self._pos, 0, self._pos + BAR_W, 4)
        self.root.after(30, self._animate)

    def set_status(self, text: str):
        self.root.after(0, lambda: self._status_var.set(text))

    def set_progress(self, text: str):
        self.root.after(0, lambda: self._progress_var.set(text))

    def set_bar(self, fraction: float):
        self._animating = False
        w = int(320 * max(0.0, min(1.0, fraction)))
        self.root.after(0, lambda: self._canvas.coords(self._bar, 0, 0, w, 4))

    def close(self):
        self.root.after(0, self.root.destroy)

    def run(self):
        self.root.mainloop()

def _download_chromium(splash: SplashScreen):
    dest_dir = os.path.join(exe_dir(), "chromium")
    zip_path = os.path.join(exe_dir(), "chromium.zip")
    splash.set_status("Sto scaricando Chromium...")
    def _progress(block_num, block_size, total_size):
        if total_size > 0:
            pct = block_num * block_size / total_size
            splash.set_bar(pct)
            mb_done = block_num * block_size / 1_048_576
            mb_total = total_size / 1_048_576
            splash.set_progress(f"{mb_done:.1f} / {mb_total:.1f} MB")
    try:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
        urllib.request.urlretrieve(CHROMIUM_DOWNLOAD_URL, zip_path, _progress)
    except Exception as e:
        raise RuntimeError(f"Download fallito: {e}")
    splash.set_status("Estrazione...")
    splash.set_progress("")
    splash.set_bar(1.0)
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(dest_dir)
    os.remove(zip_path)
    found = glob.glob(os.path.join(dest_dir, "**", "chrome.exe"), recursive=True)
    if not found:
        raise RuntimeError("chrome.exe non trovato dopo estrazione")
    return found[0]

def ensure_chromium():
    if get_chromium_path():
        return
    splash = SplashScreen()
    def _install():
        try:
            _download_chromium(splash)
            if get_chromium_path():
                splash.set_status("Pronto!")
                splash.set_progress("")
                splash.root.after(800, splash.close)
            else:
                splash.set_status("Errore: chrome.exe non trovato.")
                splash.root.after(4000, sys.exit)
        except Exception as e:
            splash.set_status(str(e)[:80])
            splash.root.after(5000, sys.exit)
    threading.Thread(target=_install, daemon=True).start()
    splash.run()

app = Flask(__name__, template_folder=resource_path('templates'), static_folder=resource_path('static'))
last_req = time.time()

@app.before_request
def update_last_request_time():
    global last_request_time
    last_request_time = time.time()

async def get_match_names(page):
    return await page.evaluate("""() => {
        const res = []; const seen = new Set();
        document.querySelectorAll('*').forEach(el => {
            if (!Array.from(el.childNodes).some(n => n.nodeName === 'BR')) return;
            const lines = el.innerText.trim().split('\\n').map(l => l.trim()).filter(l => l.length > 1);
            if (lines.length !== 2) return;
            const key = lines[0] + '|' + lines[1];
            if (!seen.has(key)) { seen.add(key); res.push(lines[0] + ' - ' + lines[1]); }
        });
        return res;
    }""")

async def get_quote(container, label):
    try:
        text = await container.locator("div.container_quota").filter(has_text=label).locator(".item--valore").inner_text()
        return float(text.replace(',', '.'))
    except: return None

async def switch_spread(page, container, val):
    try:
        await container.locator("button.spread-btn").click()
        await asyncio.sleep(0.3)
        await page.locator(".btn-group.show .dropdown-item, .spread-item, li").get_by_text(val, exact=True).first.click()
        await asyncio.sleep(0.5)
    except: pass

async def get(context):
    page = await context.new_page()
    leagues = []
    try:
        await page.goto("https://www.planetwin365.it/scommesse/sport/", wait_until="domcontentloaded", timeout=45000)
        await page.click("text=Tutti", timeout=5000)
        await asyncio.sleep(2)
        links = await page.locator("a[href*='/calcio/']").all()
        for link in links:
            url = await link.get_attribute("href")
            name = await link.inner_text()
            if url and "/calcio/" in url and len(name.strip()) > 2:
                full_url = "https://www.planetwin365.it" + url if url.startswith("/") else url
                leagues.append({"name": name.strip(), "url": full_url})
    except: pass
    finally: await page.close()
    unique = {l['url']: l for l in leagues}.values()
    return list(unique)

async def scrape_league(context, league, sem):
    async with sem:
        res = []
        page = await context.new_page()
        try:
            await page.goto(league["url"], wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector("app-scommesse-spread-layout", timeout=10000)
            matches = await get_match_names(page)
            containers = await page.locator("app-scommesse-spread-layout").all()
            for i in range(len(containers)):
                c = page.locator("app-scommesse-spread-layout").nth(i)
                name = matches[i] if i < len(matches) else "N/D"
                try:
                    u25, o25 = await get_quote(c, "U"), await get_quote(c, "O")
                    await switch_spread(page, c, "1.5")
                    u15, o15 = await get_quote(c, "U"), await get_quote(c, "O")
                    if any(q is not None for q in [u25, o25, u15, o15]):
                        res.append({"id": i, "league": league["name"], "match": name, "under_15": u15, "under_25": u25, "over_15": o15, "over_25": o25})
                except: continue
        except: pass
        finally: await page.close()
        return res

async def run_scraper():
    exe = get_chromium_path()
    if not exe: return [{"error": "Browser non trovato"}]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=exe, args=["--headless=new", "--disable-blink-features=AutomationControlled"])
        #browser = await p.chromium.launch(headless=False, executable_path=exe, args=["--disable-blink-features=AutomationControlled"])
        #debug!!
        ctx = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        leagues = await get(ctx)
        sem = asyncio.Semaphore(5)
        tasks = [scrape_league(ctx, l, sem) for l in leagues]
        nested = await asyncio.gather(*tasks)
        await browser.close()
        return [item for sub in nested for item in sub]

@app.route('/')
def index(): return render_template('index.html')

@app.route('/start-scrape')
def start_scrape():
    data = asyncio.run(run_scraper())
    return jsonify(data)

@app.route('/ping')
def ping():
    return "ok"

def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8080")

def monitor():
    while True:
        time.sleep(5)
        if time.time() - last_request_time > 300:
            os._exit(0) # dopo 5 minuti di inattività chiude tutto

if __name__ == "__main__":
    ensure_chromium()
    threading.Thread(target=open_browser, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    serve(app, host='127.0.0.1', port=8080, threads=8)
