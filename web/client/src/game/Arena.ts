import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { Chomper } from '../assets/Chomper';
import type { MaterialLibrary } from '../assets/Materials';
import { MazeKit } from '../assets/MazeKit';
import type { GameStart, GameState } from '../net/protocol';
import { PLAYER_COLORS } from '../net/protocol';
import { Trails } from '../systems/Trails';
import type { Vfx } from '../systems/Vfx';

/** What changed when playback reached a STATE, for sound, HUD and camera feedback. */
export interface StateEvents {
  state: GameState;
  pelletsEaten: { cell: string; byYou: boolean }[];
  powerEaten: { cell: string; byYou: boolean }[];
  eaten: string[]; // players who jumped back to their spawn (eaten by a powered rival)
  scored: Record<string, number>; // score change per player since the previous STATE
}

interface Track {
  chomper: Chomper;
  color: THREE.Color;
}

interface Popup {
  obj: CSS2DObject;
  t: number;
}

const MAX_SNAPS = 40;
const MIN_DELAY = 15; // ms of jitter allowance on a clean network (LAN)
const MAX_DELAY = 260; // ms, cap so a bad link never makes control feel too late
const NEON = new THREE.Color('#2160ff');

/**
 * The game world for one GAME_START: maze kit + one chomper per player.
 *
 * Smooth playback (purely cosmetic, positions are always the server's): STATEs reach the
 * browser unevenly over the internet (bunched, then late), so instead of gliding on arrival
 * they go into a small buffer and are played back on a steady clock, one tick per
 * 1000/tick_rate ms, a little behind real time. That delay adapts to the measured jitter:
 * ~15 ms on a LAN, up to MAX_DELAY on a bad link. Between two consecutive STATEs a player
 * glides one cell; any longer jump (eaten -> respawn) is a snap.
 */
export class Arena {
  readonly root = new THREE.Group();
  readonly maze: MazeKit;
  private readonly tracks = new Map<string, Track>();
  private readonly trails = new Trails();
  private readonly snaps: GameState[] = [];
  private readonly arrivals: number[] = []; // now - tick * T, per received STATE
  private readonly popups: Popup[] = [];
  private shown: GameState | null = null; // last STATE playback has reached
  private base: number | null = null; // local time of tick 0 on the fastest path seen
  private delay = 80;
  private renderTick = 0;
  private readonly tickMs: number;
  private readonly tmp = new THREE.Vector3();
  private readonly neonTarget = new THREE.Color();

  constructor(
    readonly setup: GameStart,
    private readonly you: string | null,
    private readonly mats: MaterialLibrary,
    private readonly vfx: Vfx,
  ) {
    this.root.name = 'arena';
    this.maze = new MazeKit(setup.maze, mats);
    this.root.add(this.maze.root, this.trails.mesh);
    this.tickMs = 1000 / setup.tick_rate;
  }

  /** The STATE currently on screen. */
  get current(): GameState | null {
    return this.shown;
  }

  /** Playback delay behind the fastest arrival, ms (diagnostics). */
  get bufferMs(): number {
    return Math.round(this.delay + this.tickMs);
  }

  /** Queue a STATE from the server. Old or duplicate ticks are ignored. */
  push(state: GameState, now: number): void {
    const last = this.snaps[this.snaps.length - 1];
    if (last && state.tick <= last.tick) return;
    this.snaps.push(state);
    if (this.snaps.length > MAX_SNAPS) this.snaps.shift();

    // Clock: base follows the lower envelope of (arrival - tick*T), i.e. the fastest
    // delivery seen, creeping up slowly in case the path itself got slower.
    const sample = now - state.tick * this.tickMs;
    this.arrivals.push(sample);
    if (this.arrivals.length > 50) this.arrivals.shift();
    if (this.base === null || sample < this.base) this.base = sample;
    else this.base += (sample - this.base) * 0.01;

    if (!this.shown) {
      // First STATE: show it at once (players appear on their spawns).
      this.renderTick = state.tick;
      this.reach(state);
    }
  }

  /**
   * Advance playback; returns the events of every STATE reached this frame (usually 0 or 1).
   */
  update(delta: number, elapsed: number, now: number): StateEvents[] {
    const events: StateEvents[] = [];
    this.maze.update(elapsed);
    if (this.base !== null && this.snaps.length) {
      // Jitter allowance: 95th percentile of how late STATEs were, eased so speed stays even.
      const late = this.arrivals.map((a) => a - this.base!).sort((a, b) => a - b);
      const p95 = late[Math.floor((late.length - 1) * 0.95)] ?? 0;
      const target = THREE.MathUtils.clamp(p95 + 10, MIN_DELAY, MAX_DELAY);
      this.delay += (target - this.delay) * Math.min(1, delta * (target > this.delay ? 3 : 0.5));

      const first = this.snaps[0].tick;
      const latest = this.snaps[this.snaps.length - 1].tick;
      const want = (now - this.base - this.delay) / this.tickMs - 1;
      // Play at normal speed, eased up to 2x when behind the target and down when ahead,
      // so catching up after a late STATE is a short sprint, never a teleport.
      const behind = want - this.renderTick;
      const rate = THREE.MathUtils.clamp(1 + behind * 0.9, 0.25, 2);
      this.renderTick += ((delta * 1000) / this.tickMs) * rate;
      // Never run past what has arrived (wait there instead).
      this.renderTick = THREE.MathUtils.clamp(this.renderTick, first, latest);
      // Way behind (tab was in the background): jump close to live.
      if (behind > 8 || latest - this.renderTick > 12) this.renderTick = Math.max(first, Math.min(latest, want));

      for (const s of this.snaps) {
        if (s.tick > Math.floor(this.renderTick)) break;
        if (this.shown && s.tick <= this.shown.tick) continue;
        events.push(this.reach(s));
      }
      this.place();
    }
    this.tintNeon(elapsed, delta);

    const powered = this.shown?.powered ?? {};
    for (const [name, track] of this.tracks) {
      const power = powered[name] ?? 0;
      const rivalPowered = Object.entries(powered).some(([n, p]) => n !== name && p > 0);
      track.chomper.update(delta, elapsed, power, rivalPowered && power === 0);
      this.trails.follow(name, track.chomper.root.position, track.color);
    }
    this.trails.update(delta);
    this.updatePopups(delta);
    return events;
  }

  /** Show the arrow of the direction just pressed on your chomper, before the server acts. */
  intent(dx: number, dz: number): void {
    if (this.you) this.tracks.get(this.you)?.chomper.setIntent(dx, dz);
  }

  /** World position of a player's chomper (for diagnostics), or null. */
  positionOf(name: string | null): THREE.Vector3 | null {
    if (!name) return null;
    return this.tracks.get(name)?.chomper.root.position ?? null;
  }

  /** Floating text above a player ("+10", "x5"), rises and fades. */
  popup(name: string, text: string, kind: 'gain' | 'loss' | 'streak' = 'gain'): void {
    const track = this.tracks.get(name);
    if (!track || this.popups.length > 14) return;
    const el = document.createElement('div');
    el.className = `popup ${kind}`;
    el.textContent = text;
    el.style.setProperty('--player-color', `#${track.color.getHexString()}`);
    const obj = new CSS2DObject(el);
    obj.position.copy(track.chomper.root.position).setY(1.8); // above the name label
    this.root.add(obj);
    this.popups.push({ obj, t: 0 });
  }

  // ---- playback -------------------------------------------------------------------------

  /** Playback reached STATE s: pellets, respawns, scores, facing. */
  private reach(s: GameState): StateEvents {
    const prev = this.shown;
    const ev: StateEvents = { state: s, pelletsEaten: [], powerEaten: [], eaten: [], scored: {} };
    const youCell = this.you ? s.positions[this.you] : undefined;
    const youKey = youCell ? `${youCell[0]},${youCell[1]}` : '';
    const { eaten, powerEaten } = this.maze.setPellets(s.pellets, s.power_pellets);
    if (prev) {
      for (const cell of eaten) {
        ev.pelletsEaten.push({ cell, byYou: cell === youKey });
        this.vfx.burst(this.cellWorld(cell), '#ffe2a3', 7, 1.6);
      }
      for (const cell of powerEaten) {
        ev.powerEaten.push({ cell, byYou: cell === youKey });
        this.vfx.shock(this.cellWorld(cell), '#ff8ff0');
        this.vfx.burst(this.cellWorld(cell), '#ff8ff0', 26, 2.6);
      }
      for (const [name, score] of Object.entries(s.scores)) {
        const d = score - (prev.scores[name] ?? 0);
        if (d !== 0) ev.scored[name] = d;
      }
    }

    for (const [name, cell] of Object.entries(s.positions)) {
      let track = this.tracks.get(name);
      if (!track) {
        const hex = PLAYER_COLORS[this.setup.colors[name] ?? 'yellow'] ?? '#ffffff';
        const chomper = new Chomper(name, hex, name === this.you, this.mats);
        chomper.root.position.copy(this.maze.grid.toWorld(cell[0], cell[1]));
        this.root.add(chomper.root);
        track = { chomper, color: new THREE.Color(hex) };
        this.tracks.set(name, track);
        continue;
      }
      const was = prev?.positions[name];
      if (!was) continue;
      const jump = Math.abs(cell[0] - was[0]) + Math.abs(cell[1] - was[1]);
      if (jump > 1) {
        // Eaten: burst where they were, snap to spawn.
        const color = `#${track.color.getHexString()}`;
        this.vfx.burst(track.chomper.root.position, color, 40, 3.2);
        this.vfx.shock(track.chomper.root.position, color);
        ev.eaten.push(name);
        this.trails.forget(name);
      }
    }
    for (const [name, track] of this.tracks) {
      if (!(name in s.positions)) {
        track.chomper.dispose();
        this.trails.forget(name);
        this.tracks.delete(name);
      }
    }
    this.shown = s;
    return ev;
  }

  /** Put every chomper between the STATE just reached and the next one, at renderTick. */
  private place(): void {
    const a = this.shown;
    if (!a) return;
    const b = this.snaps.find((s) => s.tick > a.tick);
    const frac = b ? THREE.MathUtils.clamp((this.renderTick - a.tick) / (b.tick - a.tick), 0, 1) : 0;
    for (const [name, track] of this.tracks) {
      const ca = a.positions[name];
      if (!ca) continue;
      const cb = b?.positions[name];
      const pos = this.maze.grid.toWorld(ca[0], ca[1], this.tmp);
      const step = cb ? Math.abs(cb[0] - ca[0]) + Math.abs(cb[1] - ca[1]) : 0;
      if (cb && step === 1) {
        const to = this.maze.grid.toWorld(cb[0], cb[1]);
        pos.lerp(to, frac);
        track.chomper.face(cb[0] - ca[0], cb[1] - ca[1]);
      }
      track.chomper.root.position.copy(pos);
      track.chomper.moving = step === 1;
    }
  }

  // ---- looks ----------------------------------------------------------------------------

  /** While someone is powered the maze trim takes their colour and pulses. */
  private tintNeon(elapsed: number, delta: number): void {
    const powered = Object.entries(this.shown?.powered ?? {}).filter(([, p]) => p > 0);
    this.neonTarget.copy(NEON);
    let pulse = 1.2;
    if (powered.length) {
      const top = powered.sort((x, y) => y[1] - x[1])[0][0];
      const color = this.tracks.get(top)?.color;
      if (color) this.neonTarget.lerp(color, 0.6);
      pulse = 1.0 + Math.sin(elapsed * 7) * 0.25;
    }
    const k = Math.min(1, delta * 4);
    this.mats.neon.emissive.lerp(this.neonTarget, k);
    this.mats.neon.color.lerp(this.neonTarget, k);
    this.mats.neon.emissiveIntensity += (pulse - this.mats.neon.emissiveIntensity) * k;
  }

  private updatePopups(delta: number): void {
    for (let i = this.popups.length - 1; i >= 0; i -= 1) {
      const p = this.popups[i];
      p.t += delta;
      p.obj.position.y += delta * 1.1;
      p.obj.element.style.opacity = String(Math.max(0, 1 - Math.max(0, p.t - 0.45) / 0.45));
      if (p.t > 0.9) {
        p.obj.element.remove();
        p.obj.removeFromParent();
        this.popups.splice(i, 1);
      }
    }
  }

  private cellWorld(key: string): THREE.Vector3 {
    const [x, y] = key.split(',').map(Number);
    return this.maze.grid.toWorld(x, y, this.tmp).clone();
  }

  dispose(): void {
    for (const t of this.tracks.values()) t.chomper.dispose();
    this.tracks.clear();
    for (const p of this.popups) p.obj.element.remove();
    this.popups.length = 0;
    this.trails.dispose();
    this.maze.dispose();
    this.mats.neon.emissive.copy(NEON);
    this.mats.neon.color.set('#1a47ff');
    this.mats.neon.emissiveIntensity = 1.2;
    this.root.removeFromParent();
  }
}
