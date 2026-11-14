#!/usr/bin/env node
/*
 * Urdu Nastaliq text → PNG, rendered by Chromium (Playwright).
 *
 * Why: Nastaliq needs very complex text shaping. Browsers do it perfectly;
 * some FFmpeg/libass builds show empty boxes instead.
 *
 * Usage:  node pipeline/urdu_text_render.js spec.json
 *
 * Mode 1 — single image (font test):
 *   { "out": "a.png", "width": 1920, "height": 1080, "fontPath": "...ttf",
 *     "fontSize": 72, "background": "#1d2433" | "transparent", "lines": ["...", "..."] }
 *
 * Mode 2 — subtitle frames (many images, one browser session):
 *   { "width": 1080, "height": 1920, "fontPath": "...ttf", "background": "transparent",
 *     "style": { "fontSize": 80, "color": "#fff", "highlight": "#FFD60A", "outline": "#000",
 *                "box": false, "bottom": 600, "maxWidth": 900 },
 *     "items": [ { "out": "f0001.png", "words": ["آج", "ہم"], "highlight": 0 }, ... ] }
 */
const fs = require("fs");
const path = require("path");

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (e) {
  console.error("Playwright nahi mila. Install: npm install && npm run setup-browser");
  process.exit(2);
}

const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

(async () => {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const transparent = spec.background === "transparent";
  // Embed the font directly (a page made with setContent may not load file:// URLs).
  const fontUrl = "data:font/ttf;base64," + fs.readFileSync(path.resolve(spec.fontPath)).toString("base64");
  const st = Object.assign({ fontSize: spec.fontSize || 72, color: "#ffffff", highlight: "#FFD60A",
                             outline: "#000000", box: false, bottom: null, maxWidth: spec.width - 160 }, spec.style || {});
  const stroke = Math.max(2, Math.round(st.fontSize / 14));
  const html = `<!doctype html><html lang="ur" dir="rtl"><head><meta charset="utf-8"><style>
@font-face{font-family:"UrduNastaliq";src:url("${fontUrl}") format("truetype")}
html,body{margin:0;width:${spec.width}px;height:${spec.height}px;overflow:hidden;
  background:${transparent ? "transparent" : spec.background || "#000"}}
#stage{position:absolute;left:0;right:0;display:flex;flex-direction:column;align-items:center;
  ${st.bottom == null ? "top:0;bottom:0;justify-content:center;" : `bottom:${st.bottom}px;`}
  gap:${Math.round(st.fontSize * 0.6)}px}
p{margin:0;max-width:${st.maxWidth}px;font-family:"UrduNastaliq",sans-serif;font-size:${st.fontSize}px;
  line-height:1.85;color:${st.color};direction:rtl;unicode-bidi:plaintext;text-align:center;
  paint-order:stroke fill;-webkit-text-stroke:${stroke}px ${st.outline};
  text-shadow:0 ${stroke}px ${stroke * 2}px rgba(0,0,0,.65);
  ${st.box ? `background:rgba(0,0,0,.55);padding:0 ${Math.round(st.fontSize * 0.35)}px;border-radius:${Math.round(st.fontSize * 0.2)}px;
  -webkit-box-decoration-break:clone;box-decoration-break:clone;` : ""}}
.hl{color:${st.highlight}}
</style></head><body><div id="stage"></div></body></html>`;

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: spec.width, height: spec.height }, deviceScaleFactor: 1 });
    await page.setContent(html, { waitUntil: "load" });
    const ok = await page.evaluate(async () => {
      await document.fonts.load('72px "UrduNastaliq"', "اردو");
      return [...document.fonts].some((f) => f.family.replace(/"/g, "") === "UrduNastaliq" && f.status === "loaded");
    });
    if (!ok) throw new Error("Urdu font load nahi hua: " + spec.fontPath);

    const items = spec.items || [{ out: spec.out, lines: spec.lines || [] }];
    for (const it of items) {
      let inner;
      if (it.words) {
        inner = "<p>" + it.words.map((w, i) => (i === it.highlight ? `<span class="hl">${esc(w)}</span>` : esc(w))).join(" ") + "</p>";
      } else {
        inner = (it.lines || []).map((l) => `<p>${esc(l)}</p>`).join("");
      }
      await page.evaluate((h) => { document.getElementById("stage").innerHTML = h; }, inner);
      await page.screenshot({ path: it.out, omitBackground: transparent });
    }
    console.log(`${items.length} image(s)`);
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(String(e && e.message ? e.message : e));
  process.exit(1);
});
