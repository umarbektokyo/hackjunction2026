// Orchestrates one review: facts → claims → per-claim verification → requirement coverage → report.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { Claim, ClaimsResult, Coverage, ExecutionEvidence, Facts, Recommendation, Report, Verdict } from './types.ts';
import { computeFacts, reviewableDiff } from './facts.ts';
import { ensureWorktree } from './git.ts';
import { MODEL, askJson } from './llm.ts';
import { CLAIMS_SCHEMA, COVERAGE_SCHEMA, SYSTEM_REVIEWER, VERDICT_SCHEMA, claimsPrompt, coveragePrompt, verifyPrompt } from './prompts.ts';
import { runExecutionEvidence } from './exec.ts';
import { renderMarkdown } from './report.ts';

export const VERSION = '0.1.0';

export interface ReviewOptions {
  repo: string;
  base: string;
  head: string;
  requirementPath: string;
  outDir: string;
  workDir: string;
  exec: boolean;
  concurrency?: number;
  log?: (msg: string) => void;
}

function factsText(f: Facts): string {
  const lines = [
    `Risk tier: ${f.riskTier} (${f.riskReasons.join('; ') || 'no risk flags'})`,
    `Files by class: ${Object.entries(f.counts).map(([k, v]) => `${k}=${v.files} (+${v.additions}/-${v.deletions})`).join(', ')}`,
    `Tests changed: ${f.hasTests ? 'yes' : 'no'}; public API touched: ${f.touchesPublicApi ? 'yes' : 'no'}`,
  ];
  if (f.unrequested.length) lines.push(`Unrequested changes (deterministic): ${f.unrequested.map((u) => `${u.path} — ${u.reason}`).join(' | ')}`);
  return lines.join('\n');
}

function relevantDiff(facts: Facts, claim: Claim): string {
  const wanted = new Set(claim.files.map((p) => p.replace(/^\.?\//, '')));
  const picked = facts.files.filter((f) => wanted.has(f.path) || [...wanted].some((w) => f.path.endsWith(w) || w.endsWith(f.path)));
  const list = picked.length ? picked : facts.files.filter((f) => f.cls === 'source' || f.cls === 'template');
  return list
    .filter((f) => f.patch)
    .map((f) => `### ${f.path}\n${f.patch.slice(0, 40_000)}`)
    .join('\n') || '(no textual diff for these files; use the checkouts)';
}

async function mapLimit<T, R>(items: T[], limit: number, fn: (t: T, i: number) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i], i);
    }
  });
  await Promise.all(workers);
  return out;
}

export function recommend(verdicts: Verdict[], coverage: Coverage[], execution: ExecutionEvidence, facts: Facts): { recommendation: Recommendation; reasons: string[] } {
  const reasons: string[] = [];
  // Only a contradiction that matters (blocker/major) rejects; a minor one is a question for the human.
  const contradicted = verdicts.filter((v) => v.verdict === 'contradicted' && (v.severity === 'blocker' || v.severity === 'major'));
  const minorContradicted = verdicts.filter((v) => v.verdict === 'contradicted' && !(v.severity === 'blocker' || v.severity === 'major'));
  const blockers = verdicts.filter((v) => v.severity === 'blocker' && v.verdict !== 'supported');
  const unverifiable = verdicts.filter((v) => v.verdict === 'unverifiable');
  const missing = coverage.filter((c) => c.status === 'missing' || c.status === 'contradicted');
  if (contradicted.length) reasons.push(`${contradicted.length} claim(s) contradicted by evidence: ${contradicted.map((v) => v.claimId).join(', ')}`);
  if (blockers.length) reasons.push(`${blockers.length} blocker(s) not supported: ${blockers.map((v) => v.claimId).join(', ')}`);
  if (missing.length) reasons.push(`requirement items not met: ${missing.map((c) => c.requirementId).join(', ')}`);
  if (execution.ran && execution.head && (execution.head.failed > 0 || execution.head.buildFailed)) reasons.push('new tests fail or do not build on HEAD');
  if (execution.ran && execution.mutation && !execution.mutation.buildFailed && execution.mutation.failed === 0 && (execution.head?.total ?? 0) > 0) reasons.push('new tests also pass without the change (they do not test it)');
  if (contradicted.length || blockers.length || missing.length || (execution.ran && execution.head && (execution.head.failed > 0 || execution.head.buildFailed))) {
    return { recommendation: 'reject', reasons };
  }
  if (minorContradicted.length) reasons.push(`${minorContradicted.length} minor claim(s) contradicted (wording or docs, not behaviour): ${minorContradicted.map((v) => v.claimId).join(', ')}`);
  if (unverifiable.length) reasons.push(`${unverifiable.length} claim(s) routed to a human: ${unverifiable.map((v) => v.claimId).join(', ')}`);
  if (!execution.ran) reasons.push('no execution evidence (tests not run here)');
  if (facts.riskTier === 'high') reasons.push('high risk tier requires a human on every unverifiable item');
  const partial = coverage.filter((c) => c.status === 'partial' || c.status === 'not-checkable');
  if (partial.length) reasons.push(`requirement items only partially covered or not checkable: ${partial.map((c) => c.requirementId).join(', ')}`);
  if (minorContradicted.length || unverifiable.length || partial.length || (!execution.ran && facts.riskTier !== 'low')) return { recommendation: 'needs-human', reasons };
  reasons.push('every claim supported by cited evidence and every requirement item addressed');
  return { recommendation: 'accept-on-evidence', reasons };
}

export async function review(opts: ReviewOptions): Promise<Report> {
  const log = opts.log ?? (() => {});
  const repo = resolve(opts.repo);
  const requirement = readFileSync(opts.requirementPath, 'utf8');
  const requirementId = (requirement.match(/^#\s*(REQ-[\w-]+)/m)?.[1]) ?? opts.requirementPath;
  const cacheDir = join(opts.workDir, 'cache');
  let costUsd = 0;

  log(`facts: diffing ${opts.base}...${opts.head}`);
  const facts = computeFacts(repo, opts.base, opts.head);
  const diff = reviewableDiff(facts);
  log(`facts: ${facts.files.length} files, risk ${facts.riskTier}; ${diff.length} chars of reviewable diff`);

  log('claims: extracting');
  const claimsRes = await askJson<ClaimsResult>(SYSTEM_REVIEWER, claimsPrompt(requirement, facts.commitMessage, factsText(facts), diff), CLAIMS_SCHEMA, { cacheDir, label: 'claims' });
  costUsd += claimsRes.costUsd;
  const claims = claimsRes.data.claims;
  log(`claims: ${claims.length} claims${claimsRes.cached ? ' (cached)' : ''}`);

  const headDir = ensureWorktree(repo, facts.headSha, join(opts.workDir, 'head'));
  const baseDir = ensureWorktree(repo, facts.mergeBase, join(opts.workDir, 'base'));

  let execution: ExecutionEvidence = { ran: false, summary: 'Execution evidence disabled (run with --exec to run the added tests and the mutation check).' };
  if (opts.exec) {
    log('exec: running added tests on HEAD and with the source change reverted (slow)');
    execution = runExecutionEvidence({ repo, facts, headDir, workDir: opts.workDir });
    log(`exec: ${execution.summary}`);
  }
  const executionNote = execution.ran
    ? `Execution evidence available: ${execution.summary} (HEAD: ${JSON.stringify(execution.head)}; with source reverted: ${JSON.stringify(execution.mutation)}). Use it.`
    : `No execution evidence: ${execution.summary} Do not assume tests pass.`;

  log(`verify: ${claims.length} claims, concurrency ${opts.concurrency ?? 3}`);
  const verdicts = await mapLimit(claims, opts.concurrency ?? 3, async (claim) => {
    const prompt = verifyPrompt({
      requirement,
      claim: `${claim.id}: ${claim.statement} (requirement refs: ${claim.requirementRefs.join(', ') || 'none'})`,
      claimKind: claim.kind,
      claimFiles: claim.files,
      headDir,
      baseDir,
      relevantDiff: relevantDiff(facts, claim),
      executionNote,
    });
    const r = await askJson<Omit<Verdict, 'claimId'>>(SYSTEM_REVIEWER, prompt, VERDICT_SCHEMA, { cacheDir, label: `verify-${claim.id}`, readDir: headDir, maxTurns: 30 });
    costUsd += r.costUsd;
    const v: Verdict = { claimId: claim.id, ...r.data };
    // A "supported" verdict must point at code or a test; otherwise demote it. This rule is deterministic.
    if (v.verdict === 'supported' && !v.evidence.some((e) => (e.kind === 'code' || e.kind === 'test' || e.kind === 'execution') && e.file)) {
      v.verdict = 'unverifiable';
      v.refusedBecause = (v.refusedBecause ? v.refusedBecause + ' ' : '') + 'Demoted by policy: "supported" without a code/test pointer.';
      v.humanQuestion ??= `Confirm ${claim.id} by reading the implementing code; the reviewer cited none.`;
    }
    log(`verify: ${claim.id} → ${v.verdict} (${v.confidence})${r.cached ? ' cached' : ''}`);
    return v;
  });

  // Deterministic verdicts for unrequested build changes the model may have skipped.
  for (const u of facts.unrequested) {
    if (!claims.some((c) => c.kind === 'scope' && c.files.some((f) => f.endsWith(u.path)))) {
      const id = `S${claims.length + 1}`;
      claims.push({ id, statement: `The change modifies ${u.path}, which no requirement item asks for.`, kind: 'scope', files: [u.path], requirementRefs: [], source: 'inferred' });
      verdicts.push({ claimId: id, verdict: 'supported', confidence: 'high', basis: 'deterministic diff fact', evidence: [{ kind: 'deterministic', file: u.path, note: u.reason }], reasoning: 'Found by file classification, independent of the model.', severity: 'minor', humanQuestion: `Is the change to ${u.path} wanted in this PR, or should it be split out?` });
    }
  }

  log('coverage: mapping requirement items to verified claims');
  const cav = claims.map((c) => {
    const v = verdicts.find((x) => x.claimId === c.id)!;
    return `- ${c.id} [${c.kind}] (${c.requirementRefs.join(', ') || 'no ref'}): ${c.statement}\n  verdict: ${v.verdict} (${v.confidence}); ${v.reasoning}`;
  }).join('\n');
  const cov = await askJson<{ coverage: Coverage[] }>(SYSTEM_REVIEWER, coveragePrompt(requirement, cav), COVERAGE_SCHEMA, { cacheDir, label: 'coverage' });
  costUsd += cov.costUsd;

  const routedToHuman = verdicts
    .filter((v) => v.verdict !== 'supported' || v.humanQuestion)
    .filter((v) => v.humanQuestion || v.refusedBecause)
    .map((v) => ({ claimId: v.claimId, question: v.humanQuestion ?? 'Review this claim.', why: v.refusedBecause ?? `${v.verdict}: ${v.reasoning}` }));

  const { recommendation, reasons } = recommend(verdicts, cov.data.coverage, execution, facts);

  const report: Report = {
    tool: 'cev',
    version: VERSION,
    generatedAt: new Date().toISOString(),
    requirementId,
    requirementPath: opts.requirementPath,
    facts: { ...facts, files: facts.files.map((f) => ({ ...f, patch: '' })) },
    model: MODEL,
    summary: claimsRes.data.summary,
    requirementItems: claimsRes.data.requirementItems,
    claims,
    verdicts,
    coverage: cov.data.coverage,
    execution,
    routedToHuman,
    recommendation,
    recommendationReasons: reasons,
    costUsd: Number(costUsd.toFixed(3)),
  };

  mkdirSync(opts.outDir, { recursive: true });
  writeFileSync(join(opts.outDir, 'report.json'), JSON.stringify(report, null, 2));
  writeFileSync(join(opts.outDir, 'report.md'), renderMarkdown(report));
  log(`done: ${recommendation}; wrote ${join(opts.outDir, 'report.md')} (model cost ≈ $${report.costUsd})`);
  return report;
}
