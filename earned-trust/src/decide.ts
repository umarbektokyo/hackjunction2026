// The accountable-human step: a named person signs the evidence bundle, not the diff.
import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Report } from './types.ts';

export interface Decision {
  at: string;
  by: string;
  decision: 'accept' | 'reject';
  requirementId: string;
  head: string;
  headSha: string;
  reportHash: string;
  recommendation: Report['recommendation'];
  /** The routed questions the human answered, by claim id. */
  answered: Record<string, string>;
  override?: string;
  note?: string;
}

export function decide(opts: { reportDir: string; by: string; decision: 'accept' | 'reject'; answers: Record<string, string>; override?: string; note?: string; logPath: string }): Decision {
  const raw = readFileSync(join(opts.reportDir, 'report.json'), 'utf8');
  const report: Report = JSON.parse(raw);
  const reportHash = createHash('sha256').update(raw).digest('hex').slice(0, 16);

  if (opts.decision === 'accept') {
    const open = report.routedToHuman.filter((h) => !opts.answers[h.claimId]);
    if (open.length) {
      throw new Error(`Cannot accept: ${open.length} question(s) routed to you are unanswered: ${open.map((h) => h.claimId).join(', ')}. Pass --answer <claimId>="<what you checked>" for each.`);
    }
    if (report.recommendation === 'reject' && !opts.override) {
      throw new Error('Cannot accept a report whose recommendation is "reject" without --override "<reason>".');
    }
  }

  const d: Decision = {
    at: new Date().toISOString(),
    by: opts.by,
    decision: opts.decision,
    requirementId: report.requirementId,
    head: report.facts.head,
    headSha: report.facts.headSha,
    reportHash,
    recommendation: report.recommendation,
    answered: opts.answers,
    override: opts.override,
    note: opts.note,
  };
  mkdirSync(join(opts.logPath, '..'), { recursive: true });
  appendFileSync(opts.logPath, JSON.stringify(d) + '\n');
  return d;
}

export function readDecisions(logPath: string): Decision[] {
  if (!existsSync(logPath)) return [];
  return readFileSync(logPath, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
}
