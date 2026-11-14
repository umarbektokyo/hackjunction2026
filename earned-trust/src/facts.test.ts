import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classify } from './facts.ts';
import { recommend } from './review.ts';
import type { Facts, Verdict } from './types.ts';

test('file classification', () => {
  assert.equal(classify('src/MessagePack.SourceGenerator/CodeAnalysis/TypeCollector.cs'), 'source');
  assert.equal(classify('tests/MessagePack.SourceGenerator.Tests/GenericsFormatterTests.cs'), 'test');
  assert.equal(classify('src/X/Transforms/FormatterTemplate.tt'), 'template');
  assert.equal(classify('src/X/Resources/Foo.g.cs'), 'generated');
  assert.equal(classify('tests/X/Resources/Case.verified.cs'), 'snapshot');
  assert.equal(classify('Directory.Packages.props'), 'build');
  assert.equal(classify('doc/analyzers/MsgPack004.md'), 'docs');
});

const facts = { riskTier: 'medium' } as Facts;
const v = (claimId: string, verdict: Verdict['verdict'], severity: Verdict['severity'] = 'major'): Verdict =>
  ({ claimId, verdict, severity, confidence: 'high', basis: '', evidence: [], reasoning: '' });
const noExec = { ran: false, summary: '' };

test('a contradicted claim rejects', () => {
  const r = recommend([v('C1', 'supported'), v('C2', 'contradicted')], [], noExec, facts);
  assert.equal(r.recommendation, 'reject');
});

test('an unverifiable claim routes to a human', () => {
  const r = recommend([v('C1', 'supported'), v('C2', 'unverifiable')], [], noExec, facts);
  assert.equal(r.recommendation, 'needs-human');
});

test('all supported, all covered, low risk accepts on evidence', () => {
  const r = recommend([v('C1', 'supported')], [{ requirementId: 'F1', status: 'addressed', claimIds: ['C1'], note: '' }], noExec, { riskTier: 'low' } as Facts);
  assert.equal(r.recommendation, 'accept-on-evidence');
});

test('tests that pass without the change are flagged', () => {
  const exec = { ran: true, summary: '', head: { passed: 3, failed: 0, skipped: 0, total: 3, buildFailed: false, durationMs: 0, failedTests: [] }, mutation: { passed: 3, failed: 0, skipped: 0, total: 3, buildFailed: false, durationMs: 0, failedTests: [] } };
  const r = recommend([v('C1', 'supported')], [], exec, facts);
  assert.ok(r.reasons.some((x) => /do not test it/.test(x)));
});
