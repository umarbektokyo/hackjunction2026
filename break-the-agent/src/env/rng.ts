// Seeded PRNG. Everything in the world and in informant answers derives from
// this so an episode replays identically for the same seed and actions.

/** FNV-1a 32-bit hash of a string → uint32 seed. */
export function hashSeed(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export class Rng {
  private state: number;

  constructor(seed: number | string) {
    this.state = (typeof seed === "string" ? hashSeed(seed) : seed) >>> 0;
  }

  /** mulberry32: uniform float in [0, 1). */
  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  /** Integer in [lo, hi] inclusive. */
  int(lo: number, hi: number): number {
    return lo + Math.floor(this.next() * (hi - lo + 1));
  }

  chance(p: number): boolean {
    return this.next() < p;
  }

  pick<T>(xs: readonly T[]): T {
    if (xs.length === 0) throw new Error("pick from empty array");
    return xs[Math.floor(this.next() * xs.length)]!;
  }

  /** Pick `n` distinct elements. */
  sample<T>(xs: readonly T[], n: number): T[] {
    return this.shuffle(xs).slice(0, n);
  }

  shuffle<T>(xs: readonly T[]): T[] {
    const out = xs.slice();
    for (let i = out.length - 1; i > 0; i--) {
      const j = Math.floor(this.next() * (i + 1));
      [out[i], out[j]] = [out[j]!, out[i]!];
    }
    return out;
  }

  /** A child generator whose stream depends only on (this seed, label). */
  fork(label: string): Rng {
    return new Rng(hashSeed(`${this.state}:${label}`));
  }
}
