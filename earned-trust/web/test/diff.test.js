import { test } from "node:test";
import assert from "node:assert/strict";
import { changed, pairChanges, whole } from "../js/diff.js";

// A 6-line unit (lines 10-15 after the change); line 12 was replaced and one line was added at 14.
const unit = {
  start: 10,
  body: ["a", "b", "this.report = filtered(reporter);", "d", "added", "e"],
  lines: [
    { kind: " ", old: 11, new: 11, text: "b" },
    { kind: "-", old: 12, new: null, text: "this.report = reporter;" },
    { kind: "+", old: null, new: 12, text: "this.report = filtered(reporter);" },
    { kind: " ", old: 13, new: 13, text: "d" },
    { kind: "+", old: null, new: 14, text: "added" },
    { kind: " ", old: 14, new: 15, text: "e" },
  ],
};
const shape = (rows) => rows.map((r) => r.kind + r.text);

test("whole puts removed lines back before their replacement", () => {
  assert.deepEqual(shape(whole(unit)), [" a", " b", "-this.report = reporter;", "+this.report = filtered(reporter);", " d", "+added", " e"]);
});

test("whole numbers unchanged lines outside the hunks on both sides", () => {
  const rows = whole(unit);
  assert.deepEqual([rows[0].old, rows[0].new], [10, 10]);
  assert.deepEqual([rows[6].old, rows[6].new], [14, 15]);
});

test("whole does not change the unit it is given", () => {
  const before = JSON.stringify(unit);
  whole(unit)[0].text = "changed";
  assert.equal(JSON.stringify(unit), before);
});

test("whole keeps removed lines at the very end of the unit", () => {
  const u = { start: 1, body: ["a"], lines: [{ kind: " ", old: 1, new: 1, text: "a" }, { kind: "-", old: 2, new: null, text: "gone" }] };
  assert.deepEqual(shape(whole(u)), [" a", "-gone"]);
});

test("whole of a brand-new unit has no old numbers to invent", () => {
  const u = { start: 5, body: ["x", "y"], lines: [{ kind: "+", old: null, new: 5, text: "x" }, { kind: "+", old: null, new: 6, text: "y" }] };
  assert.deepEqual(whole(u).map((r) => [r.old, r.new]), [[null, 5], [null, 6]]);
});

test("whole falls back to the diff lines when the body is missing (old dossiers)", () => {
  assert.deepEqual(shape(whole({ ...unit, body: undefined })), shape(unit.lines));
});

test("changed finds only the differing words of a pair", () => {
  const a = "item.Refs[0].GetSyntax()", b = "item.Refs.FirstOrDefault()?.GetSyntax()";
  const [ra, rb] = changed(a, b);
  assert.equal(a.slice(...ra), "Refs[0]");
  assert.equal(b.slice(...rb), "Refs.FirstOrDefault()?");
});

test("changed gives no highlight for lines with too little in common, identical ones, or re-indented ones", () => {
  assert.deepEqual(changed("abc", "xyz"), [null, null]);
  assert.deepEqual(changed("", "something new"), [null, null]);
  assert.deepEqual(changed("same line here", "same line here"), [null, null]);
  assert.deepEqual(changed("    same line here", "\tsame line here"), [null, null]);
});

test("pairChanges pairs runs and counts separate changes", () => {
  const { chg, blocks } = pairChanges(whole(unit));
  assert.ok(chg[2] && chg[3]);
  assert.deepEqual(blocks, [2, 5]);
});

test("pairChanges: extra removed lines stay unpaired; adjacent runs are one change", () => {
  const rows = [{ kind: "-", text: "this.value = first;" }, { kind: "-", text: "drop me entirely" },
                { kind: "+", text: "this.value = second;" }];
  const { chg, blocks } = pairChanges(rows);
  assert.ok(chg[0][0] && chg[2][0]);
  assert.equal(chg[1], undefined);
  assert.deepEqual(blocks, [0]);
});

test("pairChanges of an unchanged unit has no changes", () => {
  assert.deepEqual(pairChanges([{ kind: " ", text: "a" }]), { chg: [], blocks: [] });
});
