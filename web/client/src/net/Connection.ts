import type { ServerMessage } from './protocol';

/**
 * WebSocket to web/bridge.py, which relays each text frame as one JSON line to the TCP game
 * server. Sends a PING every second: it measures RTT and is the heartbeat the TCP server's
 * 5 s watchdog expects from every client.
 */
export class Connection {
  rttMs: number | null = null;
  private ws: WebSocket | null = null;
  private pingTimer = 0;

  constructor(
    private readonly onMessage: (msg: ServerMessage) => void,
    private readonly onClose: (reason: string) => void,
  ) {}

  get open(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  connect(): Promise<void> {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/ws`);
    this.ws = ws;
    return new Promise((resolve, reject) => {
      let opened = false;
      ws.onopen = () => {
        opened = true;
        this.pingTimer = window.setInterval(() => this.send({ type: 'PING', t: performance.now() / 1000 }), 1000);
        resolve();
      };
      ws.onmessage = (event) => {
        let msg: ServerMessage;
        try {
          msg = JSON.parse(event.data as string) as ServerMessage;
        } catch {
          return; // a broken line is skipped, like the TCP clients do
        }
        if (msg.type === 'PONG' && typeof msg.t === 'number') {
          this.rttMs = performance.now() - msg.t * 1000;
          return;
        }
        this.onMessage(msg);
      };
      ws.onclose = () => {
        window.clearInterval(this.pingTimer);
        if (!opened) reject(new Error('cannot reach the game server'));
        else this.onClose('connection to the server was lost');
      };
    });
  }

  send(msg: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  close(): void {
    window.clearInterval(this.pingTimer);
    this.ws?.close();
    this.ws = null;
  }
}
