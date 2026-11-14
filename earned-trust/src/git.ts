import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, existsSync } from 'node:fs';

export function git(repo: string, args: string[], opts: { allowFail?: boolean } = {}): string {
  const r = spawnSync('git', ['-C', repo, ...args], { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 });
  if (r.status !== 0 && !opts.allowFail) {
    throw new Error(`git ${args.join(' ')} failed: ${r.stderr}`);
  }
  return r.stdout;
}

export function revParse(repo: string, rev: string): string {
  return git(repo, ['rev-parse', rev]).trim();
}

export function mergeBase(repo: string, base: string, head: string): string {
  return git(repo, ['merge-base', base, head]).trim();
}

export function commitMessage(repo: string, rev: string): string {
  return git(repo, ['log', '-1', '--format=%B', rev]).trim();
}

export interface NameStatus {
  status: 'A' | 'M' | 'D' | 'R';
  path: string;
}

export function nameStatus(repo: string, from: string, to: string): NameStatus[] {
  const out = git(repo, ['diff', '--name-status', '-M', from, to]);
  return out
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const parts = line.split('\t');
      const code = parts[0][0] as NameStatus['status'];
      // Renames: "R100\told\tnew"
      const path = code === 'R' ? parts[2] : parts[1];
      return { status: code, path };
    });
}

export function numstat(repo: string, from: string, to: string): Map<string, { additions: number; deletions: number }> {
  const out = git(repo, ['diff', '--numstat', '-M', from, to]);
  const m = new Map<string, { additions: number; deletions: number }>();
  for (const line of out.split('\n').filter(Boolean)) {
    const [a, d, ...rest] = line.split('\t');
    let path = rest.join('\t');
    // Renames show as "old => new" or "{a => b}/x"
    if (path.includes(' => ')) {
      const mm = path.match(/^(.*)\{(.*) => (.*)\}(.*)$/);
      path = mm ? `${mm[1]}${mm[3]}${mm[4]}` : path.split(' => ')[1];
    }
    m.set(path, { additions: a === '-' ? 0 : Number(a), deletions: d === '-' ? 0 : Number(d) });
  }
  return m;
}

export function filePatch(repo: string, from: string, to: string, path: string, context = 6): string {
  return git(repo, ['diff', `--unified=${context}`, '-M', from, to, '--', path]);
}

export function show(repo: string, rev: string, path: string): string | null {
  const r = spawnSync('git', ['-C', repo, 'show', `${rev}:${path}`], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  return r.status === 0 ? r.stdout : null;
}

/** Create (or reuse) a detached worktree at `dir` for `rev`. */
export function ensureWorktree(repo: string, rev: string, dir: string): string {
  if (existsSync(dir)) {
    const current = spawnSync('git', ['-C', dir, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).stdout.trim();
    const wanted = revParse(repo, rev);
    if (current === wanted) return dir;
    execFileSync('git', ['-C', repo, 'worktree', 'remove', '--force', dir]);
  }
  mkdirSync(dir, { recursive: true });
  execFileSync('git', ['-C', repo, 'worktree', 'add', '--detach', '--force', dir, rev], { stdio: 'ignore' });
  return dir;
}

export function removeWorktree(repo: string, dir: string): void {
  spawnSync('git', ['-C', repo, 'worktree', 'remove', '--force', dir]);
}
