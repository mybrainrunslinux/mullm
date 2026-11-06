export function buildPlan(input, sources = []) {
  const { name = '', audience = '', competitors = '', focus = '' } = input || {};
  const warnings = [];

  const uniqueCompanyNames = [];
  const seen = new Set();
  competitors.split('\n').map(n => n.trim()).filter(n => n.length > 0).forEach(company => {
    const key = company.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      uniqueCompanyNames.push(company);
    }
  });

  const comparisons = uniqueCompanyNames.map(company => {
    const matchingSources = sources.filter(s =>
      s.owner && s.owner.toLowerCase() === company.toLowerCase()
    );

    const evidenceCount = matchingSources.length;
    const reviewedCount = matchingSources.filter(s => s.reviewed === true).length;
    const claims = matchingSources.map(s => s.claim).filter(c => c !== undefined && c !== null);

    if (evidenceCount === 0) {
      warnings.push(`No evidence found for ${company}.`);
    }

    return {
      name: company,
      evidence_count: evidenceCount,
      reviewed_count: reviewedCount,
      claims: claims
    };
  });

  const citations = sources
    .filter(s => s.url)
    .map(s => s.url);

  const totalEvidence = comparisons.reduce((sum, c) => sum + c.evidence_count, 0);
  const totalReviewed = comparisons.reduce((sum, c) => sum + c.reviewed_count, 0);
  const totalClaims = comparisons.reduce((sum, c) => sum + c.claims.length, 0);

  const sections = [];

  if (uniqueCompanyNames.length > 0) {
    const companySummary = comparisons.map(c => `${c.name} (${c.evidence_count} evidence, ${c.reviewed_count} reviewed)`).join(', ');
    sections.push({
      title: 'Companies',
      items: [companySummary]
    });
  }

  sections.push({
    title: 'Counts',
    items: [
      `Total evidence: ${totalEvidence}`,
      `Total reviewed: ${totalReviewed}`,
      `Total claims: ${totalClaims}`
    ]
  });

  const supportedClaims = comparisons.flatMap(c => c.claims.map(claim => `${c.name}: ${claim}`));
  if (supportedClaims.length > 0) {
    sections.push({
      title: 'Supported Claims',
      items: supportedClaims
    });
  }

  const evidenceGaps = comparisons.filter(c => c.evidence_count === 0).map(c => c.name);
  if (evidenceGaps.length > 0) {
    sections.push({
      title: 'Evidence Gaps',
      items: evidenceGaps.map(g => `No evidence for ${g}`)
    });
  }

  sections.push({
    title: 'Next Actions',
    items: [
      'Review unverified evidence.',
      'Add missing sources.',
      'Validate claims against sources.'
    ]
  });

  return {
    summary: `Plan for ${name || 'Untitled'} targeting ${audience || 'general audience'}.`,
    metrics: [
      { label: 'Companies', value: uniqueCompanyNames.length },
      { label: 'Evidence', value: totalEvidence },
      { label: 'Claims', value: totalClaims }
    ],
    sections: sections,
    warnings: warnings,
    comparisons: comparisons,
    citations: citations
  };
}