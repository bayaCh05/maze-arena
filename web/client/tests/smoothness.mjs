// Smoothness check: play through a link, sample your chomper's position every animation
// frame for a few seconds while steering, and report its per-frame speed (cells/s).
// Smooth = steady ~10 cells/s while running, few stall frames, no jumps.
//   ROOM=x node tests/smoothness.mjs https://...trycloudflare.com
import { chromium } from '@playwright/test';

const url = process.argv[2] ?? 'http://127.0.0.1:8080';
const browser = await chromium.launch({ channel: 'chromium' });
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto(url);
if (process.env.ROOM) { await page.click('details summary'); await page.fill('#room-input', process.env.ROOM); }
await page.fill('#name-input', 'smooth');
await page.click('#play-btn');
await page.waitForSelector('#screen-room:not([hidden])', { timeout: 8000 });
await page.click('#ready-btn');
await page.waitForSelector('#hud:not([hidden])', { timeout: 20000 });

// Steer around in the background while sampling.
const keys = ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'];
let k = 0;
const steer = setInterval(() => page.keyboard.press(keys[k++ % 4]).catch(() => {}), 700);
const samples = await page.evaluate(() => new Promise((resolve) => {
  const out = [];
  const t0 = performance.now();
  const step = (t) => {
    const d = window.__THREE_GAME_DIAGNOSTICS__;
    out.push([t, d.player.position.x, d.player.position.z, d.bufferMs]);
    if (t - t0 < 8000) requestAnimationFrame(step); else resolve(out);
  };
  requestAnimationFrame(step);
}));
clearInterval(steer);

const speeds = [];
let respawns = 0, glitches = 0;
for (let i = 1; i < samples.length; i += 1) {
  const dt = (samples[i][0] - samples[i - 1][0]) / 1000;
  if (dt <= 0) continue;
  const dist = Math.hypot(samples[i][1] - samples[i - 1][1], samples[i][2] - samples[i - 1][2]);
  if (dist > 1.5) { respawns += 1; continue; } // eaten -> snapped to spawn (correct)
  if (dist > 0.4) glitches += 1; // a visible teleport of half a cell or more in one frame
  speeds.push(dist / dt);
}
// Frames inside a running stretch: both neighbours moving. Count stalls (speed ~0) there.
let running = 0, stalls = 0;
for (let i = 1; i < speeds.length - 1; i += 1) {
  if (speeds[i - 1] > 3 && speeds[i + 1] > 3) { running += 1; if (speeds[i] < 1) stalls += 1; }
}
const moving = speeds.filter((s) => s > 1).sort((a, b) => a - b);
const q = (p) => +(moving[Math.floor(p * (moving.length - 1))] ?? 0).toFixed(2);
console.log(JSON.stringify({
  frames: samples.length, movingFrames: moving.length,
  speed: { p10: q(0.1), p50: q(0.5), p90: q(0.9), max: q(1) },
  respawns, glitches,
  stallsWhileRunning: `${stalls}/${running}`,
  bufferMs: samples[samples.length - 1][3], errors,
}));
await browser.close();
