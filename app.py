import multiprocessing
multiprocessing.freeze_support()

import sys
import os

def _single_instance_or_exit():
    if sys.platform != "win32":
        return
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, "Global\\AppScraperSingleInstance")
    if ctypes.get_last_error() == 183:
        sys.exit(0)
    _single_instance_or_exit._mutex_handle = handle

_single_instance_or_exit()

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
from flask import Flask, render_template, jsonify
from playwright.async_api import async_playwright
from waitress import serve


# da prendere nel browsers.json di playwright https://github.com/microsoft/playwright/blob/main/packages/playwright-core/browsers.json
CHROMIUM_DOWNLOAD_URL = (
    "https://www.googleapis.com/download/storage/v1/b/chromium-browser-snapshots/o/Win_x64%2F1551223%2Fchrome-win.zip?alt=media"
)


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
        tk.Label(self.root, textvariable=self._status_var, bg="#0f0f0f", fg="#888888",
                 font=("Helvetica", 10)).pack()
        self._progress_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self._progress_var, bg="#0f0f0f", fg="#4f9ef8",
                 font=("Helvetica", 9)).pack()
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
        ssl._create_default_https_context = ssl._create_unverified_context #contesto ssl di default
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


app = Flask(__name__,
            template_folder=resource_path('templates'),
            static_folder=resource_path('static'))

LEAGUES = [
    {"name": "Serie A",      "url": "https://www.planetwin365.it/scommesse/sport/calcio/italia/serie-a?did=1&nid=1577&eid=93"},
    {"name": "Serie B",      "url": "https://www.planetwin365.it/scommesse/sport/calcio/italia/serie-b?did=1&nid=1577&eid=1626630"},
    {"name": "Coppa Italia", "url": "https://www.planetwin365.it/scommesse/sport/calcio/italia/coppa-italia?did=1&nid=1577&eid=9683"},
]


async def get_match_names(page):
    return await page.evaluate("""() => {
        const results = [];
        const seen = new Set();
        document.querySelectorAll('*').forEach(el => {
            if (!Array.from(el.childNodes).some(n => n.nodeName === 'BR')) return;
            const lines = el.innerText.trim().split('\\n').map(l => l.trim()).filter(l => l.length > 1);
            if (lines.length !== 2) return;
            const key = lines[0] + '|' + lines[1];
            if (!seen.has(key)) {
                seen.add(key);
                results.push(lines[0] + ' - ' + lines[1]);
            }
        });
        return results;
    }""")

async def get_quote(container, label):
    try:
        text = await container.locator("div.container_quota").filter(has_text=label).locator(".item--valore").inner_text()
        return float(text.replace(',', '.'))
    except:
        return None

async def switch_spread(page, container, value):
    try:
        dropdown = container.locator("button.spread-btn")
        await dropdown.click()
        await asyncio.sleep(0.3)
        await page.locator(".btn-group.show .dropdown-item, .spread-item, li").get_by_text(value, exact=True).first.click()
        await asyncio.sleep(0.5)
    except:
        pass

async def run_scraper():
    chromium_exe = get_chromium_path()
    if not chromium_exe:
        return [{"error": "Chromium non trovato. Riavvia l'applicazione."}]

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=chromium_exe)
        for league in LEAGUES:
            page = await browser.new_page()
            try:
                await page.goto(league["url"], wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_selector("app-scommesse-spread-layout", timeout=15000)
                match_names = await get_match_names(page)
                items = await page.locator("app-scommesse-spread-layout").all()
                for i in range(len(items)):
                    container = page.locator("app-scommesse-spread-layout").nth(i)
                    match_name = match_names[i] if i < len(match_names) else "N/D"
                    try:
                        under_25 = await get_quote(container, "U")
                        over_25  = await get_quote(container, "O")
                        await switch_spread(page, container, "1.5")
                        under_15 = await get_quote(container, "U")
                        over_15  = await get_quote(container, "O")
                        await switch_spread(page, container, "2.5")
                        if (any(q is not None and q < 2.5 for q in [under_15, under_25]) and
                                any(q is not None and q > 1.5 for q in [over_15, over_25])):
                            results.append({
                                "id": i + 1, "league": league["name"], "match": match_name,
                                "under_15": under_15, "under_25": under_25,
                                "over_15": over_15,  "over_25": over_25,
                            })
                    except:
                        continue
            except:
                continue
            finally:
                await page.close()
        await browser.close()
    return results


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start-scrape')
def start_scrape():
    data = asyncio.run(run_scraper())
    return jsonify(data)

def open_browser():
    webbrowser.open_new("http://127.0.0.1:8080")


if __name__ == "__main__":
    ensure_chromium()
    threading.Thread(target=open_browser, daemon=True).start()
    serve(app, host='127.0.0.1', port=8080, threads=6)
