import { test } from "node:test";
import assert from "node:assert/strict";
import { blockers, firstUnit, nextOpen, progress, related, state, testNames, testsOf, title } from "../js/model.js";

const unit = (id, extra = {}) => ({ id, name: id, file: `src/${id}.java`, tier: "shipped", status: "cleared",
  refusals: [], covered_by: [], calls: [], ...extra });
const dossier = () => ({
  units: [
    unit("a", { status: "routed", refusals: ["R1", "R2"], covered_by: ["aTest"] }),
    unit("b", { status: "held" }),
    unit("c"),
    unit("aTest", { file: "tests/T.java", tier: "test", calls: [{ file: "tests/T.java", member: "helper" }] }),
    unit("helper", { file: "tests/T.java", tier: "test", calls: [{ file: "tests/T.java", member: "helper" }] }),
    unit("other", { file: "tests/T.java", tier: "test" }),
    unit("readme", { file: "README.md", tier: "doc" }),
  ],
  refusals: [{ id: "R1", units: ["a"], question: "Q1?", owner: { name: "Aino" } },
             { id: "R2", units: ["a"], question: "Q2?", owner: { name: "Mikko" } }],
  tests: { aTest: { status: "passed", proves_fix: true }, other: { status: "passed", proves_fix: false } },
});
const all = { R1: {}, R2: {}, b: {} };

test("state: routed until every question is answered, then decided", () => {
  const D = dossier();
  assert.equal(state(D, {}, D.units[0]), "routed");
  assert.equal(state(D, { R1: {} }, D.units[0]), "routed");
  assert.equal(state(D, { R1: {}, R2: {} }, D.units[0]), "decided");
});

test("state: held until the approver accepts it, cleared stays cleared", () => {
  const D = dossier();
  assert.equal(state(D, {}, D.units[1]), "held");
  assert.equal(state(D, { b: {} }, D.units[1]), "decided");
  assert.equal(state(D, all, D.units[2]), "cleared");
});

test("blockers: one per open question, one per unproven unit, none when all is done", () => {
  const D = dossier();
  assert.deepEqual(blockers(D, {}).map((b) => b.go), ["a", "a", "b"]);
  assert.match(blockers(D, {})[0].text, /Aino decides: Q1\?/);
  assert.deepEqual(blockers(D, all), []);
});

test("nextOpen: after the current unit, wrapping, skipping itself; null when nothing is open", () => {
  const D = dossier();
  assert.equal(nextOpen(D, {}, "a").id, "b");
  assert.equal(nextOpen(D, {}, "b").id, "a");
  assert.equal(nextOpen(D, {}, "c").id, "a");
  assert.equal(nextOpen(D, { R1: {}, R2: {} }, "b"), null);
  assert.equal(nextOpen(D, all, "a"), null);
});

test("nextOpen: an unknown starting unit starts from the top", () => {
  assert.equal(nextOpen(dossier(), {}, "nope").id, "a");
});

test("firstUnit: code that needs a person, else the first code unit", () => {
  assert.equal(firstUnit(dossier(), {}), "a");
  assert.equal(firstUnit(dossier(), { R1: {}, R2: {} }), "b");
  assert.equal(firstUnit(dossier(), all), "a");
  const docsOnly = { ...dossier(), units: [unit("readme", { tier: "doc" })] };
  assert.equal(firstUnit(docsOnly, {}), "readme");
});

test("testsOf follows helpers and survives a helper that calls itself", () => {
  const D = dossier();
  assert.deepEqual([...testsOf(D, D.units[0])], ["aTest", "helper"]);
  assert.deepEqual([...testsOf(D, D.units[2])], []);
});

test("related: a test lights its own code's tests; an orphan test only itself; docs dim nothing", () => {
  const D = dossier();
  assert.deepEqual([...related(D, D.units[4])].sort(), ["aTest", "helper"]);
  assert.deepEqual([...related(D, D.units[5])], ["other"]);
  assert.equal(related(D, D.units[6]), null);
});

test("progress: decisions made, tests that prove the change, whether anything ran", () => {
  assert.deepEqual(progress(dossier(), { R1: {} }), { decided: 1, decisions: 2, proven: 1, tests: 2, ran: true });
  const notRun = { ...dossier(), tests: { t: { status: "not run" } } };
  assert.equal(progress(notRun, {}).ran, false);
  assert.deepEqual(progress({ ...dossier(), refusals: [], tests: {} }, {}), { decided: 0, decisions: 0, proven: 0, tests: 0, ran: false });
});

test("testNames: code lists its covering tests, a test lists itself, docs none", () => {
  const D = dossier();
  assert.deepEqual(testNames(D, D.units[0]), ["aTest"]);
  assert.deepEqual(testNames(D, D.units[3]), ["aTest"]);
  assert.deepEqual(testNames(D, D.units[6]), []);
});

test("titles read like an editor's", () => {
  assert.equal(title(unit("file header", { file: "src/Main.java" })), "imports · Main.java");
  assert.equal(title(unit("file header", { file: "src/A.cs" })), "usings · A.cs");
  assert.equal(title(unit("Main", { file: "src/Main.java" })), "Main()");
  assert.equal(title(unit("count", { file: "src/Terminal.java" })), "count");
});
