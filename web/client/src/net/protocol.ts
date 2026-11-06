// Message shapes of the Maze Arena contract (common/protocol.py). The browser only sends
// LOGIN, CREATE_ROOM, JOIN_ROOM, LEAVE_ROOM, READY, INPUT and PING, and renders the rest.

export type Dir = 'UP' | 'DOWN' | 'LEFT' | 'RIGHT';
export type Cell = [number, number];

export interface RoomPlayer {
  name: string;
  ready: boolean;
}

export interface GameStart {
  type: 'GAME_START';
  room: string;
  tick_rate: number;
  max_ticks: number;
  maze: string[];
  players: string[];
  colors: Record<string, string>;
}

export interface GameState {
  type: 'STATE';
  tick: number;
  positions: Record<string, Cell>;
  pellets: Cell[];
  power_pellets: Cell[];
  scores: Record<string, number>;
  powered: Record<string, number>;
}

export interface GameOver {
  type: 'GAME_OVER';
  winner: string | null;
  ranking: { name: string; score: number }[];
}

export type ServerMessage =
  | { type: 'LOGIN_OK'; name: string }
  | { type: 'LOGIN_FAIL'; reason: string }
  | { type: 'ROOM_LIST'; rooms: unknown[]; error?: string }
  | { type: 'ROOM_UPDATE'; room: string; players: RoomPlayer[] }
  | { type: 'PLAYER_LEFT'; name: string }
  | { type: 'PONG'; t?: number }
  | GameStart
  | GameState
  | GameOver;

/** Same colour names the server assigns (common/game.py COLORS). */
export const PLAYER_COLORS: Record<string, string> = {
  yellow: '#ffd600',
  cyan: '#00e1ff',
  magenta: '#ff5fe1',
};

export const NAME_MAX = 12;
