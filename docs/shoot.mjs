// Screenshot a broadway session with headless Chromium over the DevTools protocol.
// node shoot.mjs URL OUT.png WAIT_MS [W H]   (CHROME=/path/to/chrome)
import { spawn } from "node:child_process";
const [url, out, wait = "2500", W = "520", H = "700"] = process.argv.slice(2);
const chrome = process.env.CHROME;
const port = 9300 + Math.floor(Math.random() * 500);
const p = spawn(chrome, ["--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
  `--remote-debugging-port=${port}`, `--window-size=${W},${H}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = {};
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (pending[d.id]) { pending[d.id](d); delete pending[d.id]; } };
const send = (method, params = {}) => new Promise((r) => { pending[++id] = r; ws.send(JSON.stringify({ id, method, params })); });
await send("Emulation.setDeviceMetricsOverride", { width: +W, height: +H, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url });
await sleep(+wait);
const shot = await send("Page.captureScreenshot", { format: "png" });
(await import("node:fs")).writeFileSync(out, Buffer.from(shot.result.data, "base64"));
ws.close(); p.kill();
console.log("wrote", out);
