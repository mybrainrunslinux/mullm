export class DayNightCycle {
  constructor({ scene, sun, duration = 240 } = {}) {
    this.scene = scene;
    this.sun = sun;
    this.duration = duration;
    this.time = 0.25;
    this.colors = {
      dawn: new THREE.Color(0xf59e0b),
      noon: new THREE.Color(0x93c5fd),
      dusk: new THREE.Color(0xc084fc),
      night: new THREE.Color(0x020617),
    };
  }

  update(dt) {
    this.time = (this.time + dt / this.duration) % 1;
    const angle = this.time * Math.PI * 2;
    if (this.sun) {
      this.sun.position.set(Math.cos(angle) * 40, Math.sin(angle) * 35, 12);
      this.sun.intensity = Math.max(0.05, Math.sin(angle));
    }
    const daylight = Math.max(0, Math.sin(angle));
    const sky = this.colors.night.clone().lerp(this.colors.noon, daylight);
    if (this.scene) {
      this.scene.background = sky;
      this.scene.fog = new THREE.FogExp2(sky, 0.006 + (1 - daylight) * 0.018);
    }
  }
}
