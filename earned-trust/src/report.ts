import type { Report, Verdict } from './types.ts';

const icon: Record<Verdict['verdict'], string> = { supported: '✅', contradicted: '❌', unverifiable: '🟡' };
const recText: Record<Report['recommendation'], string> = {
  'accept-on-evidence': 'ACCEPT ON EVIDENCE — a named human can approve from this report without a full read',
  'needs-human': 'NEEDS A HUMAN — approve only after answering the routed questions',
  'reject': 'REJECT — evidence contradicts the change or a requirement item is not met',
};

function loc(e: { file?: string; lineStart?: number; lineEnd?: number }): string {
  if (!e.file) return '';
  if (e.lineStart && e.lineEnd && e.lineEnd !== e.lineStart) return `\`${e.file}:${e.lineStart}-${e.lineEnd}\``;
  if (e.lineStart) return `\`${e.file}:${e.lineStart}\``;
  return `\`${e.file}\``;
}

export function renderMarkdown(r: Report): string {
  const f = r.facts;
  const out: string[] = [];
  out.push(`# Trust report — ${r.requirementId} · \`${f.head}\``);
  out.push('');
  out.push(`**Recommendation: ${recText[r.recommendation]}**`);
  out.push('');
  for (const reason of r.recommendationReasons) out.push(`- ${reason}`);
  out.push('');
  out.push(`> ${r.summary}`);
  out.push('');
  out.push('## At a glance');
  out.push('');
  out.push('| | |');
  out.push('|---|---|');
  out.push(`| Requirement | ${r.requirementId} (\`${r.requirementPath}\`) |`);
  out.push(`| Change | \`${f.base}\` → \`${f.head}\` (${f.headSha.slice(0, 10)}) |`);
  out.push(`| Risk tier | **${f.riskTier}** — ${f.riskReasons.join('; ') || 'no flags'} |`);
  out.push(`| Files | ${Object.entries(f.counts).map(([k, v]) => `${k} ${v.files}`).join(', ')} |`);
  out.push(`| Claims | ${r.claims.length}: ${r.verdicts.filter((v) => v.verdict === 'supported').length} supported, ${r.verdicts.filter((v) => v.verdict === 'contradicted').length} contradicted, ${r.verdicts.filter((v) => v.verdict === 'unverifiable').length} unverifiable |`);
  out.push(`| Execution evidence | ${r.execution.summary} |`);
  out.push(`| Model | ${r.model}; cost ≈ $${r.costUsd}; generated ${r.generatedAt} |`);
  out.push('');

  out.push('## Requirement coverage');
  out.push('');
  out.push('| Item | Status | Via | Note |');
  out.push('|---|---|---|---|');
  for (const c of r.coverage) {
    const txt = r.requirementItems.find((i) => i.id === c.requirementId)?.text ?? '';
    out.push(`| **${c.requirementId}** ${txt.slice(0, 90)}${txt.length > 90 ? '…' : ''} | ${c.status} | ${c.claimIds.join(', ') || '—'} | ${c.note} |`);
  }
  out.push('');

  out.push('## Claims and verdicts');
  out.push('');
  for (const c of r.claims) {
    const v = r.verdicts.find((x) => x.claimId === c.id);
    if (!v) continue;
    out.push(`### ${icon[v.verdict]} ${c.id} · ${c.kind} · ${v.verdict} (${v.confidence}, ${v.severity})`);
    out.push('');
    out.push(`**Claim:** ${c.statement}${c.requirementRefs.length ? ` _(→ ${c.requirementRefs.join(', ')})_` : ''}`);
    out.push('');
    out.push(`**Basis:** ${v.basis}`);
    out.push('');
    out.push(`**Reasoning:** ${v.reasoning}`);
    out.push('');
    if (v.evidence.length) {
      out.push('**Evidence:**');
      for (const e of v.evidence) out.push(`- ${e.kind} ${loc(e)} — ${e.note}`);
      out.push('');
    }
    if (v.refusedBecause) out.push(`**Refused to decide because:** ${v.refusedBecause}\n`);
    if (v.humanQuestion) out.push(`**For the human:** ${v.humanQuestion}\n`);
  }

  out.push('## Routed to a named human');
  out.push('');
  if (r.routedToHuman.length === 0) out.push('Nothing. Every claim is supported by cited evidence.');
  for (const h of r.routedToHuman) out.push(`- **${h.claimId}** — ${h.question}\n  _Why:_ ${h.why}`);
  out.push('');

  if (r.execution.ran && r.execution.log) {
    out.push('## Execution log');
    out.push('');
    out.push('```');
    out.push(r.execution.log.slice(0, 6000));
    out.push('```');
    out.push('');
  }

  out.push('## Changed files');
  out.push('');
  out.push('| File | Class | +/- |');
  out.push('|---|---|---|');
  const shown = f.files.filter((x) => x.cls !== 'generated' && x.cls !== 'snapshot');
  for (const x of shown) out.push(`| \`${x.path}\` | ${x.cls} | +${x.additions} −${x.deletions} |`);
  const hidden = f.files.length - shown.length;
  if (hidden) out.push(`| _${hidden} generated/snapshot files_ | generated | |`);
  out.push('');
  out.push('---');
  out.push(`_Sign-off: \`cev decide --report <this dir> --by "Name" accept|reject\` records who accepted, what they saw, and the report hash._`);
  return out.join('\n');
}
