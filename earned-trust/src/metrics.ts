// Trust measured, not assumed: what the reports and the decision log say about review load and outcomes.
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Report } from './types.ts';
import type { Decision } from './decide.ts';

const READ_BY_MODEL = new Set(['source', 'template', 'test', 'docs']);

export interface ChangeMetrics {
  requirementId: string;
  riskTier: string;
  changedLines: number;
  /** Changed lines in files the model reads (generated churn and snapshots are counted, not read). */
  modelReadLines: number;
  claims: number;
  supported: number;
  contradicted: number;
  unverifiable: number;
  routed: number;
  /** Distinct lines cited as evidence for the routed items: what the human has to look at. Includes unchanged context. */
  humanReadLines: number;
  /** Distinct file:range pointers behind humanReadLines: the places the human opens. */
  humanReadPlaces: number;
  recommendation: Report['recommendation'];
  decision?: Decision;
  /** Human did not overrule the AI: no accept over a "reject", no reject of an "accept-on-evidence". */
  agreed?: boolean;
  minutesToDecision?: number;
  costUsd: number;
}

export function changeMetrics(r: Report, decisions: Decision[]): ChangeMetrics {
  const files = r.facts.files;
  const lines = (pred: (cls: string) => boolean) => files.filter((f) => pred(f.cls)).reduce((n, f) => n + f.additions + f.deletions, 0);
  const count = (v: string) => r.verdicts.filter((x) => x.verdict === v).length;

  const routedIds = new Set(r.routedToHuman.map((h) => h.claimId));
  const cited = new Set<string>();
  const places = new Set<string>();
  for (const v of r.verdicts.filter((x) => routedIds.has(x.claimId))) {
    for (const e of v.evidence) {
      if (!e.file || !e.lineStart) continue;
      places.add(`${e.file}:${e.lineStart}-${e.lineEnd ?? e.lineStart}`);
      for (let l = e.lineStart; l <= (e.lineEnd ?? e.lineStart); l++) cited.add(`${e.file}:${l}`);
    }
  }

  // The latest decision on this exact head wins; earlier ones are history.
  const d = decisions.filter((x) => x.requirementId === r.requirementId && x.headSha === r.facts.headSha).at(-1);
  return {
    requirementId: r.requirementId,
    riskTier: r.facts.riskTier,
    changedLines: lines(() => true),
    modelReadLines: lines((c) => READ_BY_MODEL.has(c)),
    claims: r.claims.length,
    supported: count('supported'),
    contradicted: count('contradicted'),
    unverifiable: count('unverifiable'),
    routed: r.routedToHuman.length,
    humanReadLines: cited.size,
    humanReadPlaces: places.size,
    recommendation: r.recommendation,
    decision: d,
    agreed: d && (d.decision === 'reject' ? r.recommendation !== 'accept-on-evidence' : !d.override),
    minutesToDecision: d && Math.round((Date.parse(d.at) - Date.parse(r.generatedAt)) / 60000),
    costUsd: r.costUsd,
  };
}

export function loadReports(dir: string): Report[] {
  return readdirSync(dir)
    .map((name) => join(dir, name, 'report.json'))
    .filter((p) => existsSync(p))
    .map((p) => JSON.parse(readFileSync(p, 'utf8')));
}

const pct = (a: number, b: number) => (b ? `${Math.round((100 * a) / b)}%` : 'n/a');
const sum = (xs: ChangeMetrics[], k: keyof ChangeMetrics) => xs.reduce((n, x) => n + (x[k] as number), 0);

export function renderMetrics(ms: ChangeMetrics[]): string {
  const out: string[] = [];
  out.push('# Trust metrics');
  out.push('');
  out.push('Computed by `cev metrics` from `reports/*/report.json` and `decisions/log.jsonl`. Nothing here is typed in by hand.');
  out.push('');
  out.push('## Per change');
  out.push('');
  out.push('| Change | Risk | Changed lines | Read by model | Claims (S / C / U) | Routed | Human reads (lines in places) | Recommendation | Decision | Agreed | Min. to decision | Model cost |');
  out.push('|---|---|---|---|---|---|---|---|---|---|---|---|');
  for (const m of ms) {
    const d = m.decision;
    out.push(
      `| ${m.requirementId} | ${m.riskTier} | ${m.changedLines} | ${m.modelReadLines} | ${m.claims} (${m.supported} / ${m.contradicted} / ${m.unverifiable}) | ${m.routed} | ${m.humanReadLines} in ${m.humanReadPlaces} | ${m.recommendation} | ${d ? `${d.decision} by ${d.by}` : 'pending'} | ${d ? (m.agreed ? 'yes' : '**no**') : ''} | ${m.minutesToDecision ?? ''} | $${m.costUsd} |`,
    );
  }
  out.push('');

  const decided = ms.filter((m) => m.decision);
  const findings = sum(ms, 'contradicted');
  // A finding is accepted when the human rejected the change on it, or answered it before accepting.
  const acceptedFindings = decided.reduce((n, m) => {
    if (m.decision!.decision === 'reject') return n + m.contradicted;
    return n + Object.keys(m.decision!.answered).length;
  }, 0);
  const decidedFindings = decided.reduce((n, m) => n + (m.decision!.decision === 'reject' ? m.contradicted : m.routed), 0);
  const minutes = decided.map((m) => m.minutesToDecision!).sort((a, b) => a - b);

  out.push('## Across changes');
  out.push('');
  out.push('| Measure | Value | What it tells you |');
  out.push('|---|---|---|');
  out.push(`| Changes routed to a human | ${ms.filter((m) => m.recommendation !== 'accept-on-evidence').length} of ${ms.length} | Share the AI would not clear alone. Should fall per category only while reverts stay flat. |`);
  out.push(`| Claims routed to a human | ${sum(ms, 'routed')} of ${sum(ms, 'claims')} (${pct(sum(ms, 'routed'), sum(ms, 'claims'))}) | The questions the AI refused to decide. |`);
  out.push(`| Review load | ${sum(ms, 'humanReadLines')} lines in ${sum(ms, 'humanReadPlaces')} places, against ${sum(ms, 'changedLines')} changed lines | Lines cited as evidence for the routed items, including unchanged code the question needs. A full read is the whole diff plus that context. |`);
  out.push(`| Findings (contradicted claims) | ${findings} | What the AI found that the change gets wrong. |`);
  out.push(`| Findings accepted by the human | ${decidedFindings ? `${acceptedFindings} of ${decidedFindings} decided (${pct(acceptedFindings, decidedFindings)})` : 'no decisions yet'} | Are the findings real? Rejected findings are false alarms and count against the verifier. |`);
  out.push(`| Human agreed with recommendation | ${decided.length ? `${decided.filter((m) => m.agreed).length} of ${decided.length}` : 'no decisions yet'} | An override is logged with its reason. |`);
  out.push(`| Time to decision (median) | ${minutes.length ? `${minutes[Math.floor(minutes.length / 2)]} min` : 'no decisions yet'} | From report generated to signed decision. |`);
  out.push(`| Model cost | $${sum(ms, 'costUsd').toFixed(2)} | For all reports. |`);
  out.push(`| Reverts and incidents of accepted changes | not measurable yet | Needs merges. Source: \`git log --grep "This reverts commit <headSha>"\` and incident links on the merged SHA. The first revert in a category narrows auto-clear for it. |`);
  out.push('');
  return out.join('\n');
}
