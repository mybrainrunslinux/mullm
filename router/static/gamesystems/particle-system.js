export class ParticleEmitter {
  constructor({ scene, texture = null, maxParticles = 800 } = {}) {
    this.scene = scene;
    this.maxParticles = maxParticles;
    this.alive = 0;
    this.positions = new Float32Array(maxParticles * 3);
    this.velocities = Array.from({ length: maxParticles }, () => ({ x: 0, y: 0, z: 0 }));
    this.life = new Float32Array(maxParticles);
    this.geometry = new THREE.BufferGeometry();
    this.geometry.setAttribute("position", new THREE.BufferAttribute(this.positions, 3));
    this.material = new THREE.PointsMaterial({
      size: 0.08,
      color: 0xffb347,
      transparent: true,
      opacity: 0.85,
      map: texture,
      depthWrite: false,
    });
    this.points = new THREE.Points(this.geometry, this.material);
    scene?.add(this.points);
  }

  emit(origin, count = 24, preset = "spark") {
    const palette = { fire: 0xff7a18, smoke: 0x9ca3af, blood: 0xb91c1c, spark: 0xfacc15 };
    this.material.color.setHex(palette[preset] ?? palette.spark);
    for (let i = 0; i < count; i++) {
      const idx = (this.alive + i) % this.maxParticles;
      const p = idx * 3;
      this.positions[p] = origin.x;
      this.positions[p + 1] = origin.y;
      this.positions[p + 2] = origin.z;
      this.velocities[idx] = {
        x: (Math.random() - 0.5) * 1.2,
        y: Math.random() * 1.6,
        z: (Math.random() - 0.5) * 1.2,
      };
      this.life[idx] = 1;
    }
    this.alive = (this.alive + count) % this.maxParticles;
    this.geometry.attributes.position.needsUpdate = true;
  }

  update(dt) {
    for (let i = 0; i < this.maxParticles; i++) {
      if (this.life[i] <= 0) continue;
      this.life[i] -= dt;
      const p = i * 3;
      this.positions[p] += this.velocities[i].x * dt;
      this.positions[p + 1] += this.velocities[i].y * dt;
      this.positions[p + 2] += this.velocities[i].z * dt;
      this.velocities[i].y -= 2.8 * dt;
    }
    this.geometry.attributes.position.needsUpdate = true;
  }
}
