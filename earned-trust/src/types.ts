// Shared types for the claims → evidence → verdict review.

export type FileClass =
  | 'source'
  | 'test'
  | 'docs'
  | 'generated'
  | 'snapshot'
  | 'template'
  | 'build'
  | 'other';

export interface ChangedFile {
  path: string;
  status: 'A' | 'M' | 'D' | 'R';
  cls: FileClass;
  additions: number;
  deletions: number;
  /** Unified diff for this file (may be truncated for huge files). */
  patch: string;
}

export interface ClassCount {
  files: number;
  additions: number;
  deletions: number;
}

export type RiskTier = 'low' | 'medium' | 'high';

export interface Facts {
  repo: string;
  base: string;
  head: string;
  mergeBase: string;
  headSha: string;
  commitMessage: string;
  files: ChangedFile[];
  counts: Partial<Record<FileClass, ClassCount>>;
  riskTier: RiskTier;
  riskReasons: string[];
  /** Deterministic findings: changes that no requirement asked for. */
  unrequested: { path: string; reason: string }[];
  hasTests: boolean;
  touchesPublicApi: boolean;
}

export type ClaimKind = 'behaviour' | 'docs' | 'tests' | 'scope' | 'non-change';

export interface Claim {
  id: string;
  statement: string;
  kind: ClaimKind;
  files: string[];
  /** Requirement items (e.g. "F1", "N2") the claim is meant to satisfy. */
  requirementRefs: string[];
  source: 'commit-message' | 'docs' | 'diff' | 'inferred';
}

export interface RequirementItem {
  id: string;
  text: string;
}

export interface ClaimsResult {
  summary: string;
  requirementItems: RequirementItem[];
  claims: Claim[];
}

export type EvidenceKind = 'code' | 'test' | 'docs' | 'execution' | 'deterministic';

export interface Evidence {
  kind: EvidenceKind;
  file?: string;
  lineStart?: number;
  lineEnd?: number;
  note: string;
}

export type VerdictValue = 'supported' | 'contradicted' | 'unverifiable';
export type Confidence = 'high' | 'medium' | 'low';
export type Severity = 'blocker' | 'major' | 'minor' | 'info';

export interface Verdict {
  claimId: string;
  verdict: VerdictValue;
  confidence: Confidence;
  /** What the confidence rests on: the evidence kinds and their strength, not a feeling. */
  basis: string;
  evidence: Evidence[];
  reasoning: string;
  /** Present when the reviewer declined to decide. */
  refusedBecause?: string;
  /** The concrete question for the named human. */
  humanQuestion?: string;
  severity: Severity;
}

export type CoverageStatus = 'addressed' | 'partial' | 'missing' | 'contradicted' | 'not-checkable';

export interface Coverage {
  requirementId: string;
  status: CoverageStatus;
  claimIds: string[];
  note: string;
}

export interface ExecutionEvidence {
  ran: boolean;
  command?: string;
  summary: string;
  /** Head branch test results. */
  head?: TestRun;
  /** Same tests with the non-test changes reverted. Tests that still pass do not test the change. */
  mutation?: TestRun;
  log?: string;
}

export interface TestRun {
  passed: number;
  failed: number;
  skipped: number;
  total: number;
  buildFailed: boolean;
  durationMs: number;
  failedTests: string[];
}

export type Recommendation = 'accept-on-evidence' | 'needs-human' | 'reject';

export interface Report {
  tool: 'cev';
  version: string;
  generatedAt: string;
  requirementId: string;
  requirementPath: string;
  facts: Facts;
  model: string;
  summary: string;
  requirementItems: RequirementItem[];
  claims: Claim[];
  verdicts: Verdict[];
  coverage: Coverage[];
  execution: ExecutionEvidence;
  /** Items the AI refused to decide, with the question for the human. */
  routedToHuman: { claimId: string; question: string; why: string }[];
  recommendation: Recommendation;
  recommendationReasons: string[];
  /** Approximate cost of the model calls, USD. */
  costUsd: number;
}
