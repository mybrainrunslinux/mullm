export function buildPlan(input, sources = []) {
  const warnings = [];
  const { name, audience, objective, budget, days, channels } = input;

  const cleanChannels = (channels || "")
    .split(",")
    .map(c => c.trim())
    .filter(c => c.length > 0);

  const uniqueChannels = [...new Set(cleanChannels)];

  const safeBudget = Number(budget) || 0;
  const safeDays = Number(days) || 0;

  if (safeBudget <= 0 || uniqueChannels.length === 0) {
    warnings.push("Budget must be positive and at least one channel is required.");
  }

  const allocation = [];
  if (safeBudget > 0 && uniqueChannels.length > 0) {
    const totalCents = Math.round(safeBudget * 100);
    const baseCents = Math.floor(totalCents / uniqueChannels.length);
    const remainder = totalCents - baseCents * uniqueChannels.length;

    uniqueChannels.forEach((ch, i) => {
      allocation.push({
        channel: ch,
        amount: (baseCents + (i === uniqueChannels.length - 1 ? remainder : 0)) / 100
      });
    });
  }

  const milestones = [];
  if (safeDays > 0) {
    const p1 = Math.max(1, Math.floor(safeDays * 0.2));
    const p2 = Math.max(p1 + 1, Math.floor(safeDays * 0.5));
    const p3 = Math.max(p2 + 1, safeDays);
    milestones.push({ day: p1, label: "Prepare" });
    milestones.push({ day: p2, label: "Launch" });
    milestones.push({ day: p3, label: "Review" });
  } else {
    warnings.push("Planning window must be at least 1 day.");
  }

  const summary = `Campaign "${name || "Untitled"}" targets ${audience || "general"} to ${objective || "achieve goals"}.`;

  const sections = [];
  if (allocation.length > 0) {
    sections.push({
      title: "Budget Allocation",
      items: allocation.map(a => `${a.channel}: $${a.amount.toFixed(2)}`)
    });
  }
  if (milestones.length > 0) {
    sections.push({
      title: "Milestones",
      items: milestones.map(m => `Day ${m.day}: ${m.label}`)
    });
  }
  sections.push({
    title: "Measurement Actions",
    items: [
      "Track channel-specific engagement metrics.",
      "Review conversion data at the Review milestone.",
      "Adjust allocation based on performance."
    ]
  });

  return {
    summary,
    metrics: [
      { label: "Total Budget", value: `$${safeBudget.toFixed(2)}` },
      { label: "Planning Days", value: safeDays },
      { label: "Channels", value: uniqueChannels.length }
    ],
    sections,
    warnings,
    allocation,
    milestones,
    sources
  };
}