// Bottom left: the approver's actions. Merge is always visible; when it cannot be used it says why.
import { esc } from "./syntax.js";
import { blockers } from "./model.js";

function outcome(D, rec) {
  const merged = rec.decision === "approved";
  return `<div class="state ${merged ? "" : "hot"}"><i class="led ${merged ? "decided" : "routed"}"></i>
    ${merged ? "Merged" : "Changes requested"} by ${esc(rec.by.name)} · ${rec.at.slice(11, 16)}</div>
    ${rec.note ? `<p class="facts">“${esc(rec.note)}”</p>` : ""}
    <button class="link" data-item="MERGE" data-decision="reopen">${merged ? "Undo merge" : "Withdraw request"}</button>`;
}

const askForm = () => `<div class="ask"><label class="label" for="note">what should the agent change?</label>
  <textarea id="note" rows="3" placeholder="e.g. copy the ticket list before the thread reads it"></textarea>
  <div class="after"><button class="secondary" data-item="MERGE" data-decision="changes requested">Send request</button>
  <button class="link" data-act="cancel">Cancel</button></div></div>`;

// ui: {dec, asking}
export function approver(D, ui) {
  const ap = D.owners.approver, rec = ui.dec.MERGE;
  const head = `<div class="label">approver · ${esc(ap.name)}</div>`;
  if (rec) return head + outcome(D, rec);
  const why = blockers(D, ui.dec);
  const merge = why.length
    ? `<button class="primary off" aria-disabled="true" data-act="blocked" title="Resolve the items below first">Merge</button>`
    : `<button class="primary" data-item="MERGE" data-decision="approved">Merge</button>`;
  const list = why.length ? `<div class="why" id="why"><div class="label">blocked by ${why.length}</div>${why.map((b) =>
    `<button data-go="${esc(b.go)}" title="${esc(b.text)}">${esc(b.text)}</button>`).join("")}</div>` : `<p class="facts">Every item is proven or decided.</p>`;
  return head + merge + list + (ui.asking ? askForm() : `<button class="secondary" data-act="ask">Request changes</button>`);
}
