export class CameraShake {
  constructor(camera) {
    this.camera = camera;
    this.trauma = 0;
    this.seed = Math.random() * 1000;
    this.base = camera?.position?.clone?.() ?? null;
  }

  add(amount = 0.35) {
    this.trauma = Math.min(1, this.trauma + amount);
    if (this.camera?.position?.clone) this.base = this.camera.position.clone();
  }

  update(dt) {
    if (!this.camera || !this.base || this.trauma <= 0) return;
    const shake = this.trauma * this.trauma;
    const t = performance.now() * 0.02 + this.seed;
    this.camera.position.set(
      this.base.x + Math.sin(t * 1.7) * shake * 0.18,
      this.base.y + Math.cos(t * 2.1) * shake * 0.12,
      this.base.z + Math.sin(t * 2.9) * shake * 0.18,
    );
    this.trauma = Math.max(0, this.trauma - dt * 1.8);
  }
}
