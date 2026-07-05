export class ComboSystem {
  constructor({ windowMs = 420, decayMs = 1400 } = {}) {
    this.windowMs = windowMs;
    this.decayMs = decayMs;
    this.buffer = [];
    this.combo = 0;
    this.lastHit = 0;
  }

  input(action, now = performance.now()) {
    this.buffer = this.buffer.filter((entry) => now - entry.time <= this.windowMs);
    this.buffer.push({ action, time: now });
    return this.sequence();
  }

  hit(baseDamage, now = performance.now()) {
    if (now - this.lastHit > this.decayMs) this.combo = 0;
    this.combo += 1;
    this.lastHit = now;
    return Math.round(baseDamage * (1 + Math.min(2.5, this.combo * 0.08)));
  }

  sequence() {
    return this.buffer.map((entry) => entry.action).join(">");
  }
}
