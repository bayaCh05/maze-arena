import * as THREE from 'three';
import { Chomper } from '../assets/Chomper';
import type { MaterialLibrary } from '../assets/Materials';
import { MazeKit } from '../assets/MazeKit';
import type { GameStart, GameState } from '../net/protocol';
import { PLAYER_COLORS } from '../net/protocol';
import type { Vfx } from '../systems/Vfx';

/** What changed between two STATEs, for sound and HUD feedback. */
export interface StateEvents {
  pelletsEaten: { cell: string; byYou: boolean }[];
  powerEaten: { cell: string; byYou: boolean }[];
  eaten: string[]; // players who jumped back to their spawn (eaten by a powered rival)
}

interface Track {
  chomper: Chomper;
  from: THREE.Vector3;
  to: THREE.Vector3;
  cell: [number, number];
  t0: number;
  movedAt: number;
}

/**
 * The game world for one GAME_START: maze kit + one chomper per player. Applies each STATE
 * (server truth) and glides a player between two consecutive cells over one tick, purely
 * cosmetic, like the pygame client: any jump other than one cell is drawn as a snap.
 */
export class Arena {
  readonly root = new THREE.Group();
  readonly maze: MazeKit;
  private readonly tracks = new Map<string, Track>();
  private state: GameState | null = null;
  private readonly tickMs: number;
  private readonly tmp = new THREE.Vector3();

  constructor(
    readonly setup: GameStart,
    private readonly you: string | null,
    private readonly mats: MaterialLibrary,
    private readonly vfx: Vfx,
  ) {
    this.root.name = 'arena';
    this.maze = new MazeKit(setup.maze, mats);
    this.root.add(this.maze.root);
    this.tickMs = 1000 / setup.tick_rate;
  }

  get current(): GameState | null {
    return this.state;
  }

  apply(state: GameState, now: number): StateEvents {
    const events: StateEvents = { pelletsEaten: [], powerEaten: [], eaten: [] };
    const youCell = this.you ? state.positions[this.you] : undefined;
    const youKey = youCell ? `${youCell[0]},${youCell[1]}` : '';
    const { eaten, powerEaten } = this.maze.setPellets(state.pellets, state.power_pellets);
    for (const cell of eaten) {
      events.pelletsEaten.push({ cell, byYou: cell === youKey });
      this.vfx.burst(this.cellWorld(cell), '#ffe2a3', 7, 1.6);
    }
    for (const cell of powerEaten) {
      events.powerEaten.push({ cell, byYou: cell === youKey });
      this.vfx.shock(this.cellWorld(cell), '#ff8ff0');
      this.vfx.burst(this.cellWorld(cell), '#ff8ff0', 26, 2.6);
    }

    for (const [name, cell] of Object.entries(state.positions)) {
      let track = this.tracks.get(name);
      if (!track) {
        const colorName = this.setup.colors[name] ?? 'yellow';
        const chomper = new Chomper(name, PLAYER_COLORS[colorName] ?? '#ffffff', name === this.you, this.mats);
        const at = this.maze.grid.toWorld(cell[0], cell[1]);
        track = { chomper, from: at.clone(), to: at.clone(), cell: [cell[0], cell[1]], t0: now, movedAt: -1e9 };
        chomper.root.position.copy(at);
        this.root.add(chomper.root);
        this.tracks.set(name, track);
        continue;
      }
      const dx = cell[0] - track.cell[0];
      const dy = cell[1] - track.cell[1];
      if (dx === 0 && dy === 0) continue;
      const next = this.maze.grid.toWorld(cell[0], cell[1]);
      if (Math.abs(dx) + Math.abs(dy) === 1) {
        track.from.copy(track.chomper.root.position);
        track.to.copy(next);
        track.t0 = now;
        track.movedAt = now;
        track.chomper.face(dx, dy);
      } else {
        // More than one cell: respawn after being eaten. Burst where they were, snap to spawn.
        const color = PLAYER_COLORS[this.setup.colors[name]] ?? '#ffffff';
        this.vfx.burst(track.chomper.root.position, color, 40, 3.2);
        this.vfx.shock(track.chomper.root.position, color);
        events.eaten.push(name);
        track.from.copy(next);
        track.to.copy(next);
        track.chomper.root.position.copy(next);
      }
      track.cell = [cell[0], cell[1]];
    }
    // Players missing from STATE left the game.
    for (const [name, track] of this.tracks) {
      if (!(name in state.positions)) {
        track.chomper.dispose();
        this.tracks.delete(name);
      }
    }
    this.state = state;
    return events;
  }

  update(delta: number, elapsed: number, now: number): void {
    this.maze.update(elapsed);
    const powered = this.state?.powered ?? {};
    for (const [name, track] of this.tracks) {
      const t = Math.min(1, (now - track.t0) / this.tickMs);
      track.chomper.root.position.lerpVectors(track.from, track.to, t);
      const moving = now - track.movedAt < this.tickMs * 1.6;
      const power = powered[name] ?? 0;
      const rivalPowered = Object.entries(powered).some(([n, p]) => n !== name && p > 0);
      track.chomper.update(delta, elapsed, moving, power, rivalPowered && power === 0);
    }
  }

  /** World position of a player's chomper (for diagnostics), or null. */
  positionOf(name: string | null): THREE.Vector3 | null {
    if (!name) return null;
    return this.tracks.get(name)?.chomper.root.position ?? null;
  }

  private cellWorld(key: string): THREE.Vector3 {
    const [x, y] = key.split(',').map(Number);
    return this.maze.grid.toWorld(x, y, this.tmp).clone();
  }

  dispose(): void {
    for (const t of this.tracks.values()) t.chomper.dispose();
    this.tracks.clear();
    this.maze.dispose();
    this.root.removeFromParent();
  }
}
