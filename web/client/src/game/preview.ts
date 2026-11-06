import type { GameOver, GameStart, GameState, RoomPlayer } from '../net/protocol';

/**
 * Offline snapshots for the title-screen backdrop and the test hooks (lobby / active-play /
 * game-over). The maze is a copy of the server's default map; a live game always uses the
 * maze from GAME_START instead.
 */
export const PREVIEW_MAZE = [
  '####################',
  '#1.......##.......2#',
  '#o##.###.##.###.##o#',
  '#..................#',
  '#.##.#.######.#.##.#',
  '#....#...##...#....#',
  '####.###.##.###.####',
  '#........3.........#',
  '####.#.######.#.####',
  '#....#....##..#....#',
  '#.##.###.##.###.##.#',
  '#o.#............#.o#',
  '##.#.##.####.##.#.##',
  '#..................#',
  '####################',
];

export const PREVIEW_START: GameStart = {
  type: 'GAME_START',
  room: 'demo',
  tick_rate: 10,
  max_ticks: 1200,
  maze: PREVIEW_MAZE,
  players: ['baya', 'yahia', 'nour'],
  colors: { baya: 'yellow', yahia: 'cyan', nour: 'magenta' },
};

function cells(ch: string): [number, number][] {
  const out: [number, number][] = [];
  PREVIEW_MAZE.forEach((row, y) => [...row].forEach((c, x) => c === ch && out.push([x, y])));
  return out;
}

/** Mid-game: a third of the pellets gone, one power pellet used, cyan powered and hunting. */
export function previewState(): GameState {
  const eaten = new Set(['1,1', '2,1', '3,1', '4,1', '5,1', '6,1', '1,3', '2,3', '3,3', '4,3', '4,4', '4,5',
    '18,3', '17,3', '16,3', '15,3', '14,3', '13,3', '12,3', '18,4', '18,5', '17,5', '16,5', '8,7', '7,7',
    '6,7', '5,7', '4,7', '10,7', '11,7', '12,7', '13,7', '14,7', '9,13', '10,13', '11,13', '12,13']);
  return {
    type: 'STATE',
    tick: 642,
    positions: { baya: [4, 6], yahia: [12, 3], nour: [9, 11] },
    pellets: cells('.').filter(([x, y]) => !eaten.has(`${x},${y}`)),
    power_pellets: [[1, 2], [1, 11], [18, 11]],
    scores: { baya: 230, yahia: 310, nour: 140 },
    powered: { baya: 0, yahia: 34, nour: 0 },
  };
}

export const PREVIEW_ROOM: RoomPlayer[] = [
  { name: 'baya', ready: true },
  { name: 'yahia', ready: false },
];

export const PREVIEW_OVER: GameOver = {
  type: 'GAME_OVER',
  winner: 'yahia',
  ranking: [
    { name: 'yahia', score: 610 },
    { name: 'baya', score: 480 },
    { name: 'nour', score: 220 },
  ],
};
