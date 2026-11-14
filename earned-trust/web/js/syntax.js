// Code lines as HTML: syntax colours, the changed part, the function's name, a hanging indent.

export const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const KW = "abstract|as|async|await|base|bool|boolean|break|case|catch|char|class|const|continue|default|delegate|do|double|else|enum|"
  + "event|extends|false|final|finally|for|foreach|get|if|implements|import|in|init|instanceof|int|interface|internal|is|long|"
  + "nameof|namespace|new|not|null|object|out|override|package|params|partial|private|protected|public|readonly|record|ref|"
  + "return|sealed|set|static|string|struct|super|switch|synchronized|this|throw|throws|true|try|typeof|using|var|virtual|"
  + "void|volatile|when|where|while|yield|and|or";
const TOK = new RegExp(String.raw`(//.*$|^\s*\*.*$|/\*.*$)|(@?"(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)')|\b(${KW})\b|`
  + String.raw`\b(\d[\d_]*(?:\.\d+)?)\b|(@[A-Za-z]\w*|\b[A-Z]\w*\b)`, "g");
const KIND = ["com", "str", "kw", "num", "type"];

export function tokens(text) {
  return [...text.matchAll(TOK)].map((m) => [m.index, m.index + m[0].length, KIND[m.slice(1).findIndex(Boolean)]]);
}

// Paint text from overlapping ranges [start, end, class].
export function paint(text, ranges) {
  const cuts = [...new Set([0, text.length, ...ranges.flatMap(([a, b]) => [a, b])])]
    .filter((x) => x >= 0 && x <= text.length).sort((a, b) => a - b);
  let out = "";
  for (let i = 0; i < cuts.length - 1; i++) {
    const [a, b] = [cuts[i], cuts[i + 1]], cls = [...new Set(ranges.filter(([s, e]) => s <= a && e >= b).map((r) => r[2]))];
    const seg = esc(text.slice(a, b));
    out += cls.length ? `<span class="${cls.join(" ")}">${seg}</span>` : seg;
  }
  return out;
}

export const expand = (t) => t.replace(/\t/g, "    ");
// Leading indentation as tabs (drawn 2 columns wide), so deep nesting does not push code off screen.
export const tabify = (t) => t.replace(/^(?: {4})+/, (m) => "\t".repeat(m.length / 4));
export function dedent(texts) {
  const d = Math.min(...texts.filter((t) => t.trim()).map((t) => t.search(/\S/)));
  return (t) => t.slice(Number.isFinite(d) ? d : 0);
}

// One line. Leading indentation becomes a hanging indent: wrapped parts stay under the line, 4 columns in.
export function lineHtml({ old = "", nu = "", sign = "", text, cls = "", prose = false, chg = null, name = "", id = "" }) {
  const ranges = prose ? [] : tokens(text);
  if (chg && chg[1] > chg[0]) ranges.push([chg[0], chg[1], "chg"]);
  if (name) for (const m of text.matchAll(new RegExp(String.raw`\b${name}\b(?=\s*[(<])`, "g"))) ranges.push([m.index, m.index + m[0].length, "name"]);
  const lead = text.match(/^[\t ]*/)[0], L = lead.length;
  const cols = [...lead].reduce((n, c) => n + (c === "\t" ? 2 : 1), 0);
  const body = paint(text.slice(L), ranges.map(([a, b, c]) => [Math.max(0, a - L), Math.max(0, b - L), c]));
  return `<div class="ln ${cls}"${id ? ` id="${id}"` : ""}><span class="gut"><span>${old}</span><span>${nu}</span>`
    + `<span class="sg">${sign}</span></span><span class="tx" style="--i:${cols}ch">${body || " "}</span></div>`;
}
