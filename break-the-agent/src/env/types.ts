// Domain model for the "Unreliable Informants" environment.
//
// The world is fictional and fully generated from a seed, so a frontier model
// can't answer from training data: it has to gather and weigh testimony.

export type Domain = "people" | "companies" | "events" | "finance";

/** One atomic, gradeable fact about the world. */
export interface Fact {
  id: string;
  domain: Domain;
  /** Entity the fact is about (used for self-interest bias). */
  subject: string;
  attribute: string;
  /** Canonical current value, e.g. "1987", "Marit Lehto", "42". */
  value: string;
  /** Present when the value changed over time; stale informants report the old one. */
  previous?: { value: string; untilYear: number };
  /** Archive record holding this fact. */
  recordId: string;
}

export interface Question {
  id: string;
  factId: string;
  domain: Domain;
  text: string;
}

export interface ArchiveRecord {
  id: string;
  title: string;
  /** Facts stated by the record, including history when present. */
  factIds: string[];
}

/** How an informant goes wrong. Hidden from the agent. */
export type InformantKind =
  | "generalist" // high reputation, answers everything, wrong outside true expertise
  | "stale" // accurate up to `cutoffYear`, reports previous values after that
  | "self_interested" // accurate except on facts about `biasedSubjects`
  | "ring" // shares a wrong source with other ring members; reputations are mutual
  | "narrow_expert"; // cheap, low reputation, accurate in domain, says "I don't know" otherwise

export interface Informant {
  id: string;
  name: string;
  /** What the informant claims to know. Visible. */
  claimedExpertise: Domain[];
  /** Public reputation 0..5. Visible. Not necessarily earned. */
  reputation: number;
  /** Credits charged per question. Visible. */
  cost: number;
  /** Who vouched for this reputation. Visible; lets a careful agent spot rings. */
  endorsedBy: string[];
  hidden: {
    kind: InformantKind;
    trueExpertise: Domain[];
    cutoffYear?: number;
    biasedSubjects?: string[];
    ringId?: string;
  };
}

export interface World {
  seed: string;
  town: string;
  currentYear: number;
  facts: Record<string, Fact>;
  records: Record<string, ArchiveRecord>;
  questions: Question[];
  informants: Informant[];
  /** Per-ring: the set of facts the ring is jointly wrong about, and the fake record they cite. */
  rings: Record<string, { factIds: string[]; fakeRecordId: string }>;
  budget: { credits: number; archiveLookups: number };
}

/** What an informant says when asked about a question. */
export interface Testimony {
  informantId: string;
  questionId: string;
  /** Null means "I don't know". */
  answer: string | null;
  /** Record id the informant points to; may be real, stale, or fabricated. */
  citedRecord?: string;
  confidence: "high" | "medium" | "low";
}

/** What the agent hands in. */
export interface Submission {
  answers: Array<{
    questionId: string;
    answer: string;
    /** Record ids and/or informant ids the agent relied on. */
    sources: string[];
  }>;
}

/** Append-only, HMAC-signed episode log written by the server; read by the verifier. */
export type LogEvent =
  | { t: "start"; seed: string; budget: World["budget"] }
  | { t: "ask"; informantId: string; questionId: string; cost: number; testimony: Testimony }
  | { t: "lookup"; recordId: string; found: boolean }
  | { t: "submit"; submission: Submission }
  | { t: "end"; reason: "submitted" | "budget_exhausted" | "timeout" };

export interface LogEntry {
  seq: number;
  ts: string;
  event: LogEvent;
  /** HMAC-SHA256 over (seq, prevSig, event) with a secret the agent never sees. */
  sig: string;
}
