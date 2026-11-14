import { test } from "node:test";
import assert from "node:assert/strict";
import { dedent, esc, lineHtml, paint, tabify, tokens } from "../js/syntax.js";

const kinds = (t) => tokens(t).map(([a, b, k]) => `${k}:${t.slice(a, b)}`);

test("tokens classify keywords, strings, comments, numbers and types", () => {
  assert.deepEqual(kinds(`return new Thread("x", 3); // go`), ["kw:return", "kw:new", "type:Thread", 'str:"x"', "num:3", "com:// go"]);
  assert.deepEqual(kinds("@Override"), ["type:@Override"]);
});

test("tokens: keywords inside strings and comments stay strings and comments", () => {
  assert.deepEqual(kinds(`"return new"`), ['str:"return new"']);
  assert.deepEqual(kinds("// if this then that"), ["com:// if this then that"]);
  assert.deepEqual(kinds(`"a \\" b"`), ['str:"a \\" b"']);
});

test("tokens: Javadoc continuation lines are comments; an unclosed string runs to the end", () => {
  assert.deepEqual(kinds("     * @param x the value"), ["com:     * @param x the value"]);
  assert.deepEqual(kinds(`s = "unclosed`), ['str:"unclosed']);
});

test("tokens: identifiers that only contain a keyword are not keywords", () => {
  assert.deepEqual(kinds("newValue = returned"), []);
});

test("paint nests overlapping ranges and escapes text", () => {
  assert.equal(paint("a<b", [[0, 3, "chg"], [1, 2, "kw"]]), `<span class="chg">a</span><span class="chg kw">&lt;</span><span class="chg">b</span>`);
  assert.equal(paint("", []), "");
  assert.equal(paint("x", [[5, 9, "kw"]]), "x");
});

test("esc neutralises markup from model or code text", () => {
  assert.equal(esc(`"<&>"`), "&quot;&lt;&amp;&gt;&quot;");
  assert.equal(esc(`<img src=x onerror=alert(1)>`), "&lt;img src=x onerror=alert(1)&gt;");
  assert.equal(esc(42), "42");
});

test("dedent removes the common indentation and ignores blank lines", () => {
  const cut = dedent(["    a", "        b", "", "  "]);
  assert.equal(cut("        b"), "    b");
  assert.equal(dedent(["", " "])("x"), "x");
});

test("tabify turns whole 4-space steps into tabs and keeps the rest", () => {
  assert.equal(tabify("        x  y"), "\t\tx  y");
  assert.equal(tabify("      z"), "\t  z");
  assert.equal(tabify("no indent"), "no indent");
});

test("lineHtml turns indentation into a hanging indent", () => {
  const html = lineHtml({ nu: 7, text: "\t\treturn x;" });
  assert.match(html, /--i:4ch/);
  assert.match(html, /<span class="kw">return<\/span> x;/);
});

test("lineHtml marks calls of the function by name, not other names that contain it", () => {
  const html = lineHtml({ text: "a.run(); runAll(); run (x);", name: "run" });
  assert.equal((html.match(/class="name"/g) || []).length, 2);
});

test("lineHtml: prose gets no syntax colours, an empty line still has height, the change keeps its colours", () => {
  assert.doesNotMatch(lineHtml({ text: "return new", prose: true }), /class="kw"/);
  assert.match(lineHtml({ text: "" }), /<span class="tx" style="--i:0ch"> <\/span>/);
  assert.match(lineHtml({ text: "x = null;", chg: [4, 8] }), /class="kw chg">null/);
});

test("lineHtml escapes code so it cannot inject markup", () => {
  assert.doesNotMatch(lineHtml({ text: `s = "<script>alert(1)</script>";` }), /<script>/);
});
