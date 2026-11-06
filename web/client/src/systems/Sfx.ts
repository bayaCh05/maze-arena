/**
 * Synthesised sound effects (Web Audio, no files): chomp, power-up, eaten, start, game over.
 * The context is created on the first user gesture (browser autoplay rule). M mutes.
 */
export class Sfx {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private chompFlip = false;
  muted = false;

  unlock(): void {
    if (this.ctx) {
      void this.ctx.resume();
      return;
    }
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    this.ctx = new Ctor();
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.5;
    this.master.connect(this.ctx.destination);
  }

  toggleMute(): boolean {
    this.muted = !this.muted;
    if (this.master) this.master.gain.value = this.muted ? 0 : 0.5;
    return this.muted;
  }

  chomp(): void {
    this.chompFlip = !this.chompFlip;
    this.tone(this.chompFlip ? 420 : 300, this.chompFlip ? 260 : 380, 0.07, 'square', 0.12);
  }

  power(): void {
    [392, 523, 659, 784].forEach((f, i) => this.tone(f, f * 1.01, 0.09, 'triangle', 0.18, i * 0.06));
  }

  eatenSelf(): void {
    this.tone(520, 90, 0.55, 'sawtooth', 0.16);
  }

  eatenOther(): void {
    this.tone(260, 880, 0.22, 'square', 0.12);
  }

  start(): void {
    [523, 659, 784, 1046].forEach((f, i) => this.tone(f, f, 0.12, 'triangle', 0.2, i * 0.11));
  }

  over(won: boolean): void {
    const notes = won ? [523, 659, 784, 1046, 1318] : [440, 392, 349, 294];
    notes.forEach((f, i) => this.tone(f, f, 0.18, 'triangle', 0.2, i * 0.14));
  }

  click(): void {
    this.tone(880, 660, 0.05, 'sine', 0.1);
  }

  private tone(f0: number, f1: number, dur: number, type: OscillatorType, vol: number, delay = 0): void {
    if (!this.ctx || !this.master || this.ctx.state !== 'running') return;
    const t = this.ctx.currentTime + delay;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(f0, t);
    osc.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(vol, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(gain).connect(this.master);
    osc.start(t);
    osc.stop(t + dur + 0.02);
  }

  dispose(): void {
    void this.ctx?.close();
    this.ctx = null;
  }
}
