// Right pane: what this unit is, what the tests say, the decisions a person owns, what the AI noticed.
import { esc } from "./syntax.js";
import { isTest, refusalsOf, state, testNames } from "./model.js";

const LABEL = { cleared: "Proven · safe to skip", held: "Not proven by a test", routed: "Needs a decision", decided: "Decided" };

function facts(D, u) {
  if (isTest(D, u)) return `This test ${esc(D.tests[u.name].why)}.`;
  if (u.tier !== "shipped") return "";
  const names = testNames(D, u), proven = names.filter((n) => D.tests[n].proves_fix).length;
  if (!names.length) return "No test reaches this function.";
  return proven ? `${proven} of ${names.length} test${names.length > 1 ? "s prove" : " proves"} the change: it passes with it, and fails or no longer compiles without it.`
    : `${names.length} test${names.length > 1 ? "s" : ""} reach it; none has proven the change yet.`;
}

function requirements(D, u) {
  const reqs = D.requirements.filter((r) => u.reqs.includes(r.id));
  if (!reqs.length) return `<p class="reqs none">Not traced to a requirement.</p>`;
  return `<p class="reqs">Serves ${reqs.map((r) => `<span class="req" title="${esc(r.text)}">${esc(r.id)}</span>`).join(" ")}</p>`;
}

// opts: the decisions to offer; labels: optional button text for each (the decision is what gets recorded).
const options = (id, opts, busy, labels = opts) => `<div class="opts">${opts.map((o, k) =>
  `<button class="opt ${busy === id + "|" + o ? "busy" : ""}" data-item="${esc(id)}" data-decision="${esc(o)}">${esc(labels[k])}</button>`).join("")}</div>`;

function decidedCard(question, rec, item, next) {
  return `<section class="card done">
    <div class="label">decided · ${esc(rec.by.name)} · ${rec.at.slice(11, 16)}</div>
    <h2>${esc(question)}</h2><div class="chosen">${esc(rec.decision)}</div>
    <div class="who">Recorded with ${esc(rec.by.name)}'s name and the evidence it rests on.</div>
    <div class="after">${next ? `<button class="primary" data-go="${esc(next.id)}">Next open item →</button>` : `<span class="facts">Nothing else needs a person.</span>`}
      <button class="link" data-item="${esc(item)}" data-decision="reopen">Change decision</button></div></section>`;
}

function decisionCard(r, ui) {
  const rec = ui.dec[r.id];
  if (rec) return decidedCard(r.question, rec, r.id, ui.next);
  return `<section class="card">
    <div class="label hot">needs a decision · ${esc(r.owner.name)}, ${esc(r.owner.role)}</div>
    <h2>${esc(r.question)}</h2>
    <p class="hint">The AI will not decide this. Pick one: it is recorded with ${esc(r.owner.name)}'s name, and you can change it later.</p>
    ${r.agent_choice ? `<p class="agent">What the agent did: ${esc(r.agent_choice)}</p>` : ""}
    ${options(r.id, r.options, ui.busy)}${ui.error ? `<div class="err">Not recorded: ${esc(ui.error)}</div>` : ""}
    <details><summary>Why the AI won't decide this</summary><p>${esc(r.why)}</p></details></section>`;
}

function proofCard(D, u, ui) {
  const rec = ui.dec[u.id], ap = D.owners.approver;
  if (rec) return decidedCard("Accept this without a test that proves it?", rec, u.id, ui.next);
  return `<section class="card">
    <div class="label hot">not proven · ${esc(ap.name)}, ${esc(ap.role)}</div>
    <h2>No test proves this change. Accept it anyway?</h2>
    <p class="hint">Accepting records that ${esc(ap.name)} takes responsibility for the missing proof. To ask for a test instead, use Request changes.</p>
    ${options(u.id, ["accepted without proof"], ui.busy, [`Accept without a proving test (${ap.name} answers for it)`])}</section>`;
}

function notes(D, u) {
  const mine = D.findings.filter((f) => f.unit === u.id);
  if (!mine.length) return "";
  return `<section><div class="label">the AI noticed</div>${mine.map((f) => {
    const wanted = D.proposed_tests.filter((p) => p.for === f.id);
    return `<details><summary><span>${esc(f.title)}</span>${wanted.length ? `<em>${wanted.length} test${wanted.length > 1 ? "s" : ""} to add</em>` : ""}</summary>
      <p>${esc(f.text)}</p>${wanted.map((p) => `<div class="suggest">${esc(p.text)}</div>`).join("")}</details>`;
  }).join("")}</section>`;
}

// ui: {dec, busy, error, next}
export function review(D, u, ui) {
  const st = state(D, ui.dec, u);
  let html = `<div class="state ${st === "routed" || st === "held" ? "hot" : ""}"><i class="led ${st}"></i>${LABEL[st]}</div>
    <p class="summary">${esc(u.summary)}</p>${requirements(D, u)}<p class="facts">${facts(D, u)}</p>`;
  html += refusalsOf(D, u).map((r) => `<section>${decisionCard(r, ui)}</section>`).join("");
  if (u.status === "held") html += `<section>${proofCard(D, u, ui)}</section>`;
  return html + notes(D, u);
}
