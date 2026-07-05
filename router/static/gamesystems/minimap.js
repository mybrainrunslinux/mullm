export class Minimap {
  constructor(canvas, worldSize = 200) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.worldSize = worldSize;
    this.zoom = 1;
  }

  project(position) {
    const scale = (this.canvas.width / this.worldSize) * this.zoom;
    return {
      x: this.canvas.width / 2 + position.x * scale,
      y: this.canvas.height / 2 + position.z * scale,
    };
  }

  draw({ player, enemies = [], objectives = [] }) {
    const c = this.ctx;
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
    c.fillStyle = "rgba(15,23,42,.82)";
    c.fillRect(0, 0, this.canvas.width, this.canvas.height);
    for (const obj of objectives) this.dot(obj.position, "#22c55e", 4);
    for (const enemy of enemies) this.dot(enemy.position, "#ef4444", 3);
    this.dot(player.position, "#38bdf8", 5);
  }

  dot(position, color, radius) {
    const p = this.project(position);
    this.ctx.fillStyle = color;
    this.ctx.beginPath();
    this.ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    this.ctx.fill();
  }
}
