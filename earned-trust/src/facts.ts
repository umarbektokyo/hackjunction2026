import type { ChangedFile, ClassCount, Facts, FileClass, RiskTier } from './types.ts';
import { commitMessage, filePatch, mergeBase, nameStatus, numstat, revParse } from './git.ts';

const MAX_PATCH_CHARS = 60_000;

export function classify(path: string): FileClass {
  const p = path.replace(/\\/g, '/');
  const name = p.split('/').pop() ?? p;
  if (/\.g\.cs$/i.test(name) || /\/obj\//.test(p) || /\.verified\./.test(name)) {
    return /\.verified\./.test(name) ? 'snapshot' : 'generated';
  }
  if (/\.tt$/i.test(name)) return 'template';
  if (/\.(md|txt|rst)$/i.test(name) || /^doc(s)?\//.test(p)) return 'docs';
  if (/\.(csproj|props|targets|sln|json|yml|yaml|config|rsp|nuspec)$/i.test(name) || name === 'global.json') return 'build';
  if (/(^|\/)tests?\//i.test(p) || /Tests?\.cs$/.test(name) || /\.Tests\//.test(p)) return 'test';
  if (/\.(cs|ts|js|py|java|go|rs|cpp|h)$/i.test(name)) return 'source';
  return 'other';
}

export function computeFacts(repo: string, base: string, head: string): Facts {
  const mb = mergeBase(repo, base, head);
  const headSha = revParse(repo, head);
  const files0 = nameStatus(repo, mb, head);
  const stats = numstat(repo, mb, head);
  const files: ChangedFile[] = files0.map((f) => {
    const s = stats.get(f.path) ?? { additions: 0, deletions: 0 };
    const cls = classify(f.path);
    let patch = '';
    // Full patches for everything except generated/snapshot churn; those get a header only.
    if (cls !== 'generated' && cls !== 'snapshot') {
      patch = filePatch(repo, mb, head, f.path);
      if (patch.length > MAX_PATCH_CHARS) {
        patch = patch.slice(0, MAX_PATCH_CHARS) + `\n... [truncated ${patch.length - MAX_PATCH_CHARS} chars]\n`;
      }
    }
    return { path: f.path, status: f.status, cls, additions: s.additions, deletions: s.deletions, patch };
  });

  const counts: Partial<Record<FileClass, ClassCount>> = {};
  for (const f of files) {
    const c = (counts[f.cls] ??= { files: 0, additions: 0, deletions: 0 });
    c.files += 1;
    c.additions += f.additions;
    c.deletions += f.deletions;
  }

  const touchesPublicApi = files.some((f) => /Annotations\/|\/Attributes\.cs$|PublicAPI/.test(f.path));
  const hasTests = (counts.test?.files ?? 0) > 0;

  const unrequested: Facts['unrequested'] = [];
  for (const f of files) {
    if (f.cls === 'build' && /Directory\.Packages\.props|global\.json|\.props$|\.targets$/.test(f.path)) {
      unrequested.push({ path: f.path, reason: 'Dependency or build-configuration change; no requirement item asks for one.' });
    }
  }

  const riskReasons: string[] = [];
  let score = 0;
  const srcLines = (counts.source?.additions ?? 0) + (counts.source?.deletions ?? 0) + (counts.template?.additions ?? 0);
  if (srcLines > 400) { score += 2; riskReasons.push(`${srcLines} changed source/template lines`); }
  else if (srcLines > 100) { score += 1; riskReasons.push(`${srcLines} changed source/template lines`); }
  if (touchesPublicApi) { score += 2; riskReasons.push('touches public API surface (annotations/attributes)'); }
  if (unrequested.length) { score += 1; riskReasons.push(`${unrequested.length} build/dependency file(s) changed without a requirement`); }
  if (!hasTests) { score += 2; riskReasons.push('no test files changed'); }
  if ((counts.generated?.files ?? 0) + (counts.snapshot?.files ?? 0) > 50) { score += 1; riskReasons.push('large generated/snapshot churn hides the real diff'); }
  if (files.some((f) => f.cls === 'template')) { score += 1; riskReasons.push('changes code-generation templates (every consumer is affected)'); }
  const riskTier: RiskTier = score >= 4 ? 'high' : score >= 2 ? 'medium' : 'low';

  return {
    repo,
    base,
    head,
    mergeBase: mb,
    headSha,
    commitMessage: commitMessage(repo, head),
    files,
    counts,
    riskTier,
    riskReasons,
    unrequested,
    hasTests,
    touchesPublicApi,
  };
}

/** The diff the model reads: everything except generated/snapshot churn, in a stable order. */
export function reviewableDiff(facts: Facts, budgetChars = 180_000): string {
  const order: FileClass[] = ['source', 'template', 'test', 'docs', 'build', 'other'];
  const parts: string[] = [];
  let used = 0;
  for (const cls of order) {
    for (const f of facts.files.filter((x) => x.cls === cls)) {
      if (!f.patch) continue;
      const chunk = `### ${f.path} [${cls}, ${f.status}, +${f.additions} -${f.deletions}]\n${f.patch}\n`;
      if (used + chunk.length > budgetChars) {
        parts.push(`### ${f.path} [${cls}] — omitted, diff budget exhausted\n`);
        continue;
      }
      parts.push(chunk);
      used += chunk.length;
    }
  }
  const hidden = facts.files.filter((f) => f.cls === 'generated' || f.cls === 'snapshot');
  if (hidden.length) {
    parts.push(`### ${hidden.length} generated/snapshot files changed (not shown): ${hidden.slice(0, 8).map((f) => f.path).join(', ')}${hidden.length > 8 ? ', …' : ''}\n`);
  }
  return parts.join('\n');
}
