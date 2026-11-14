#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { resolve } from 'node:path';
import { computeFacts } from './facts.ts';
import { review } from './review.ts';
import { decide, readDecisions } from './decide.ts';

const USAGE = `cev — claims → evidence → verdict review for agent-written changes

  cev review  --repo <path> --base <rev> --head <rev> --requirement <file> --out <dir> [--exec] [--work <dir>] [--concurrency N]
  cev facts   --repo <path> --base <rev> --head <rev>
  cev rerender --report <dir>              recompute recommendation + report.md from report.json (no model calls)
  cev decide  --report <dir> --by "<name>" (accept|reject) [--answer C1="what I checked"]... [--override "<reason>"] [--note "..."] [--log decisions/log.jsonl]
  cev log     [--log decisions/log.jsonl]

Model: the logged-in \`claude\` CLI (CEV_MODEL=sonnet|opus|haiku, default sonnet).`;

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const { values, positionals } = parseArgs({
    args: rest,
    allowPositionals: true,
    options: {
      repo: { type: 'string' },
      base: { type: 'string', default: 'origin/master' },
      head: { type: 'string' },
      requirement: { type: 'string' },
      out: { type: 'string' },
      work: { type: 'string', default: '.work' },
      exec: { type: 'boolean', default: false },
      concurrency: { type: 'string', default: '3' },
      report: { type: 'string' },
      by: { type: 'string' },
      answer: { type: 'string', multiple: true, default: [] },
      override: { type: 'string' },
      note: { type: 'string' },
      log: { type: 'string', default: 'decisions/log.jsonl' },
    },
  });

  switch (cmd) {
    case 'facts': {
      if (!values.repo || !values.head) throw new Error('--repo and --head required');
      const f = computeFacts(resolve(values.repo), values.base!, values.head);
      console.log(JSON.stringify({ ...f, files: f.files.map(({ patch, ...x }) => x) }, null, 2));
      return;
    }
    case 'review': {
      if (!values.repo || !values.head || !values.requirement || !values.out) throw new Error('--repo, --head, --requirement and --out required');
      const headSlug = values.head.replace(/[^\w.-]+/g, '_');
      await review({
        repo: values.repo,
        base: values.base!,
        head: values.head,
        requirementPath: values.requirement,
        outDir: values.out,
        workDir: resolve(values.work!, headSlug),
        exec: values.exec!,
        concurrency: Number(values.concurrency),
        log: (m) => console.error(`[cev] ${m}`),
      });
      return;
    }
    case 'rerender': {
      // Recompute recommendation and Markdown from an existing report.json (no model calls).
      if (!values.report) throw new Error('--report required');
      const { readFileSync, writeFileSync } = await import('node:fs');
      const { join } = await import('node:path');
      const { recommend, routed } = await import('./review.ts');
      const { renderMarkdown } = await import('./report.ts');
      const r = JSON.parse(readFileSync(join(values.report, 'report.json'), 'utf8'));
      const { recommendation, reasons } = recommend(r.verdicts, r.coverage, r.execution, r.facts);
      r.routedToHuman = routed(r.verdicts);
      r.recommendation = recommendation;
      r.recommendationReasons = reasons;
      writeFileSync(join(values.report, 'report.json'), JSON.stringify(r, null, 2));
      writeFileSync(join(values.report, 'report.md'), renderMarkdown(r));
      console.log(`${r.requirementId}: ${recommendation}`);
      return;
    }
    case 'decide': {
      const decision = positionals[0];
      if (!values.report || !values.by || (decision !== 'accept' && decision !== 'reject')) throw new Error('--report, --by and accept|reject required');
      const answers: Record<string, string> = {};
      for (const a of values.answer!) {
        const i = a.indexOf('=');
        if (i < 0) throw new Error(`--answer must be <claimId>=<text>: ${a}`);
        answers[a.slice(0, i)] = a.slice(i + 1);
      }
      const d = decide({ reportDir: values.report, by: values.by, decision, answers, override: values.override, note: values.note, logPath: values.log! });
      console.log(JSON.stringify(d, null, 2));
      return;
    }
    case 'log': {
      for (const d of readDecisions(values.log!)) console.log(`${d.at}  ${d.decision.padEnd(6)} ${d.requirementId.padEnd(10)} ${d.head.padEnd(24)} by ${d.by} (report ${d.reportHash}${d.override ? ', OVERRIDE: ' + d.override : ''})`);
      return;
    }
    default:
      console.log(USAGE);
      process.exit(cmd ? 1 : 0);
  }
}

main().catch((e) => {
  console.error(`error: ${e.message}`);
  process.exit(1);
});
