import { test } from "node:test";
import assert from "node:assert/strict";
import { approver } from "../js/view-approver.js";
import { review } from "../js/view-review.js";
import { editor } from "../js/view-editor.js";
import { header, switcher, unitList } from "../js/view-list.js";

const EVIL = `<img src=x onerror=alert(1)>`;
const unit = (id, extra = {}) => ({ id, name: id, file: `src/${id}.java`, tier: "shipped", status: "cleared", refusals: [],
  covered_by: [], calls: [], callers: [], reqs: ["REQ-1"], summary: "does a thing", start: 1, end: 1, added: 1, removed: 0,
  lines: [{ kind: "+", old: null, new: 1, text: "int a = 1;" }], body: ["int a = 1;"], ...extra });
const dossier = (units, refusals = []) => ({
  case: { issue: "W3", label: "REQ-W3", title: "Thread", language: "Java" }, units, refusals,
  tests: {}, findings: [], proposed_tests: [], requirements: [{ id: "REQ-1", text: "req text" }],
  owners: { approver: { name: "Sara", role: "Approver" } }, review_source: { kind: "llm", note: "claude" },
});
const R1 = { id: "R1", units: ["a"], question: "Wait or not?", why: "unclear", options: ["wait", "do not wait"],
  owner: { name: "Jussi", role: "Product owner" }, agent_choice: "do not wait" };
const decidedBy = (decision) => ({ decision, by: { name: "Jussi" }, at: "2026-11-14T13:56:00", note: "" });

test("approver: Merge is shown but disabled while anything blocks it, with each blocker as a link", () => {
  const html = approver(dossier([unit("a", { status: "routed", refusals: ["R1"] })], [R1]), { dec: {}, asking: false });
  assert.match(html, /class="primary off" aria-disabled="true"/);
  assert.match(html, /blocked by 1/);
  assert.match(html, /data-go="a"/);
  assert.match(html, /Request changes/);
});

test("approver: Merge is enabled once nothing blocks it", () => {
  const html = approver(dossier([unit("a")]), { dec: {}, asking: false });
  assert.match(html, /data-item="MERGE" data-decision="approved">Merge</);
  assert.doesNotMatch(html, /aria-disabled/);
});

test("approver: after a merge or a change request it shows the outcome with a way back", () => {
  const D = dossier([unit("a")]);
  assert.match(approver(D, { dec: { MERGE: decidedBy("approved") } }), /Merged by Jussi[\s\S]*Undo merge/);
  const asked = approver(D, { dec: { MERGE: { ...decidedBy("changes requested"), note: EVIL } } });
  assert.match(asked, /Changes requested[\s\S]*Withdraw request/);
  assert.doesNotMatch(asked, /<img/);
});

test("approver: asking for changes shows a note box with send and cancel", () => {
  const html = approver(dossier([unit("a")]), { dec: {}, asking: true });
  assert.match(html, /<textarea id="note"/);
  assert.match(html, /data-decision="changes requested"/);
  assert.match(html, /data-act="cancel"/);
});

test("review: an open question offers every option, names the owner and what the agent did", () => {
  const D = dossier([unit("a", { status: "routed", refusals: ["R1"] })], [R1]);
  const html = review(D, D.units[0], { dec: {}, busy: null, error: null, next: null });
  assert.equal((html.match(/class="opt /g) || []).length, 2);
  assert.match(html, /Jussi, Product owner/);
  assert.match(html, /What the agent did: do not wait/);
});

test("review: while saving, the clicked option is marked busy; a server error is shown", () => {
  const D = dossier([unit("a", { status: "routed", refusals: ["R1"] })], [R1]);
  const html = review(D, D.units[0], { dec: {}, busy: "R1|wait", error: "not a valid decision", next: null });
  assert.match(html, /class="opt busy"/);
  assert.match(html, /Not recorded: not a valid decision/);
});

test("review: a decided question shows the choice, who, when, and change / next actions", () => {
  const D = dossier([unit("a", { status: "routed", refusals: ["R1"] }), unit("b", { status: "held" })], [R1]);
  const html = review(D, D.units[0], { dec: { R1: decidedBy("wait") }, next: D.units[1] });
  assert.match(html, /class="chosen">wait</);
  assert.match(html, /decided · Jussi · 13:56/);
  assert.match(html, /data-go="b"[^>]*>Next open item/);
  assert.match(html, /data-decision="reopen">Change decision/);
});

test("review: a held unit offers accepting without proof, on the approver's name", () => {
  const D = dossier([unit("b", { status: "held" })]);
  const html = review(D, D.units[0], { dec: {}, next: null });
  assert.match(html, /data-decision="accepted without proof">Accept without a proving test \(Sara answers for it\)/);
});

test("review: untraced units say so; model text is escaped", () => {
  const D = dossier([unit("a", { reqs: [], summary: EVIL })]);
  const html = review(D, D.units[0], { dec: {}, next: null });
  assert.match(html, /Not traced to a requirement/);
  assert.doesNotMatch(html, /<img/);
});

test("editor: the whole function with numbers, change navigation, and an honest test summary", () => {
  const D = dossier([unit("a")]);
  const { html, blocks } = editor(D, D.units[0]);
  assert.equal(blocks, 1);
  assert.match(html, /go to change/);
  assert.match(html, /no test reaches this/);
  assert.match(html, /no caller found in this repo/);
});

test("editor: Markdown is shown as a section without callers or calls", () => {
  const D = dossier([unit("doc", { file: "README.md", tier: "doc", lines: [{ kind: "+", new: 1, text: "# Title" }], body: ["# Title"] })]);
  const { html } = editor(D, D.units[0]);
  assert.match(html, /the whole section/);
  assert.doesNotMatch(html, /called from/);
});

test("list: the switcher marks the current case and shows open counts or outcomes", () => {
  const html = switcher([{ id: "a", label: "#1", title: "One", open: 2 }, { id: "b", label: "#2", title: "Two", open: 0, outcome: "approved" }], "b");
  assert.match(html, /value="a" >#1 · One · 2 open/);
  assert.match(html, /value="b" selected>#2 · Two · approved/);
});

test("list: header says whether the AI review is real; units are grouped and marked", () => {
  const D = dossier([unit("a", { status: "routed", refusals: ["R1"] }), unit("t", { tier: "test", file: "tests/T.java" })], [R1]);
  assert.match(header(D, {}), /AI review: Claude/);
  assert.match(header({ ...D, review_source: { kind: "handwritten", note: "" } }, {}), /hand-written stand-in/);
  const list = unitList(D, {}, "a");
  assert.match(list, /code<\/div>[\s\S]*tests<\/div>/);
  assert.match(list, /class="row sel /);
  assert.doesNotMatch(list, /docs<\/div>/);
});
