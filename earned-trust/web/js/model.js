// The rules of a review, as pure functions of the dossier (D) and the standing decisions (dec).

export const base = (path) => path.split("/").pop();

export function title(u) {
  if (u.name === "file header") return u.file.endsWith(".java") ? `imports · ${base(u.file)}` : `usings · ${base(u.file)}`;
  return base(u.file).split(".")[0] === u.name ? `${u.name}()` : u.name;
}

export const isTest = (D, u) => u.name in D.tests;
export const refusalsOf = (D, u) => D.refusals.filter((r) => u.refusals.includes(r.id));
export const openRefusals = (D, dec) => D.refusals.filter((r) => !dec[r.id]);
export const testNames = (D, u) => (u.tier === "shipped" ? u.covered_by : isTest(D, u) ? [u.name] : []);

// What the reviewer sees: routed and held units become "decided" once a person has answered for them.
export function state(D, dec, u) {
  if (u.status === "routed") return refusalsOf(D, u).every((r) => dec[r.id]) ? "decided" : "routed";
  if (u.status === "held") return dec[u.id] ? "decided" : "held";
  return u.status;
}

export const needsPerson = (D, dec, u) => ["routed", "held"].includes(state(D, dec, u));

// The next unit that needs a person, after `from` in list order, wrapping around; null when none is left.
export function nextOpen(D, dec, from) {
  const i = D.units.findIndex((u) => u.id === from);
  const order = [...D.units.slice(i + 1), ...D.units.slice(0, i + 1)];
  return order.find((u) => u.id !== from && needsPerson(D, dec, u)) || null;
}

// The first unit to show: something that needs a person, else the first changed function.
export const firstUnit = (D, dec) =>
  (D.units.find((u) => needsPerson(D, dec, u) && u.tier === "shipped") || D.units.find((u) => needsPerson(D, dec, u))
    || D.units.find((u) => u.tier === "shipped") || D.units[0]).id;

// Why the approver cannot merge yet, each with the unit that resolves it.
export function blockers(D, dec) {
  const out = openRefusals(D, dec).map((r) => ({ go: r.units[0], text: `${r.owner.name} decides: ${r.question}` }));
  for (const u of D.units) if (u.status === "held" && !dec[u.id]) out.push({ go: u.id, text: `${title(u)} is not proven by a test` });
  return out;
}

export function progress(D, dec) {
  const tests = Object.values(D.tests);
  return { decided: D.refusals.length - openRefusals(D, dec).length, decisions: D.refusals.length,
    proven: tests.filter((t) => t.proves_fix).length, tests: tests.length, ran: tests.some((t) => t.status !== "not run") };
}

// The test units that belong to a code unit: its tests and the helpers they call, transitively.
export function testsOf(D, u) {
  const byName = (n) => D.units.find((x) => x.name === n && x.tier === "test");
  const seen = new Set(), todo = u.covered_by.map(byName).filter(Boolean);
  for (const t of todo) {
    if (seen.has(t.id)) continue;
    seen.add(t.id);
    for (const c of t.calls) { const h = D.units.find((x) => x.file === c.file && x.name === c.member); if (h?.tier === "test") todo.push(h); }
  }
  return seen;
}

// Which test rows stay lit for the selection; null means no dimming (docs).
export function related(D, u) {
  if (u.tier === "doc") return null;
  if (u.tier === "shipped") return testsOf(D, u);
  const owners = D.units.filter((x) => x.tier === "shipped" && testsOf(D, x).has(u.id));
  return new Set([u.id, ...owners.flatMap((x) => [...testsOf(D, x)])]);
}
