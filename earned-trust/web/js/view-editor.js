// Middle pane: where the unit is called from, the whole unit after the change, and what it calls.
import { dedent, esc, expand, lineHtml, tabify } from "./syntax.js";
import { pairChanges, whole } from "./diff.js";
import { base, isTest, testNames, title } from "./model.js";

export function testLed(D, n) {
  const t = D.tests[n], cls = t.status === "passed" && !t.proves_fix ? "weak" : t.status.replace(/ /g, "");
  return `<i class="led ${cls}" title="${esc(`${n}: ${t.why}`)}"></i>`;
}

function testSummary(D, u) {
  const names = testNames(D, u);
  if (u.tier === "doc") return "";
  if (!names.length) return u.tier === "shipped" ? `<span class="tests hot">no test reaches this</span>` : "";
  const proven = names.filter((n) => D.tests[n].proves_fix).length, ran = names.some((n) => D.tests[n].status !== "not run");
  const words = ran ? `${proven} of ${names.length} prove${names.length > 1 ? "" : "s"} the change` : `${names.length} not run`;
  return `<span class="tests">${names.map((n) => testLed(D, n)).join("")} ${words}</span>`;
}

function pathBar(D, u, blocks) {
  const nav = blocks > 1 ? `<span class="nav-chg">${blocks} changes <button data-chg="-1" title="previous change (p)">↑</button><button data-chg="1" title="next change (n)">↓</button></span>`
    : blocks ? `<span class="nav-chg"><button data-chg="1" title="go to the change (n)">go to change ↓</button></span>` : "";
  return `<div class="path"><b>${esc(title(u))}</b><span class="file">${esc(u.file)}:${u.start}–${u.end}</span>${nav}${testSummary(D, u)}</div>`;
}

const jump = (D, file, name) => {
  const u = D.units.find((x) => x.file === file && x.name === name);
  return u ? `<button data-go="${esc(u.id)}">${esc(name)}</button>` : `<b>${esc(name)}</b>`;
};

function callers(D, u) {
  let html = `<div class="sec label">called from</div>`;
  for (const c of u.callers) {
    const via = (c.callers || []).map((d) => `${d.member} ${base(d.file)}:${d.line}`).join(" · ");
    const ex = c.excerpt.map((l) => expand(l.text)), cut = dedent(ex);
    html += `<div class="where">${jump(D, c.file, c.member)}<span>${esc(base(c.file))}:${c.line}${via ? " · reached from " + esc(via) : ""}</span></div>
      <div class="code one">${c.excerpt.map((l, k) => lineHtml({ nu: l.line, text: tabify(cut(ex[k])), cls: l.line === c.line ? "hit" : "", name: u.name })).join("")}</div>`;
  }
  const none = isTest(D, u) ? "run by the test runner" : u.name === "file header" ? "—" : "no caller found in this repo";
  return html + (u.callers.length ? "" : `<div class="quiet">${none}</div>`);
}

function change(u, prose) {
  const rows = whole(u).map((r) => ({ ...r, text: expand(r.text) })), cut = dedent(rows.map((r) => r.text));
  rows.forEach((r) => (r.text = prose ? cut(r.text) : tabify(cut(r.text))));
  const { chg, blocks } = pairChanges(rows);
  const html = rows.map((r, i) => lineHtml({ old: r.kind === "+" ? "" : r.old ?? "", nu: r.kind === "-" ? "" : r.new ?? "",
    sign: r.kind.trim(), text: r.text, prose, chg: chg[i], cls: { "+": "add", "-": "del", " ": "" }[r.kind],
    id: blocks.includes(i) ? `chg${blocks.indexOf(i)}` : "" })).join("");
  return { html: `<div class="sec label">the whole ${prose ? "section" : "function"} · after the change</div><div class="code ${prose ? "prose" : ""}">${html}</div>`, blocks: blocks.length };
}

function calls(D, u) {
  const html = u.calls.map((c) => `<div class="where">${jump(D, c.file, c.member)}<span>${esc(base(c.file))}:${c.decl} · called at line ${c.line}</span></div>
    <div class="code one">${lineHtml({ nu: c.decl, text: c.signature.trim(), cls: "hit", name: c.member })}</div>`).join("");
  return `<div class="sec label">calls</div>${html || `<div class="quiet">nothing else in this repo</div>`}`;
}

// Returns the pane's HTML and how many separate changes it has (for n / p navigation).
export function editor(D, u) {
  const prose = u.file.endsWith(".md"), body = change(u, prose);
  const html = pathBar(D, u, body.blocks) + (prose ? "" : callers(D, u)) + body.html + (prose ? "" : calls(D, u));
  return { html: html + `<div class="end"></div>`, blocks: body.blocks };
}
