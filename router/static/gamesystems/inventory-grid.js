export class InventoryGrid {
  constructor(width = 8, height = 5) {
    this.width = width;
    this.height = height;
    this.slots = Array.from({ length: width * height }, () => null);
  }

  add(item, quantity = 1) {
    const stack = this.slots.find((slot) => slot && slot.id === item.id && slot.quantity < (item.maxStack ?? 1));
    if (stack) {
      const room = (item.maxStack ?? 1) - stack.quantity;
      const moved = Math.min(room, quantity);
      stack.quantity += moved;
      quantity -= moved;
    }
    while (quantity > 0) {
      const idx = this.slots.findIndex((slot) => slot === null);
      if (idx < 0) return false;
      const moved = Math.min(item.maxStack ?? 1, quantity);
      this.slots[idx] = { ...item, quantity: moved };
      quantity -= moved;
    }
    return true;
  }

  move(from, to) {
    if (from === to || !this.slots[from]) return false;
    [this.slots[from], this.slots[to]] = [this.slots[to], this.slots[from]];
    return true;
  }

  serialize() {
    return JSON.stringify({ width: this.width, height: this.height, slots: this.slots });
  }
}
