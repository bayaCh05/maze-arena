import * as THREE from 'three';
import { MaterialLibrary } from '../assets/Materials';
import { Loop } from '../core/Loop';
import { createRenderer } from '../core/Renderer';
import { Connection } from '../net/Connection';
import type { Dir, GameStart, ServerMessage } from '../net/protocol';
import { PLAYER_COLORS } from '../net/protocol';
import { RenderPipeline } from '../systems/RenderPipeline';
import { Sfx } from '../systems/Sfx';
import { Vfx } from '../systems/Vfx';
import { Ui } from '../ui/Ui';
import { createSeededRandom } from '../utils/random';
import { Arena, type StateEvents } from './Arena';
import { PREVIEW_OVER, PREVIEW_ROOM, PREVIEW_START, previewState } from './preview';

const KEY_DIRS: Record<string, Dir> = {
  ArrowUp: 'UP', ArrowDown: 'DOWN', ArrowLeft: 'LEFT', ArrowRight: 'RIGHT',
  KeyW: 'UP', KeyS: 'DOWN', KeyA: 'LEFT', KeyD: 'RIGHT',
};
const GRID_STEP: Record<Dir, [number, number]> = { UP: [0, -1], DOWN: [0, 1], LEFT: [-1, 0], RIGHT: [1, 0] };
const STREAK_GAP = 0.45; // s between two of your pellets that still counts as a streak
const ROOM_COLORS = [PLAYER_COLORS.yellow, PLAYER_COLORS.cyan, PLAYER_COLORS.magenta];

/**
 * Screen flow + network + input. The server decides everything; this class forwards the
 * player's intents (LOGIN, rooms, READY, INPUT) and hands every server message to the
 * arena (3D) or the UI (DOM).
 */
export class App {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly pipeline: RenderPipeline;
  private readonly mats: MaterialLibrary;
  private readonly vfx: Vfx;
  private readonly sfx = new Sfx();
  private readonly ui = new Ui();
  private readonly conn: Connection;
  private readonly loop = new Loop((d, e) => this.update(d, e), () => this.pipeline.render());
  private arena: Arena | null = null;
  private setup: GameStart | null = null;
  private you: string | null = null;
  private loggedIn = false;
  private joining = false;
  private roomReady = false;
  private frame = 0;
  private elapsed = 0;
  private rttTimer = 0;
  private paused = false;
  private reducedMotion = false;
  private swipe: { x: number; y: number } | null = null;
  private streak = 0;
  private lastPelletAt = -1;

  constructor(private readonly canvas: HTMLCanvasElement) {
    this.renderer = createRenderer(canvas);
    this.pipeline = new RenderPipeline(this.renderer, this.scene, document.querySelector('#app')!);
    this.mats = new MaterialLibrary(this.renderer.capabilities.getMaxAnisotropy());
    this.vfx = new Vfx(createSeededRandom(1));
    this.conn = new Connection((m) => this.onMessage(m), (r) => this.onClosed(r));
    this.buildLighting();
    this.scene.add(this.vfx.root);
    this.useArena(PREVIEW_START, null);
    this.bindUi();
    this.bindInput();
    this.installTestHooks();
    this.ui.show('login');
  }

  start(): void {
    this.loop.start();
  }

  dispose(): void {
    this.loop.stop();
    this.conn.close();
    this.arena?.dispose();
    this.vfx.dispose();
    this.mats.dispose();
    this.sfx.dispose();
    this.pipeline.dispose();
    this.renderer.dispose();
    window.__THREE_GAME_DIAGNOSTICS__ = undefined;
    window.__THREE_GAME_TEST_HOOKS__ = undefined;
  }

  // ---- scene ----------------------------------------------------------------------------

  private buildLighting(): void {
    this.scene.background = new THREE.Color('#04060f');
    this.scene.fog = new THREE.Fog('#04060f', 26, 60);
    this.scene.add(new THREE.HemisphereLight('#9fb4ff', '#0a0c1c', 0.75));
    const key = new THREE.DirectionalLight('#fff2dc', 1.7);
    key.position.set(-6, 14, 9);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -12;
    key.shadow.camera.right = 12;
    key.shadow.camera.top = 10;
    key.shadow.camera.bottom = -10;
    key.shadow.bias = -0.0006;
    key.shadow.normalBias = 0.02;
    this.scene.add(key);
    const rim = new THREE.DirectionalLight('#5b7bff', 1.4);
    rim.position.set(7, 6, -10);
    this.scene.add(rim);
  }

  private useArena(setup: GameStart, you: string | null): void {
    this.arena?.dispose();
    this.vfx.clear();
    this.setup = setup;
    this.arena = new Arena(setup, you, this.mats, this.vfx);
    this.scene.add(this.arena.root);
    this.pipeline.frameMaze(setup.maze[0].length, setup.maze.length);
  }

  private update(delta: number, time: number): void {
    this.frame += 1;
    if (!this.paused) {
      this.elapsed += delta;
      const t = this.reducedMotion ? 0 : this.elapsed;
      this.vfx.update(this.reducedMotion ? 0 : delta);
      const events = this.arena?.update(delta, t, performance.now()) ?? [];
      for (const ev of events) this.onReached(ev);
      this.pipeline.update(this.reducedMotion ? 0 : delta);
      this.updateMood();
      this.rttTimer -= delta;
      if (this.rttTimer <= 0) {
        this.rttTimer = 0.5;
        this.ui.rtt(this.conn.rttMs);
      }
    }
    void time;
    this.publishDiagnostics();
  }

  // ---- network --------------------------------------------------------------------------

  private async submitLogin(): Promise<void> {
    this.sfx.unlock();
    const name = this.ui.nameInput.value.trim();
    const room = this.ui.roomInput.value.trim() || 'demo';
    this.ui.roomInput.value = room;
    if (!name) {
      this.ui.loginError('Type a name first.');
      return;
    }
    this.ui.loginError('');
    if (!this.conn.open) {
      this.ui.busy(true);
      try {
        await this.conn.connect();
      } catch {
        this.ui.busy(false);
        this.ui.loginError("Can't reach the game server. Is the host's server running?");
        return;
      }
      this.ui.busy(false);
    }
    if (!this.loggedIn) this.conn.send({ type: 'LOGIN', name });
    else this.joinRoom();
  }

  private joinRoom(): void {
    const room = this.ui.roomInput.value.trim() || 'demo';
    this.joining = true;
    this.conn.send({ type: 'CREATE_ROOM', room }); // refused with "room already exists": fine
    this.conn.send({ type: 'JOIN_ROOM', room });
  }

  private onMessage(msg: ServerMessage): void {
    switch (msg.type) {
      case 'LOGIN_OK':
        this.loggedIn = true;
        this.you = msg.name;
        this.ui.rememberName(msg.name);
        this.ui.nameInput.disabled = true;
        this.joinRoom();
        break;
      case 'LOGIN_FAIL':
        this.ui.loginError(msg.reason === 'name already taken' ? 'That name is taken: pick another one.' : msg.reason);
        break;
      case 'ROOM_LIST':
        if (!msg.error || msg.error === 'room already exists') break;
        if (this.joining && this.ui.screen === 'login') {
          this.ui.loginError(msg.error === 'game already running'
            ? 'A game is running in this room: wait for it to end, or pick another room.'
            : msg.error);
        } else {
          this.ui.toast(msg.error, true);
        }
        this.joining = false;
        break;
      case 'ROOM_UPDATE': {
        this.joining = false;
        this.roomReady = msg.players.find((p) => p.name === this.you)?.ready ?? false;
        this.ui.room(msg.room, msg.players, this.you, ROOM_COLORS);
        if (this.ui.screen === 'login') this.ui.show('room');
        break;
      }
      case 'GAME_START':
        this.useArena(msg, this.you);
        this.ui.hudSetup(msg, this.you);
        this.ui.show('game');
        this.ui.banner('GO!');
        this.sfx.start();
        this.streak = 0;
        break;
      case 'STATE':
        // Played back smoothly by the arena; its events come out of update().
        if (this.arena && this.setup) this.arena.push(msg, performance.now());
        break;
      case 'GAME_OVER':
        this.ui.over(msg, this.setup?.colors ?? {}, this.you);
        this.ui.show('over');
        this.sfx.over(msg.winner === this.you);
        break;
      case 'PLAYER_LEFT':
        if (msg.name !== this.you) this.ui.toast(`${msg.name} left`);
        break;
    }
  }

  /** Playback reached a STATE: sounds, popups, streaks, camera kicks, HUD. */
  private onReached(ev: StateEvents): void {
    if (!this.setup || !this.arena) return;
    const mine = ev.pelletsEaten.some((p) => p.byYou);
    if (mine) {
      this.streak = this.elapsed - this.lastPelletAt < STREAK_GAP ? this.streak + 1 : 1;
      this.lastPelletAt = this.elapsed;
      this.sfx.chomp(Math.min(this.streak, 12));
      if (this.streak >= 5 && this.streak % 5 === 0 && this.you) this.arena.popup(this.you, `x${this.streak} streak!`, 'streak');
    } else if (this.elapsed - this.lastPelletAt > STREAK_GAP) {
      this.streak = 0;
    }
    if (ev.powerEaten.some((p) => p.byYou)) {
      this.sfx.power();
      this.pipeline.kick(0.18);
    }
    for (const name of ev.eaten) {
      if (name === this.you) {
        this.sfx.eatenSelf();
        this.ui.toast('You got eaten! -50', true);
        this.pipeline.kick(0.45);
      } else {
        this.sfx.eatenOther();
        this.ui.toast(`${name} got eaten`);
        this.pipeline.kick(0.12);
      }
    }
    for (const [name, d] of Object.entries(ev.scored)) {
      // Pellets are frequent: only show popups for bigger swings, and yours every time.
      if (name === this.you || Math.abs(d) >= 30) this.arena.popup(name, d > 0 ? `+${d}` : `${d}`, d > 0 ? 'gain' : 'loss');
    }
    this.ui.hudState(this.setup, ev.state, this.you);
  }

  /** Screen-edge glow: gold while you are powered, a cold blue pulse while you are prey. */
  private updateMood(): void {
    const powered = this.arena?.current?.powered ?? {};
    const mine = this.you ? powered[this.you] ?? 0 : 0;
    const prey = !mine && Object.entries(powered).some(([n, p]) => n !== this.you && p > 0);
    const mood = this.ui.screen !== 'game' ? '' : mine > 0 ? 'power' : prey ? 'prey' : '';
    if (document.body.dataset.mood !== mood) document.body.dataset.mood = mood;
  }

  private onClosed(reason: string): void {
    this.loggedIn = false;
    this.ui.nameInput.disabled = false;
    this.ui.lost(`${reason}. Your browser is fine: the host's server or tunnel may have restarted.`);
    this.ui.show('lost');
  }

  private toggleReady(): void {
    this.sfx.unlock();
    this.sfx.click();
    this.conn.send({ type: 'READY', ready: !this.roomReady });
  }

  private leave(): void {
    this.conn.send({ type: 'LEAVE_ROOM' });
    this.useArena(PREVIEW_START, null);
    this.ui.show('login');
  }

  /** dir is what the player pressed or swiped on screen; the server gets the grid direction. */
  private steer(dir: Dir): void {
    if (this.ui.screen !== 'game') return;
    const grid = this.pipeline.screenToGrid(dir);
    this.conn.send({ type: 'INPUT', dir: grid });
    this.arena?.intent(...GRID_STEP[grid]);
  }

  // ---- UI + input -----------------------------------------------------------------------

  private bindUi(): void {
    this.ui.loginForm.addEventListener('submit', (e) => {
      e.preventDefault();
      void this.submitLogin();
    });
    this.ui.readyBtn.addEventListener('click', () => this.toggleReady());
    this.ui.leaveBtn.addEventListener('click', () => this.leave());
    this.ui.againBtn.addEventListener('click', () => {
      this.sfx.click();
      this.conn.send({ type: 'READY', ready: true });
      this.ui.show('room');
    });
    this.ui.overLeaveBtn.addEventListener('click', () => this.leave());
    this.ui.reconnectBtn.addEventListener('click', () => {
      this.useArena(PREVIEW_START, null);
      this.ui.show('login');
      void this.submitLogin();
    });
    this.ui.muteBtn.addEventListener('click', () => {
      this.sfx.unlock();
      this.ui.setMuted(this.sfx.toggleMute());
    });
  }

  private bindInput(): void {
    window.addEventListener('keydown', (e) => {
      const typing = e.target instanceof HTMLInputElement;
      const dir = KEY_DIRS[e.code];
      if (dir && this.ui.screen === 'game') {
        e.preventDefault();
        if (!e.repeat) this.steer(dir);
        return;
      }
      if (typing || e.repeat) return;
      if (e.code === 'KeyR' && this.ui.screen === 'room') this.toggleReady();
      if (e.code === 'KeyM') this.ui.setMuted(this.sfx.toggleMute());
    });

    // Swipe anywhere on the game view: one direction per 24 px of travel, chainable.
    this.canvas.addEventListener('pointerdown', (e) => {
      this.swipe = { x: e.clientX, y: e.clientY };
    });
    this.canvas.addEventListener('pointermove', (e) => {
      if (!this.swipe) return;
      const dx = e.clientX - this.swipe.x;
      const dy = e.clientY - this.swipe.y;
      if (Math.hypot(dx, dy) < 24) return;
      this.steer(Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'RIGHT' : 'LEFT') : dy > 0 ? 'DOWN' : 'UP');
      this.swipe = { x: e.clientX, y: e.clientY };
    });
    const endSwipe = () => {
      this.swipe = null;
    };
    this.canvas.addEventListener('pointerup', endSwipe);
    this.canvas.addEventListener('pointercancel', endSwipe);

    for (const btn of this.ui.dpad.querySelectorAll<HTMLButtonElement>('button')) {
      btn.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        btn.classList.add('pressed');
        this.steer(btn.dataset.dir as Dir);
      });
      const release = () => btn.classList.remove('pressed');
      btn.addEventListener('pointerup', release);
      btn.addEventListener('pointerleave', release);
    }
  }

  // ---- test hooks + diagnostics ---------------------------------------------------------

  private installTestHooks(): void {
    // Real states rendered through the same arena/UI code as a live game, from the canned
    // snapshots in preview.ts (no server needed). Used by the canvas inspector and baselines.
    window.__THREE_GAME_TEST_HOOKS__ = {
      seed: (value: number) => {
        this.vfx.setRandom(createSeededRandom(value));
      },
      setState: (name: string) => {
        const now = performance.now();
        if (name === 'lobby') {
          this.useArena(PREVIEW_START, null);
          this.ui.show('login');
        } else if (name === 'room') {
          this.useArena(PREVIEW_START, null);
          this.ui.room('demo', PREVIEW_ROOM, 'baya', ROOM_COLORS);
          this.ui.show('room');
        } else if (name === 'active-play' || name === 'game-over') {
          this.you = 'baya';
          this.useArena(PREVIEW_START, 'baya');
          const state = previewState();
          this.arena!.push(state, now - 1000);
          this.ui.hudSetup(PREVIEW_START, 'baya');
          this.ui.hudState(PREVIEW_START, state, 'baya');
          this.ui.rtt(42);
          if (name === 'game-over') {
            this.ui.over(PREVIEW_OVER, PREVIEW_START.colors, 'baya');
            this.ui.show('over');
          } else {
            this.ui.show('game');
          }
        } else {
          throw new Error(`Unknown test state: ${name}`);
        }
        this.vfx.clear();
        this.arena?.update(0.016, this.reducedMotion ? 0 : this.elapsed, now);
        this.pipeline.render();
        this.publishDiagnostics();
        return { state: name };
      },
      setPausedForScreenshot: (paused: boolean) => {
        this.paused = paused;
      },
      setReducedMotion: (enabled: boolean) => {
        this.reducedMotion = enabled;
        this.arena?.update(0, 0, performance.now());
        this.pipeline.render();
      },
      hideDebugUi: () => {
        /* this client has no debug UI */
      },
    };
  }

  private publishDiagnostics(): void {
    const info = this.renderer.info;
    const me = this.arena?.positionOf(this.you);
    const state = this.arena?.current;
    window.__THREE_GAME_DIAGNOSTICS__ = {
      frame: this.frame,
      elapsed: this.elapsed,
      score: (this.you && state?.scores[this.you]) || 0,
      targetScore: this.arena?.maze.totalPellets ?? 0,
      complete: this.ui.screen === 'over',
      player: { position: { x: me?.x ?? 0, y: me?.y ?? 0, z: me?.z ?? 0 }, speed: 0 },
      renderer: {
        calls: info.render.calls,
        triangles: info.render.triangles,
        geometries: info.memory.geometries,
        textures: info.memory.textures,
      },
      canvas: {
        clientWidth: this.canvas.clientWidth,
        clientHeight: this.canvas.clientHeight,
        width: this.canvas.width,
        height: this.canvas.height,
        dpr: Math.min(window.devicePixelRatio || 1, this.pipeline.maxDpr),
      },
      screen: this.ui.screen,
      tick: state?.tick ?? null,
      rttMs: this.conn.rttMs,
      bufferMs: this.arena?.bufferMs ?? null,
    };
  }
}
