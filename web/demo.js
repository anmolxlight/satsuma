// Simulated Satsuma wheel: drag a sample file, switch wheels with Shift/Ctrl/Alt, pick a slice.
const FILES = {
  "holiday.png": { label: "PNG", convert: ["JPG", "WEBP", "HEIC", "AVIF", "TIFF", "GIF", "PDF", "ICO"],
    tools: ["Compress", "Resize", "Crop", "Rotate", "Flip", "Grayscale", "Strip metadata", "To PDF"] },
  "interview.mp4": { label: "MP4", convert: ["MOV", "MKV", "WEBM", "GIF", "MP3", "M4A"],
    tools: ["Compress", "Trim", "Crop", "Resize", "Extract audio", "Mute", "To GIF", "Speed", "Normalize"] },
  "q3-report.pdf": { label: "PDF", convert: ["DOCX", "ODT", "PPTX", "XLSX", "JPG", "PNG", "TXT", "MD", "HTML", "EPUB"],
    tools: ["Compress", "Split", "Crop", "Rotate", "Grayscale", "Encrypt", "To images"] },
};
const ACTIONS = ["Copy", "Copy path", "Move to…", "Show in folder", "Terminal", "Trash", "Float"];
const MODES = ["Convert formats", "File tools", "File actions"];
const KEYMODE = { Shift: 0, Control: 1, Alt: 2 };
const NS = "http://www.w3.org/2000/svg";
const C = 200, R = 178, r = 80;

const svg = document.getElementById("wheel");
const card = document.querySelector(".card");
const caption = document.getElementById("caption");
const modeCaption = document.getElementById("mode-caption");
const keys = [...document.querySelectorAll(".key")];
const fileBtns = [...document.querySelectorAll(".file")];
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const S = { file: null, mode: 0, hover: -1, busy: false };

const el = (tag, attrs = {}, parent = svg) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent.appendChild(e);
  return e;
};
const pt = (rad, a) => `${(C + rad * Math.cos(a)).toFixed(2)} ${(C + rad * Math.sin(a)).toFixed(2)}`;

function items() {
  if (!S.file) return [];
  const f = FILES[S.file];
  if (S.mode === 0) return f.convert.map((x) => [x, `Convert to ${x}`]);
  if (S.mode === 1) return f.tools.map((x) => [x, x]);
  return ACTIONS.map((x) => [x, x]);
}

function render(animate = false) {
  svg.innerHTML = "";
  const defs = el("defs");
  const g = el("radialGradient", { id: "shine", cx: C, cy: C, r: R, gradientUnits: "userSpaceOnUse" }, defs);
  el("stop", { offset: "45%", "stop-color": "#ebecec" }, g);
  el("stop", { offset: "100%", "stop-color": "#fbfbfb" }, g);
  el("circle", { cx: C, cy: C, r: R + 12, fill: "#ecedeb", stroke: "#dfe0dd" });
  const list = items();
  svg.removeAttribute("aria-activedescendant");
  if (!S.file) {
    el("circle", { cx: C, cy: C, r: R - 4, fill: "#fbfbfa" });
    el("circle", { cx: C, cy: C, r: R - 18, fill: "none", stroke: "#cfcfcb", "stroke-dasharray": "5 6" });
    const t = el("text", { x: C, y: C - 4, "text-anchor": "middle", "font-size": 20, fill: "#141414" });
    t.textContent = "Drop a file";
    const s = el("text", { x: C, y: C + 22, "text-anchor": "middle", "font-size": 12, fill: "#777", "font-weight": 400 });
    s.textContent = "or pick one above";
  }
  const n = list.length, step = (2 * Math.PI) / Math.max(n, 1), gap = 7 / R;
  list.forEach(([label, cap], i) => {
    const a0 = -Math.PI / 2 - step / 2 + i * step + gap, a1 = a0 + step - 2 * gap;
    const ri = r + 10, ro = R - 6, gi = (7 / ri) - gap;
    const big = a1 - a0 > Math.PI ? 1 : 0;
    const d = `M ${pt(ro, a0)} A ${ro} ${ro} 0 ${big} 1 ${pt(ro, a1)} L ${pt(ri, a1 - gi)} A ${ri} ${ri} 0 ${big} 0 ${pt(ri, a0 + gi)} Z`;
    const on = i === S.hover;
    const p = el("path", { d, class: "seg", id: `seg-${i}`, role: "option", "aria-label": cap, "aria-selected": on,
      fill: on ? "#fd5400" : "url(#shine)", stroke: on ? "#fd5400" : "url(#shine)", "stroke-width": 12, "stroke-linejoin": "round" });
    p.addEventListener("pointerenter", () => setHover(i));
    p.addEventListener("click", () => apply(i));
    const am = -Math.PI / 2 + i * step, rm = (ri + ro) / 2;
    const words = label.length > 9 && label.includes(" ") ? label.split(" ") : [label];
    words.forEach((w, j) => {
      const t = el("text", { x: C + rm * Math.cos(am), y: C + rm * Math.sin(am) + 5 + (j - (words.length - 1) / 2) * 15,
        "text-anchor": "middle", "font-size": S.mode === 0 ? 15 : 13, fill: on ? "#fff" : "#141414" });
      t.textContent = w;
    });
  });
  if (S.file) {
    el("circle", { cx: C, cy: C, r, fill: "#f6f6f5" });
    el("rect", { x: C - 44, y: C - 18, width: 88, height: 36, rx: 18, fill: "#fff" });
    const t = el("text", { x: C, y: C + 5, "text-anchor": "middle", "font-size": 13, fill: "#141414", "font-weight": 500 });
    t.textContent = S.busy ? "…" : FILES[S.file].label;
  }
  if (S.hover >= 0) svg.setAttribute("aria-activedescendant", `seg-${S.hover}`);
  if (animate && !reduced) {
    svg.classList.remove("open");
    void svg.getBoundingClientRect();
    svg.classList.add("open");
  }
}

function setHover(i) {
  if (S.busy || i === S.hover) return;
  S.hover = i;
  render();
  const it = items()[i];
  caption.textContent = it ? it[1] : "";
}

function setMode(m) {
  S.mode = ((m % 3) + 3) % 3;
  S.hover = -1;
  keys.forEach((k, i) => { k.classList.toggle("on", i === S.mode); k.setAttribute("aria-pressed", i === S.mode); });
  modeCaption.textContent = MODES[S.mode];
  render(true);
}

function load(name) {
  S.file = name;
  S.hover = -1;
  fileBtns.forEach((b) => b.classList.toggle("active", b.dataset.file === name));
  caption.textContent = "Pick a slice: hover, or use the arrow keys and Enter";
  render(true);
}

function outName(label) {
  const base = S.file.replace(/\.[^.]+$/, ""), ext = S.file.split(".").pop();
  if (S.mode === 0) return ["JPG", "PNG"].includes(label) && ext === "pdf" ? `${base} pages/` : `${base}.${label.toLowerCase()}`;
  return `${base} ${label.toLowerCase().replace(/[^a-z]+/g, "-").replace(/-$/, "")}.${ext}`;
}

function apply(i) {
  const it = items()[i];
  if (!it || S.busy) return;
  if (S.mode === 2) { caption.textContent = `${it[0]}: done`; return; }
  S.busy = true;
  render();
  caption.textContent = `${it[1]}…`;
  const ring = el("circle", { cx: C, cy: C, r: R + 9, fill: "none", stroke: "#fd5400", "stroke-width": 5,
    "stroke-linecap": "round", transform: `rotate(-90 ${C} ${C})`, "stroke-dasharray": `0 ${2 * Math.PI * (R + 9)}` });
  const total = 2 * Math.PI * (R + 9), t0 = performance.now(), dur = reduced ? 1 : 1100;
  const tick = (now) => {
    const p = Math.min(1, (now - t0) / dur);
    ring.setAttribute("stroke-dasharray", `${p * total} ${total}`);
    if (p < 1) return requestAnimationFrame(tick);
    S.busy = false;
    S.hover = i;
    render();
    caption.textContent = `✓ ${outName(it[0])} saved next to the original`;
  };
  requestAnimationFrame(tick);
}

function hitTest(x, y) {
  const b = svg.getBoundingClientRect(), s = 400 / b.width;
  const dx = (x - b.left) * s - C, dy = (y - b.top) * s - C, d = Math.hypot(dx, dy), n = items().length;
  if (!n || d < r || d > R) return -1;
  const a = (Math.atan2(dy, dx) + Math.PI / 2 + Math.PI / n + 4 * Math.PI) % (2 * Math.PI);
  return Math.floor(a / ((2 * Math.PI) / n));
}

fileBtns.forEach((b) => {
  b.addEventListener("click", () => load(b.dataset.file));
  b.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", b.dataset.file); e.dataTransfer.effectAllowed = "copy"; });
});
card.addEventListener("dragover", (e) => {
  e.preventDefault();
  card.classList.add("drag");
  const m = e.shiftKey ? 0 : e.ctrlKey ? 1 : e.altKey ? 2 : S.mode;
  if (m !== S.mode) setMode(m);
  if (S.file) setHover(hitTest(e.clientX, e.clientY));
});
card.addEventListener("dragleave", () => card.classList.remove("drag"));
card.addEventListener("drop", (e) => {
  e.preventDefault();
  card.classList.remove("drag");
  const name = e.dataTransfer.getData("text/plain");
  if (!FILES[name]) return;
  const had = S.file === name;
  if (!had) load(name);
  const i = hitTest(e.clientX, e.clientY);
  if (had && i >= 0) apply(i); // dropped straight onto a slice: zero clicks
});
keys.forEach((k) => k.addEventListener("click", () => setMode(+k.dataset.mode)));
svg.addEventListener("pointerleave", () => { if (!S.busy) { S.hover = -1; render(); } });
svg.addEventListener("keydown", (e) => {
  const n = items().length;
  if (e.key in KEYMODE) { setMode(KEYMODE[e.key]); return; }
  if (!S.file) { if (e.key === "Enter" || e.key === " ") { load("holiday.png"); e.preventDefault(); } return; }
  if (["ArrowRight", "ArrowDown"].includes(e.key)) setHover((S.hover + 1 + n) % n);
  else if (["ArrowLeft", "ArrowUp"].includes(e.key)) setHover(S.hover < 0 ? n - 1 : (S.hover - 1 + n) % n);
  else if (e.key === "Enter" || e.key === " ") apply(Math.max(S.hover, 0));
  else if (e.key === "Escape") { S.file = null; fileBtns.forEach((b) => b.classList.remove("active")); caption.textContent = "Drag a sample file onto the wheel"; render(true); }
  else return;
  e.preventDefault();
});

document.getElementById("copy").addEventListener("click", async (e) => {
  try {
    await navigator.clipboard.writeText(document.getElementById("oneliner").textContent);
    e.target.textContent = "Copied";
  } catch { e.target.textContent = "Select and copy above"; }
  setTimeout(() => (e.target.textContent = "Copy command"), 1800);
});

render();
