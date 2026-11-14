// Left pane: which change, how far the review is, and the changed units.
import { esc } from "./syntax.js";
import { progress, related, state, title } from "./model.js";

export const MEANS = { cleared: "proven, safe to skip", held: "not proven by a test", routed: "needs a decision", decided: "decided" };

export function switcher(cases, current) {
  const opt = (c) => `<option value="${esc(c.id)}" ${c.id === current ? "selected" : ""}>${esc(c.label)} · ${esc(c.title)}`
    + `${c.language ? ` (${esc(c.language)})` : ""}${c.outcome ? ` · ${esc(c.outcome)}` : c.open ? ` · ${c.open} open` : ""}</option>`;
  return `<label class="label" for="case">change under review</label><select id="case">${cases.map(opt).join("")}</select>`;
}

export function header(D, dec) {
  const p = progress(D, dec), c = D.case;
  const tests = p.ran ? `<b>${p.proven} of ${p.tests}</b> tests prove the change` : "tests not run on this machine";
  return `<div class="label">${esc(c.label || "#" + c.issue)} · agent change · ${esc(c.language || "")}</div>
    <h1>${esc(c.title)}</h1>
    <div class="progress"><b>${p.decided} of ${p.decisions}</b> decisions made<br>${tests}</div>
    <div class="source" title="${esc(D.review_source.note)}">AI review: ${D.review_source.kind === "llm" ? "Claude" : "hand-written stand-in"}</div>`;
}

function row(D, dec, u, sel, lit) {
  const st = state(D, dec, u), dim = u.tier === "test" && lit && !lit.has(u.id);
  return `<button class="row ${u.id === sel ? "sel" : ""} ${dim ? "dim" : ""}" data-go="${esc(u.id)}" title="${esc(MEANS[st])} · ${esc(u.file)}">
    <i class="led ${st}"></i><span>${esc(title(u))}</span><em>+${u.added}${u.removed ? " −" + u.removed : ""}</em></button>`;
}

export function unitList(D, dec, sel) {
  const lit = related(D, D.units.find((u) => u.id === sel));
  return [["shipped", "code"], ["test", "tests"], ["doc", "docs"]]
    .filter(([tier]) => D.units.some((u) => u.tier === tier))
    .map(([tier, name]) => `<div class="group label">${name}</div>`
      + D.units.filter((u) => u.tier === tier).map((u) => row(D, dec, u, sel, lit)).join("")).join("");
}

export const legend = () => Object.entries(MEANS).map(([k, v]) => `<span><i class="led ${k}"></i>${v}</span>`).join("");
