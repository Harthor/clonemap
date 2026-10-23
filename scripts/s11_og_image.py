"""Etapa 11: imagen de vista previa (Open Graph, 1200×630) para LinkedIn / redes, en site/og.png.

Arma una plantilla HTML con el estilo de la página (misma tipografía del sistema, fondo claro, un acento) a partir de
site/data.json y la captura con Chrome headless por el DevTools Protocol, a 1200×630 exactos.
Requiere Google Chrome instalado (ruta en config: site.chrome).
Uso: uv run scripts/s11_og_image.py
"""
import asyncio
import base64
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

from common import ROOT, load_config

cfg = load_config()
S = cfg["site"]
W, H, PORT = 1200, 630, 9334
data = json.loads((ROOT / "site" / "data.json").read_text())
h = data["headline"]

TEMPLATE = f"""<!doctype html><html><head><meta charset="utf-8"><style>
:root {{ --bg: #fafaf8; --fg: #1b1b19; --muted: #6a6963; --line: #e5e3dd; --accent: #1f5fae;
        --sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }}
* {{ box-sizing: border-box; margin: 0; }}
html, body {{ width: {W}px; height: {H}px; background: var(--bg); color: var(--fg); font-family: var(--sans); }}
body {{ padding: 64px 80px 56px; display: flex; flex-direction: column; }}
.claim {{ font-size: 40px; line-height: 1.2; font-weight: 600; letter-spacing: -0.01em; }}
.nums {{ display: flex; gap: 72px; margin-top: 44px; }}
.num b {{ display: block; font-size: 168px; line-height: 0.95; font-weight: 800; letter-spacing: -0.04em; }}
.num span {{ display: block; margin-top: 14px; font-size: 30px; color: var(--muted); }}
.num.main b {{ color: var(--accent); }}
.num.ctrl b {{ color: #8a8880; }}
.foot {{ margin-top: auto; padding-top: 22px; border-top: 2px solid var(--line); display: flex; justify-content: space-between;
        align-items: baseline; font-size: 24px; color: var(--muted); }}
.foot b {{ color: var(--fg); font-weight: 700; }}
</style></head><body>
<div class="claim">Write their own parser for the JSON an AI model returns</div>
<div class="nums">
  <div class="num main"><b>{round(h['pct_domain'])}%</b><span>of LLM apps</span></div>
  <div class="num ctrl"><b>{round(h['pct_control'])}%</b><span>of regular Python projects</span></div>
</div>
<div class="foot"><b>clonemap</b><span>{sum(data['run']['repos'].values()):,} GitHub projects analyzed</span></div>
</body></html>"""


async def capture(ws_url: str, page_url: str, out: Path):
    async with websockets.connect(ws_url, max_size=2**26) as ws:
        n = 0

        async def cmd(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == n:
                    return m.get("result", {})

        await cmd("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
        await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
        await cmd("Page.enable")
        await cmd("Page.navigate", url=page_url)
        await asyncio.sleep(1.5)
        res = await cmd("Page.captureScreenshot", format="png", clip={"x": 0, "y": 0, "width": W, "height": H, "scale": 1})
        out.write_bytes(base64.b64decode(res["data"]))


def main():
    out = ROOT / "site" / "og.png"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tpl = Path(tmp) / "og.html"
        tpl.write_text(TEMPLATE)
        proc = subprocess.Popen([S["chrome"], "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                 f"--user-data-dir={tmp}/profile", f"--remote-debugging-port={PORT}", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
                    break
                except OSError:
                    time.sleep(0.2)
            target = json.loads(urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")).read())
            asyncio.run(capture(target["webSocketDebuggerUrl"], tpl.as_uri(), out))
        finally:
            proc.terminate()
            proc.wait(timeout=10)  # que Chrome suelte el perfil antes de borrar la carpeta temporal
    print(f"escrito {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
