// The page: state, server calls, events. Views are pure functions of this state.
import { esc } from "./syntax.js";
import { firstUnit, nextOpen } from "./model.js";
import { header, legend, switcher, unitList } from "./view-list.js";
import { editor } from "./view-editor.js";
import { review } from "./view-review.js";
import { approver } from "./view-approver.js";

const $ = (s) => document.querySelector(s);
const ui = { cases: [], S: null, sel: null, busy: null, error: null, asking: false, chgAt: -1, blocks: 0 };
const D = () => ui.S.dossier, dec = () => ui.S.decisions, unit = () => D().units.find((u) => u.id === ui.sel);

async function openCase(id, unitId) {
  ui.S = await (await fetch(`/api/state?case=${encodeURIComponent(id)}`)).json();
  ui.sel = D().units.some((u) => u.id === unitId) ? unitId : firstUnit(D(), dec());
  ui.asking = false;
  render(true);
}

async function start() {
  ui.cases = await (await fetch("/api/cases")).json();
  const [caseId, unitId] = decodeURIComponent(location.hash.slice(1)).split("/");   // #<case>/<unit id>
  await openCase(ui.cases.some((c) => c.id === caseId) ? caseId : ui.cases[0].id, unitId);
}

async function post(item, decision, note = "") {
  ui.busy = item + "|" + decision; ui.error = null; renderSide();
  const res = await fetch("/api/decide", { method: "POST", body: JSON.stringify({ case: ui.S.case, item, decision, note }) });
  ui.busy = null;
  if (!res.ok) { ui.error = await res.text(); return renderSide(); }
  ui.S = await res.json();
  ui.cases = await (await fetch("/api/cases")).json();
  ui.asking = false;
  renderSide();
  toast(...feedback(item, decision));
}

function feedback(item, decision) {
  if (decision === "reopen") return [item === "MERGE" ? "Withdrawn. The change is open again." : "Reopened. Choose again."];
  if (item === "MERGE") return [decision === "approved" ? "Merged." : "Changes requested. The agent gets your note.", () => post(item, "reopen")];
  return [`Recorded: “${decision}”`, () => post(item, "reopen")];
}

function toast(text, undo) {
  const t = $("#toast");
  t.innerHTML = `<span>${esc(text)}</span>${undo ? `<button>Undo</button>` : ""}`;
  if (undo) t.querySelector("button").onclick = () => { t.classList.remove("show"); undo(); };
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 6000);
}

function go(id) {
  ui.sel = id; ui.chgAt = -1;
  render(true);
}

function jumpChange(step) {
  if (!ui.blocks) return;
  ui.chgAt = Math.max(0, Math.min(ui.blocks - 1, ui.chgAt + step));
  const el = document.getElementById("chg" + ui.chgAt);
  $("#editor").scrollTo({ top: el.offsetTop - 120, behavior: "smooth" });
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
}

function act(name) {
  if (name === "ask") { ui.asking = true; renderSide(); $("#note").focus(); }
  if (name === "cancel") { ui.asking = false; renderSide(); }
  if (name === "blocked") { const w = $("#why"); w.classList.remove("flash"); void w.offsetWidth; w.classList.add("flash"); }
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-go],[data-item],[data-chg],[data-act]");
  if (!t) return;
  if (t.dataset.act) return act(t.dataset.act);
  if (t.dataset.item) return post(t.dataset.item, t.dataset.decision, $("#note")?.value || "");
  if (t.dataset.chg) return jumpChange(+t.dataset.chg);
  go(t.dataset.go);
});
document.addEventListener("change", (e) => { if (e.target.id === "case") openCase(e.target.value); });
document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey || /input|textarea|select/i.test(e.target.tagName)) return;
  if (e.key === "n" || e.key === "p") return jumpChange(e.key === "n" ? 1 : -1);
  const step = { ArrowDown: 1, ArrowUp: -1, j: 1, k: -1 }[e.key];
  const order = [...document.querySelectorAll(".row")].map((r) => r.dataset.go), next = order[order.indexOf(ui.sel) + (step || 0)];
  if (step && next) { e.preventDefault(); go(next); $(".row.sel").scrollIntoView({ block: "nearest" }); }
});

// Re-render the list, the review and the approver box (decisions change these, not the code).
function renderSide() {
  $("#head").innerHTML = switcher(ui.cases, ui.S.case) + header(D(), dec());
  $("#list").innerHTML = unitList(D(), dec(), ui.sel);
  $("#approver").innerHTML = approver(D(), { dec: dec(), asking: ui.asking });
  $("#review").innerHTML = review(D(), unit(), { dec: dec(), busy: ui.busy, error: ui.error, next: nextOpen(D(), dec(), ui.sel) });
}

function render(scrollTop) {
  const ed = editor(D(), unit());
  $("#editor").innerHTML = ed.html;
  ui.blocks = ed.blocks;
  renderSide();
  $("#legend").innerHTML = legend();
  if (scrollTop) { $("#editor").scrollTop = 0; $("#review").scrollTop = 0; }
  history.replaceState(null, "", `#${ui.S.case}/${ui.sel}`);
}

start();
