#!/usr/bin/env node
/*
 * Urdu Nastaliq text → PNG, rendered by Chromium (Playwright).
 *
 * Why: Nastaliq needs very complex text shaping. Browsers do it perfectly;
 * some FFmpeg/libass builds show empty boxes instead. Phase 3 will use this
 * to make subtitle images (transparent PNG) that FFmpeg overlays on video.
 *
 * Usage:  node pipeline/urdu_text_render.js spec.json
 * spec = {
 *   "out": "file.png", "width": 1920, "height": 1080,
 *   "fontPath": "/abs/path/NotoNastaliqUrdu-Regular.ttf",
 *   "fontSize": 72, "color": "#ffffff", "outline": "#000000",
 *   "background": "#1d2433" | "transparent",
 *   "lines": ["...", "..."]
 * }
 */
const fs = require("fs");
const path = require("path");

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (e) {
  console.error("Playwright nahi mila. Install: npm install playwright && npx playwright install chromium");
  process.exit(2);
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

(async () => {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const transparent = spec.background === "transparent";
  // Embed the font directly (a page made with setContent may not load file:// URLs).
  const fontUrl = "data:font/ttf;base64," + fs.readFileSync(path.resolve(spec.fontPath)).toString("base64");
  const o = spec.outline || "#000";
  const w = Math.max(2, Math.round((spec.fontSize || 72) / 16));
  const html = `<!doctype html><html lang="ur" dir="rtl"><head><meta charset="utf-8"><style>
@font-face{font-family:"UrduNastaliq";src:url("${fontUrl}") format("truetype")}
html,body{margin:0;width:${spec.width}px;height:${spec.height}px;background:${transparent ? "transparent" : spec.background || "#000"}}
body{display:flex;flex-direction:column;justify-content:center;align-items:center;gap:${Math.round((spec.fontSize || 72) * 0.6)}px}
p{margin:0;font-family:"UrduNastaliq",sans-serif;font-size:${spec.fontSize || 72}px;line-height:1.9;color:${spec.color || "#fff"};
  direction:rtl;unicode-bidi:plaintext;text-align:center;paint-order:stroke fill;-webkit-text-stroke:${w}px ${o};
  text-shadow:0 ${w}px ${w * 2}px rgba(0,0,0,.6)}
</style></head><body>${(spec.lines || []).map((l) => `<p>${esc(l)}</p>`).join("")}</body></html>`;

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: spec.width, height: spec.height }, deviceScaleFactor: 1 });
    await page.setContent(html, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    const ok = await page.evaluate(async () => {
      await document.fonts.load('72px "UrduNastaliq"', "اردو");
      return [...document.fonts].some((f) => f.family.replace(/"/g, "") === "UrduNastaliq" && f.status === "loaded");
    });
    if (!ok) throw new Error("Urdu font load nahi hua: " + spec.fontPath);
    await page.screenshot({ path: spec.out, omitBackground: transparent });
    console.log(spec.out);
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(String(e && e.message ? e.message : e));
  process.exit(1);
});
