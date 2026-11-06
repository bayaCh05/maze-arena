import type { GameOver, GameStart, GameState, RoomPlayer } from '../net/protocol';
import { PLAYER_COLORS } from '../net/protocol';

export type Screen = 'login' | 'room' | 'game' | 'over' | 'lost';

function $(sel: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(sel);
  if (!el) throw new Error(`missing ${sel}`);
  return el;
}

function li(className: string, color: string, html: string): HTMLLIElement {
  const el = document.createElement('li');
  el.className = className;
  el.style.setProperty('--c', color);
  el.innerHTML = html;
  return el;
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/** All DOM screens and the HUD. Shows server state; never computes game rules. */
export class Ui {
  readonly nameInput = $('#name-input') as HTMLInputElement;
  readonly roomInput = $('#room-input') as HTMLInputElement;
  readonly loginForm = $('#login-form') as HTMLFormElement;
  readonly playBtn = $('#play-btn') as HTMLButtonElement;
  readonly readyBtn = $('#ready-btn') as HTMLButtonElement;
  readonly leaveBtn = $('#leave-btn');
  readonly againBtn = $('#again-btn');
  readonly overLeaveBtn = $('#over-leave-btn');
  readonly reconnectBtn = $('#reconnect-btn');
  readonly muteBtn = $('#mute');
  readonly dpad = $('#dpad');
  private readonly screens: Record<Exclude<Screen, 'game'>, HTMLElement> = {
    login: $('#screen-login'),
    room: $('#screen-room'),
    over: $('#screen-over'),
    lost: $('#screen-lost'),
  };
  private readonly hud = $('#hud');
  private lastScores: Record<string, number> = {};
  screen: Screen = 'login';

  constructor() {
    try {
      const saved = localStorage.getItem('maze-arena-name');
      if (saved) this.nameInput.value = saved;
    } catch {
      /* storage blocked: start empty */
    }
    const room = new URLSearchParams(location.search).get('room');
    if (room) this.roomInput.value = room.slice(0, 12);
  }

  show(screen: Screen): void {
    this.screen = screen;
    for (const [name, el] of Object.entries(this.screens)) el.hidden = name !== screen;
    this.hud.hidden = screen !== 'game';
    this.dpad.hidden = !(screen === 'game' && matchMedia('(pointer: coarse)').matches);
    if (screen === 'login') queueMicrotask(() => this.nameInput.focus());
  }

  rememberName(name: string): void {
    try {
      localStorage.setItem('maze-arena-name', name);
    } catch {
      /* not essential */
    }
  }

  loginError(text: string): void {
    $('#login-error').textContent = text;
  }

  busy(on: boolean): void {
    this.playBtn.disabled = on;
    this.playBtn.textContent = on ? 'Connecting...' : 'Play';
  }

  room(name: string, players: RoomPlayer[], you: string | null, colors: string[]): void {
    $('#room-name').textContent = name;
    const list = $('#room-players');
    list.replaceChildren();
    players.forEach((p, i) =>
      list.append(
        li(p.ready ? 'ready' : '', colors[i] ?? '#888',
          `<span class="dot"></span><span class="who">${esc(p.name)}${p.name === you ? ' (you)' : ''}</span>` +
          `<span class="state">${p.ready ? 'ready' : 'not ready'}</span>`),
      ),
    );
    for (let i = players.length; i < 3; i += 1) {
      list.append(li('empty', 'transparent', '<span class="dot"></span><span class="who">Waiting for a player...</span><span class="state"></span>'));
    }
    const me = players.find((p) => p.name === you);
    this.readyBtn.textContent = me?.ready ? 'Ready! (tap to cancel)' : "I'm ready";
    this.readyBtn.classList.toggle('is-ready', Boolean(me?.ready));
    const waiting = players.filter((p) => !p.ready).length;
    $('#room-hint').textContent =
      players.length < 2
        ? 'Waiting for at least one more player (2-3 per game).'
        : waiting
          ? `Starts when everyone is ready (${waiting} not ready).`
          : 'Starting...';
  }

  hudSetup(setup: GameStart, you: string | null): void {
    this.lastScores = {};
    $('#hint').textContent = matchMedia('(pointer: coarse)').matches ? 'Swipe or use the pad' : 'Arrows / WASD to steer';
    this.hudState(setup, { type: 'STATE', tick: 0, positions: {}, pellets: [], power_pellets: [], scores: Object.fromEntries(setup.players.map((p) => [p, 0])), powered: {} }, you);
  }

  hudState(setup: GameStart, state: GameState, you: string | null): void {
    const left = Math.max(0, (setup.max_ticks - state.tick) / setup.tick_rate);
    const m = Math.floor(left / 60);
    const s = Math.floor(left % 60);
    $('#timer').textContent = `${m}:${String(s).padStart(2, '0')}`;
    $('.timer').classList.toggle('low', left <= 15);

    const board = $('#scoreboard');
    const rows = Object.entries(state.scores).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    board.replaceChildren(
      ...rows.map(([name, score]) => {
        const bumped = this.lastScores[name] !== undefined && score > this.lastScores[name];
        return li(`${name === you ? 'you' : ''}${bumped ? ' bump' : ''}`, PLAYER_COLORS[setup.colors[name]] ?? '#fff',
          `<span class="dot"></span><span class="who">${esc(name)}</span><span class="score">${score}</span>`);
      }),
    );
    this.lastScores = { ...state.scores };

    const power = you ? state.powered[you] ?? 0 : 0;
    $('#power-meter').hidden = power <= 0;
    ($('#power-fill') as HTMLElement).style.transform = `scaleX(${Math.min(1, power / 50)})`;
  }

  rtt(ms: number | null): void {
    $('#rtt').textContent = ms === null ? 'RTT --' : `RTT ${Math.round(ms)} ms`;
  }

  over(msg: GameOver, colors: Record<string, string>, you: string | null): void {
    $('#over-title').textContent = msg.winner ? (msg.winner === you ? 'You win!' : `${msg.winner} wins`) : "It's a draw";
    $('#over-ranking').replaceChildren(
      ...msg.ranking.map((r) =>
        li('', PLAYER_COLORS[colors[r.name]] ?? '#888',
          `<span class="dot"></span><span class="who">${esc(r.name)}${r.name === you ? ' (you)' : ''}</span><span class="score">${r.score}</span>`),
      ),
    );
  }

  lost(reason: string): void {
    $('#lost-reason').textContent = reason;
  }

  /** Big centred word that punches in and fades ("GO!"). */
  banner(text: string): void {
    const el = $('#banner');
    el.textContent = text;
    el.classList.remove('show');
    void el.offsetWidth; // restart the animation
    el.classList.add('show');
  }

  toast(text: string, bad = false): void {
    const el = document.createElement('div');
    el.className = `toast${bad ? ' bad' : ''}`;
    el.textContent = text;
    $('#toasts').append(el);
    window.setTimeout(() => el.remove(), 3200);
  }

  setMuted(muted: boolean): void {
    this.muteBtn.classList.toggle('is-muted', muted);
    this.muteBtn.setAttribute('aria-label', muted ? 'Unmute sound' : 'Mute sound');
  }
}
