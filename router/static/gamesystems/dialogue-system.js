export class DialogueTree {
  constructor(nodes, variables = {}) {
    this.nodes = nodes;
    this.variables = variables;
    this.current = nodes.start;
  }

  line() {
    if (!this.current) return null;
    return {
      speaker: this.current.speaker ?? "NPC",
      text: this.interpolate(this.current.text ?? ""),
      choices: (this.current.choices ?? []).filter((choice) => this.allowed(choice)),
    };
  }

  choose(index) {
    const options = this.line()?.choices ?? [];
    const choice = options[index];
    if (!choice) return false;
    for (const [key, value] of Object.entries(choice.set ?? {})) this.variables[key] = value;
    this.current = this.nodes[choice.next] ?? null;
    return true;
  }

  allowed(choice) {
    return Object.entries(choice.when ?? {}).every(([key, value]) => this.variables[key] === value);
  }

  interpolate(text) {
    return text.replace(/\{([a-z0-9_]+)\}/gi, (_, key) => String(this.variables[key] ?? ""));
  }
}
