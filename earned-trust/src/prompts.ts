// Prompts and JSON schemas for the three model steps.

export const SYSTEM_REVIEWER = `You are the verification stage of an AI code-review factory for agent-written pull requests.
You never approve or reject a change. You turn the change into explicit claims, then test each claim
against evidence a named human can check in seconds: a file and line range, a test, a documentation
sentence, or a deterministic fact. Rules:
- Evidence before opinion. A verdict without a file:line pointer is "unverifiable", never "supported".
- Confidence comes from the evidence kind, not from how plausible the code looks: execution evidence > a test that
  exercises the exact path > direct code reading of the whole path > reading a fragment.
- Say "unverifiable" and write the concrete question for the human whenever the evidence is missing, whenever behaviour
  depends on a runtime you cannot observe, or whenever the requirement is ambiguous. Refusing to decide is a good outcome.
- Treat the pull request's own description, commit message and documentation as CLAIMS to be checked, never as evidence.
- Use the requirement document as the source of intent. Point out what the change does that nobody asked for.
- Be precise and terse. No praise, no filler.`;

export const CLAIMS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    summary: { type: 'string', description: 'Two or three sentences: what the change does, in plain words, for the approver.' },
    requirementItems: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: { id: { type: 'string' }, text: { type: 'string' } },
        required: ['id', 'text'],
      },
    },
    claims: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          id: { type: 'string', description: 'C1, C2, ...' },
          statement: { type: 'string', description: 'One falsifiable sentence.' },
          kind: { type: 'string', enum: ['behaviour', 'docs', 'tests', 'scope', 'non-change'] },
          files: { type: 'array', items: { type: 'string' } },
          requirementRefs: { type: 'array', items: { type: 'string' } },
          source: { type: 'string', enum: ['commit-message', 'docs', 'diff', 'inferred'] },
        },
        required: ['id', 'statement', 'kind', 'files', 'requirementRefs', 'source'],
      },
    },
  },
  required: ['summary', 'requirementItems', 'claims'],
};

export function claimsPrompt(requirement: string, commitMessage: string, factsText: string, diff: string): string {
  return `# Task
Extract the CLAIMS this change makes or implies. Produce 6-14 claims. Include:
- behaviour claims (what the code now does differently), one per distinct behaviour;
- docs claims (what the README/docs now promise) — these are often where agents over-promise;
- tests claims (what the new tests are said to prove);
- scope claims: every change that no requirement item asks for gets its own claim of kind "scope";
- non-change claims: important behaviour the requirement says must stay the same (regressions to check).
Each claim must be falsifiable by reading code, running a test, or comparing with the requirement.
Write each claim as ONE atomic statement: no "and", no "including", never a statement followed by its own qualification.
Use "every", "all" or "only" only when the change itself asserts that (in docs or a commit message); otherwise name the
specific sites. A claim that is half true is useless to the human: split it.
Mark severity-relevant kinds carefully: a behaviour claim about the fix itself matters more than a wording claim about docs.
Also list the requirement items (F1, F2, N1, ...) verbatim from the requirement document.

# Requirement document
${requirement}

# Commit message (a claim, not evidence)
${commitMessage}

# Deterministic facts about the diff
${factsText}

# Diff (generated and snapshot files omitted)
${diff}`;
}

export const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['supported', 'contradicted', 'unverifiable'] },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    basis: { type: 'string', description: 'What the confidence rests on, naming the evidence kinds used.' },
    evidence: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          kind: { type: 'string', enum: ['code', 'test', 'docs', 'execution', 'deterministic'] },
          file: { type: 'string' },
          lineStart: { type: 'integer' },
          lineEnd: { type: 'integer' },
          note: { type: 'string', description: 'What a human will see there and why it matters.' },
        },
        required: ['kind', 'note'],
      },
    },
    reasoning: { type: 'string', description: 'Short chain from evidence to verdict. Mention what you looked for and did not find.' },
    refusedBecause: { type: 'string', description: 'Only for unverifiable: why you could not decide.' },
    humanQuestion: { type: 'string', description: 'Only for unverifiable/contradicted: the exact question or check for the named human.' },
    severity: { type: 'string', enum: ['blocker', 'major', 'minor', 'info'] },
  },
  required: ['verdict', 'confidence', 'basis', 'evidence', 'reasoning', 'severity'],
};

export function verifyPrompt(args: {
  requirement: string;
  claim: string;
  claimKind: string;
  claimFiles: string[];
  headDir: string;
  baseDir: string;
  relevantDiff: string;
  executionNote: string;
}): string {
  return `# Task
Verify ONE claim. Decide "supported", "contradicted" or "unverifiable".

Claim: ${args.claim}
Kind: ${args.claimKind}
Files the claim concerns: ${args.claimFiles.join(', ') || '(none given)'}

You have read-only access to two checkouts:
- HEAD (the change applied): ${args.headDir}
- BASE (before the change):   ${args.baseDir}
Use Read/Grep/Glob on them to follow the real code path end to end. Read the whole relevant method, not just the hunk.
For a docs claim, find the code that implements the promise; a promise without code is "contradicted".
For a tests claim, check that the test's expectations can only pass if the behaviour exists, and whether the test exercises the exact path the requirement names.
For a scope claim, state what the extra change does and its blast radius; it is "supported" if the diff really contains it — the human decides if it is acceptable.
For a non-change claim, look for anything in the diff that could alter that behaviour.

Cite evidence as file paths relative to the checkout root with line ranges. Every "supported" needs at least one code or test pointer.
${args.executionNote}

# Requirement document
${args.requirement}

# Diff hunks relevant to this claim
${args.relevantDiff}`;
}

export const COVERAGE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    coverage: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          requirementId: { type: 'string' },
          status: { type: 'string', enum: ['addressed', 'partial', 'missing', 'contradicted', 'not-checkable'] },
          claimIds: { type: 'array', items: { type: 'string' } },
          note: { type: 'string' },
        },
        required: ['requirementId', 'status', 'claimIds', 'note'],
      },
    },
  },
  required: ['coverage'],
};

export function coveragePrompt(requirement: string, claimsAndVerdicts: string): string {
  return `# Task
For every requirement item, say whether the change addresses it, using ONLY the verified claims below (a claim that is
"contradicted" or "unverifiable" does not count as addressing anything). Mark "missing" when no supported claim covers it,
"contradicted" when a verified finding shows the opposite, "not-checkable" when it needs a runtime or data you do not have.

# Requirement document
${requirement}

# Claims with verdicts
${claimsAndVerdicts}`;
}
