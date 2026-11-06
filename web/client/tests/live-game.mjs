// Live end-to-end check: a real browser plays a full game through web/bridge.py against a
// Python bot on the real TCP server. Start the stack first (see web/README.md), then:
//   node tests/live-game.mjs http://127.0.0.1:8091 [--mobile]
// Prints JSON: screens reached, ticks seen, RTT, how the browser player moved, browser errors.
import { chromium, devices } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const url = process.argv[2] ?? 'http://127.0.0.1:8091';
const mobile = process.argv.includes('--mobile');
const out = `artifacts/live${mobile ? '-mobile' : ''}`;
await mkdir(out, { recursive: true });

const browser = await chromium.launch({ channel: 'chromium' });
const context = await browser.newContext(mobile ? { ...devices['iPhone 13'] } : { viewport: { width: 1280, height: 720 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
page.on('console', (m) => m.type() === 'error' && errors.push(`console: ${m.text()}`));

const diag = () => page.evaluate(() => window.__THREE_GAME_DIAGNOSTICS__);
const result = { mobile, screens: [], errors };

await page.goto(url);
  const room = process.env.ROOM; if (room) { await page.click('details summary'); await page.fill('#room-input', room); }
await page.fill('#name-input', mobile ? 'phone' : 'browser');
await page.click('#play-btn');
await page.waitForSelector('#screen-room:not([hidden])', { timeout: 8000 });
result.screens.push('room');
await page.click('#ready-btn');

await page.waitForSelector('#hud:not([hidden])', { timeout: 20000 });
result.screens.push('game');
const start = await diag();

// Steer: on desktop with arrow keys, on the phone by tapping the d-pad. Cycle directions so
// the player actually travels through corridors.
const dirs = ['RIGHT', 'DOWN', 'LEFT', 'UP'];
const keys = { UP: 'ArrowUp', DOWN: 'ArrowDown', LEFT: 'ArrowLeft', RIGHT: 'ArrowRight' };
const positions = [];
for (let i = 0; i < 24; i += 1) {
  const dir = dirs[Math.floor(i / 3) % 4];
  if (mobile) await page.tap(`#dpad [data-dir="${dir}"]`);
  else await page.keyboard.press(keys[dir]);
  await page.waitForTimeout(250);
  const d = await diag();
  positions.push([+d.player.position.x.toFixed(2), +d.player.position.z.toFixed(2)]);
  if (i === 8) await page.screenshot({ path: `${out}/mid-game.png` });
}
const mid = await diag();

await page.waitForSelector('#screen-over:not([hidden])', { timeout: 160000 });
result.screens.push('over');
await page.screenshot({ path: `${out}/game-over.png` });
result.overTitle = await page.textContent('#over-title');
result.ranking = await page.$$eval('#over-ranking li', (lis) => lis.map((li) => li.textContent.trim()));
result.ticks = { atStart: start.tick, mid: mid.tick };
result.rttMs = mid.rttMs;
result.distinctPositions = new Set(positions.map((p) => p.join(','))).size;
result.renderer = mid.renderer;

// Play again: READY from the game-over screen returns to the room.
await page.click('#again-btn');
await page.waitForSelector('#screen-room:not([hidden])', { timeout: 5000 });
result.screens.push('room-again');

console.log(JSON.stringify(result, null, 2));
await browser.close();
process.exit(errors.length ? 1 : 0);
