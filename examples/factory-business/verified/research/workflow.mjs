export function buildPlan(input, sources = []) {
  const { name, audience, hypothesis, method, participants, days, decision } = input || {};
  const warnings = [];
  const p = Number(participants) || 0;
  const d = Number(days) || 0;

  if (p <= 0) warnings.push('Participants must be greater than 0.');
  if (d <= 0) warnings.push('Days must be greater than 0.');

  const schedule = [];
  if (d > 0) {
    schedule.push({ day: 1, label: 'Recruit' });
    schedule.push({ day: 2, label: 'Collect' });
    schedule.push({ day: 3, label: 'Synthesize' });
    schedule.push({ day: d, label: 'Decide' });
  }

  const questions = [
    'Walk me through the last time your team encountered this problem?',
    'Which step took the most effort, and what happened?',
    'What have you already tried, and how did it work?',
    'What evidence would make you choose a different approach?'
  ];

  const summary = `Plan for "${name || 'Untitled Study'}" to test: "${hypothesis || 'No hypothesis provided'}".`;

  return {
    summary,
    metrics: [
      { label: 'Target participants', value: p },
      { label: 'Study days', value: d },
      { label: 'Evidence count', value: sources.length }
    ],
    sections: [
      {
        title: 'Hypothesis (Untested)',
        items: [hypothesis || 'No hypothesis provided']
      },
      {
        title: 'Interview Questions',
        items: questions
      },
      {
        title: 'Study Schedule',
        items: schedule.map(s => s.label)
      },
      {
        title: 'Decision',
        items: [decision || 'No decision specified. Revisit when ready.']
      }
    ],
    warnings,
    name,
    audience,
    hypothesis,
    method,
    participants: p,
    days: d,
    decision,
    questions,
    schedule,
    evidence_count: sources.length,
    sources
  };
}