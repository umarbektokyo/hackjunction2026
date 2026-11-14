// Execution evidence: run the tests the change added on HEAD, then again with the non-test
// changes reverted. A test that passes both times does not test the change.
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import type { ChangedFile, ExecutionEvidence, Facts, TestRun } from './types.ts';
import { ensureWorktree, show } from './git.ts';

export interface ExecOptions {
  repo: string;
  facts: Facts;
  headDir: string;
  workDir: string;
  /** Test project directories to run (relative to repo root). Defaults to projects containing changed test files. */
  testProjects?: string[];
  timeoutMs?: number;
}

function dotnetAvailable(): boolean {
  return spawnSync('dotnet', ['--version'], { encoding: 'utf8' }).status === 0;
}

function findProject(repoDir: string, testFile: string): string | null {
  let d = dirname(testFile);
  while (d && d !== '.') {
    const full = join(repoDir, d);
    if (existsSync(full)) {
      const r = spawnSync('sh', ['-c', `ls "${full}"/*.csproj 2>/dev/null | head -1`], { encoding: 'utf8' });
      if (r.stdout.trim()) return d;
    }
    d = dirname(d);
  }
  return null;
}

function parseRun(out: string, durationMs: number): TestRun {
  // "Passed! - Failed: 0, Passed: 5, Skipped: 0, Total: 5, Duration: ..." or "Failed! - Failed: 3, Passed: 2, ..."
  const m = out.match(/(Passed|Failed)!\s+-\s+Failed:\s+(\d+),\s+Passed:\s+(\d+),\s+Skipped:\s+(\d+),\s+Total:\s+(\d+)/);
  const failedTests = [...out.matchAll(/^\s+Failed\s+(\S+)/gm)].map((x) => x[1]);
  if (!m) {
    return { passed: 0, failed: 0, skipped: 0, total: 0, buildFailed: /error\s+(CS|MSB)\d+/.test(out) || !/Test run for/.test(out), durationMs, failedTests };
  }
  return { failed: Number(m[2]), passed: Number(m[3]), skipped: Number(m[4]), total: Number(m[5]), buildFailed: false, durationMs, failedTests };
}

function testClassFilter(files: ChangedFile[]): string {
  const classes = files
    .filter((f) => f.cls === 'test' && f.status === 'A')
    .map((f) => f.path.split('/').pop()!.replace(/\.cs$/, ''));
  return classes.map((c) => `FullyQualifiedName~${c}`).join('|');
}

function runDotnetTest(cwd: string, project: string, filter: string, timeoutMs: number): { out: string; run: TestRun } {
  const started = Date.now();
  const args = ['test', project, '-v', 'q', '--nologo'];
  if (filter) args.push('--filter', filter);
  const r = spawnSync('dotnet', args, {
    cwd,
    encoding: 'utf8',
    env: { ...process.env, DOTNET_CLI_TELEMETRY_OPTOUT: '1', DOTNET_NOLOGO: '1' },
    maxBuffer: 64 * 1024 * 1024,
    timeout: timeoutMs,
  });
  const out = (r.stdout ?? '') + '\n' + (r.stderr ?? '');
  return { out, run: parseRun(out, Date.now() - started) };
}

export function runExecutionEvidence(opts: ExecOptions): ExecutionEvidence {
  const { repo, facts, headDir, workDir } = opts;
  const timeoutMs = opts.timeoutMs ?? 20 * 60 * 1000;
  if (!dotnetAvailable()) {
    return { ran: false, summary: 'dotnet SDK not found on PATH; tests were not executed. Execution evidence is missing, so test claims stay unverifiable.' };
  }
  const newTests = facts.files.filter((f) => f.cls === 'test' && f.status === 'A');
  if (newTests.length === 0) {
    return { ran: false, summary: 'The change adds no test files; there is nothing to execute that targets the change.' };
  }
  const projects = opts.testProjects ?? [...new Set(newTests.map((f) => findProject(headDir, f.path)).filter((p): p is string => !!p))];
  if (projects.length === 0) {
    return { ran: false, summary: 'Could not locate a test project for the added tests.' };
  }
  const filter = testClassFilter(facts.files);
  const log: string[] = [];
  const headRuns: TestRun[] = [];
  const mutRuns: TestRun[] = [];
  let command = '';

  // Mutation worktree: HEAD with every non-test, non-docs source file reset to BASE.
  const mutDir = join(workDir, 'mutation');
  ensureWorktree(repo, facts.headSha, mutDir);
  const reverted: string[] = [];
  for (const f of facts.files) {
    if (f.cls === 'source' || f.cls === 'template') {
      const baseContent = show(repo, facts.mergeBase, f.path);
      const target = join(mutDir, f.path);
      if (baseContent === null) {
        spawnSync('rm', ['-f', target]);
      } else {
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(target, baseContent);
      }
      reverted.push(f.path);
    }
  }

  for (const project of projects) {
    command = `dotnet test ${project} --filter "${filter}"`;
    log.push(`## HEAD: ${command}`);
    const h = runDotnetTest(headDir, project, filter, timeoutMs);
    headRuns.push(h.run);
    log.push(h.out.split('\n').filter((l) => /Passed!|Failed!|error|Failed\s+\S+|Test run/.test(l)).slice(0, 60).join('\n'));

    log.push(`## MUTATION (reverted ${reverted.length} source file(s): ${reverted.join(', ')}): ${command}`);
    const m = runDotnetTest(mutDir, project, filter, timeoutMs);
    mutRuns.push(m.run);
    log.push(m.out.split('\n').filter((l) => /Passed!|Failed!|error|Failed\s+\S+|Test run/.test(l)).slice(0, 60).join('\n'));
  }

  const sum = (runs: TestRun[]): TestRun => runs.reduce(
    (a, b) => ({
      passed: a.passed + b.passed,
      failed: a.failed + b.failed,
      skipped: a.skipped + b.skipped,
      total: a.total + b.total,
      buildFailed: a.buildFailed || b.buildFailed,
      durationMs: a.durationMs + b.durationMs,
      failedTests: [...a.failedTests, ...b.failedTests],
    }),
    { passed: 0, failed: 0, skipped: 0, total: 0, buildFailed: false, durationMs: 0, failedTests: [] },
  );
  const head = sum(headRuns);
  const mutation = sum(mutRuns);

  let summary: string;
  if (head.buildFailed) summary = 'HEAD does not build or the tests could not be discovered; the change cannot be trusted on execution evidence.';
  else if (head.failed > 0) summary = `${head.failed} of ${head.total} new tests FAIL on HEAD: the change does not do what its own tests say.`;
  else if (mutation.buildFailed) summary = `All ${head.total} new tests pass on HEAD. With the source change reverted the tests do not compile, so they depend on the change (weak positive signal).`;
  else if (mutation.failed === 0) summary = `All ${head.total} new tests pass on HEAD and ALSO pass with the source change reverted: these tests do not test the change.`;
  else summary = `All ${head.total} new tests pass on HEAD; ${mutation.failed} of ${mutation.total} fail with the source change reverted, so ${mutation.failed} test(s) genuinely exercise the change.`;

  return { ran: true, command, summary, head, mutation, log: log.join('\n') };
}
