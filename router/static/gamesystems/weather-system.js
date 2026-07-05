export class WeatherSystem {
  constructor(scene) {
    this.scene = scene;
    this.state = "clear";
    this.intensity = 0;
    this.target = 0;
    this.wind = new THREE.Vector3(0.4, 0, 0.1);
  }

  setWeather(state, intensity = 1) {
    this.state = state;
    this.target = Math.max(0, Math.min(1, intensity));
  }

  update(dt) {
    this.intensity += (this.target - this.intensity) * Math.min(1, dt * 2);
    if (!this.scene) return;
    const fogColor = this.state === "snow" ? 0xdbeafe : this.state === "rain" ? 0x334155 : 0x93c5fd;
    const density = this.state === "clear" ? 0.004 : 0.01 + this.intensity * 0.02;
    this.scene.fog = new THREE.FogExp2(fogColor, density);
  }

  lightning(light) {
    if (this.state !== "rain" || Math.random() > 0.01 * this.intensity) return;
    const previous = light.intensity;
    light.intensity = 6;
    setTimeout(() => { light.intensity = previous; }, 90);
  }
}
