// Model backend. Default: the logged-in `claude` CLI in print mode with a JSON schema.
// Set CEV_MODEL to pick the model alias (default "sonnet").
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export interface LlmOptions {
  /** Directory the model may read (read-only tools). Omit for a pure text call. */
  readDir?: string;
  maxTurns?: number;
  cacheDir?: string;
  label?: string;
}

export interface LlmResult<T> {
  data: T;
  costUsd: number;
  cached: boolean;
  durationMs: number;
}

export const MODEL = process.env.CEV_MODEL ?? 'sonnet';

export async function askJson<T>(system: string, prompt: string, schema: object, opts: LlmOptions = {}): Promise<LlmResult<T>> {
  const key = createHash('sha256').update(JSON.stringify({ system, prompt, schema, MODEL, readDir: !!opts.readDir })).digest('hex').slice(0, 24);
  const cacheFile = opts.cacheDir ? join(opts.cacheDir, `${key}.json`) : null;
  if (cacheFile && existsSync(cacheFile)) {
    const c = JSON.parse(readFileSync(cacheFile, 'utf8'));
    return { data: c.data, costUsd: 0, cached: true, durationMs: 0 };
  }

  const args = [
    '-p',
    '--output-format', 'json',
    '--json-schema', JSON.stringify(schema),
    '--model', MODEL,
    '--no-session-persistence',
    '--system-prompt', system,
  ];
  if (opts.readDir) {
    args.push('--add-dir', opts.readDir, '--allowedTools', 'Read', 'Grep', 'Glob', '--disallowedTools', 'Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch', 'Agent', 'Task', 'NotebookEdit');
    args.push('--max-turns', String(opts.maxTurns ?? 30));
  } else {
    args.push('--tools', '', '--max-turns', '1');
  }

  const env = { ...process.env };
  delete env.CLAUDECODE; // allow nesting from inside a Claude Code session
  const started = Date.now();
  const r = spawnSync('claude', args, {
    input: prompt,
    encoding: 'utf8',
    env,
    cwd: opts.readDir ?? process.cwd(),
    maxBuffer: 64 * 1024 * 1024,
    timeout: 15 * 60 * 1000,
  });
  const durationMs = Date.now() - started;
  if (r.status !== 0) {
    throw new Error(`claude -p failed (${opts.label ?? 'call'}): ${r.stderr || r.stdout}`);
  }
  let parsed: any;
  try {
    parsed = JSON.parse(r.stdout);
  } catch {
    throw new Error(`claude -p returned non-JSON (${opts.label ?? 'call'}): ${r.stdout.slice(0, 500)}`);
  }
  if (parsed.is_error) throw new Error(`claude -p error (${opts.label ?? 'call'}): ${parsed.result}`);
  let data: T = parsed.structured_output;
  if (data === undefined) {
    // Fallback: the result text should itself be JSON.
    try { data = JSON.parse(parsed.result); } catch { throw new Error(`no structured output (${opts.label ?? 'call'}): ${String(parsed.result).slice(0, 500)}`); }
  }
  const costUsd = Number(parsed.total_cost_usd ?? 0);
  if (cacheFile) {
    mkdirSync(opts.cacheDir!, { recursive: true });
    writeFileSync(cacheFile, JSON.stringify({ data, costUsd, model: MODEL, label: opts.label, durationMs }, null, 2));
  }
  return { data, costUsd, cached: false, durationMs };
}
