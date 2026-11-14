// The whole unit as it reads after the change, with removed lines back in place and both line numbers.

// u.lines: the diff rows inside the unit ({kind: " "|"+"|"-", old, new, text}); u.body: the unit after the change.
export function whole(u) {
  if (!u.body) return u.lines.map((l) => ({ ...l }));
  const byNew = new Map(u.lines.filter((l) => l.kind !== "-").map((l) => [l.new, l]));
  const before = new Map();
  let pend = [];
  for (const l of u.lines) {
    if (l.kind === "-") pend.push(l);
    else if (pend.length) { before.set(l.new, pend); pend = []; }
  }
  const rows = [];
  u.body.forEach((text, k) => {
    const n = u.start + k;
    rows.push(...(before.get(n) || []), byNew.get(n) || { kind: " ", new: n, text });
  });
  return oldNumbers(u.lines, [...rows, ...pend].map((r) => ({ ...r })));
}

// Unchanged lines outside the hunks get old = new + (removed - added so far).
export function oldNumbers(lines, rows) {
  const ref = lines.findIndex((l) => l.kind === " "), seen = lines.slice(0, ref);
  const count = (k) => seen.filter((l) => l.kind === k).length;
  let delta = ref < 0 ? 0 : lines[ref].old - lines[ref].new - count("-") + count("+");
  for (const r of rows) {
    if (r.kind === " ") r.old ??= r.new + delta;
    delta += r.kind === "-" ? 1 : r.kind === "+" ? -1 : 0;
  }
  return rows;
}

// The part of a removed/added pair that differs: common prefix and suffix cut, snapped to whole words.
export function changed(a, b) {
  if (a.trim() === b.trim()) return [null, null];                // only indentation moved: nothing to point at
  let p = 0, s = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p++;
  while (p > 0 && /\w/.test(a[p - 1])) p--;
  while (s < a.length - p && s < b.length - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s++;
  while (s > 0 && /\w/.test(a[a.length - s])) s--;
  return p + s < 6 ? [null, null] : [[p, a.length - s], [p, b.length - s]];
}

// Pair each run of removed lines with the added run after it; `blocks` are the row indexes where
// a separate change starts (changes split by at least one unchanged line).
export function pairChanges(rows) {
  const chg = [], starts = [];
  for (let i = 0; i < rows.length;) {
    let d = i; while (d < rows.length && rows[d].kind === "-") d++;
    let a = d; while (a < rows.length && rows[a].kind === "+") a++;
    for (let k = 0; k < Math.min(d - i, a - d); k++) [chg[i + k], chg[d + k]] = changed(rows[i + k].text, rows[d + k].text);
    if (a > i) { starts.push(i); i = a; } else i++;
  }
  const blocks = starts.filter((s, k) => k === 0 || rows.slice(starts[k - 1], s).some((r) => r.kind === " "));
  return { chg, blocks };
}
