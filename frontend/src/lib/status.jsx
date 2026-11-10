export const STATUS_META = {
  pending_dept: { label: "Pending Dept Head", cls: "bg-amber-100 text-amber-700" },
  pending_admin: { label: "Pending Admin Head", cls: "bg-amber-100 text-amber-700" },
  waiting_stock: { label: "Waiting for Stock", cls: "bg-orange-100 text-orange-700" },
  pending_it_service: { label: "Pending IT (Service)", cls: "bg-sky-100 text-sky-700" },
  product_collected_by_it: { label: "Collected by IT", cls: "bg-sky-100 text-sky-700" },
  sent_to_service_center: { label: "At Service Center", cls: "bg-sky-100 text-sky-700" },
  service_in_progress: { label: "In Progress (IT Service)", cls: "bg-indigo-100 text-indigo-700" },
  pending_repair_approval: { label: "Pending Repair Approval (IT Head)", cls: "bg-amber-100 text-amber-700" },
  product_in_service: { label: "Product at Service Center", cls: "bg-purple-100 text-purple-700" },
  service_completed_and_returned: { label: "Service Completed", cls: "bg-emerald-100 text-emerald-700" },
  pending_it: { label: "Pending IT Head", cls: "bg-amber-100 text-amber-700" },
  pending_pr: { label: "Awaiting PR Handler Review", cls: "bg-orange-100 text-orange-700" },
  pending_pr_revision: { label: "Needs PR Revision", cls: "bg-orange-100 text-orange-700" },
  pending_it_review: { label: "Pending IT Head Approval", cls: "bg-amber-100 text-amber-700" },
  pending_po_entry: { label: "Approved — Awaiting PO Entry", cls: "bg-orange-100 text-orange-700" },
  po_draft: { label: "PO Draft — Not Submitted", cls: "bg-slate-100 text-slate-600" },
  pending_accounts: { label: "Pending Accounts Head", cls: "bg-amber-100 text-amber-700" },
  pending_md: { label: "Pending MD", cls: "bg-purple-100 text-purple-700" },
  pending_purchase: { label: "Pending Purchase Dept Head", cls: "bg-amber-100 text-amber-700" },
  buy_process: { label: "Product Buy Process in Progress", cls: "bg-indigo-100 text-indigo-700" },
  stock_received_in_it: { label: "Stock Received in IT", cls: "bg-sky-100 text-sky-700" },
  pending_handover: { label: "Ready for Handover", cls: "bg-sky-100 text-sky-700" },
  awaiting_requester_confirmation: { label: "Waiting for User Confirmation", cls: "bg-purple-100 text-purple-700" },
  handover_done: { label: "Handover Done", cls: "bg-emerald-100 text-emerald-700" },
  revision_requested: { label: "Revision Requested", cls: "bg-orange-100 text-orange-700" },
  // Purchase Order approval workflow statuses
  draft: { label: "Draft", cls: "bg-slate-100 text-slate-600" },
  pending_purchase_head_approval: { label: "Pending Purchase Head", cls: "bg-amber-100 text-amber-700" },
  pending_md_approval: { label: "Pending MD Approval", cls: "bg-purple-100 text-purple-700" },
  pending_accounts_head_approval: { label: "Pending Accounts Head", cls: "bg-amber-100 text-amber-700" },
  // approved already exists for requisitions; reuse for final PO approval
  approved: { label: "Approved", cls: "bg-emerald-100 text-emerald-700" },
  rejected: { label: "Rejected", cls: "bg-red-100 text-red-700" },
  pr_cancelled: { label: "PR Cancelled", cls: "bg-red-100 text-red-700" },
  cancelled: { label: "Cancelled by Requester", cls: "bg-slate-200 text-slate-600" },
};

export function StatusBadge({ status }) {
  const m = STATUS_META[status] || { label: status, cls: "bg-slate-100 text-slate-600" };
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${m.cls}`} data-testid={`status-${status}`}>
      {m.label}
    </span>
  );
}

export const bdt = (n) => `৳ ${Number(n || 0).toLocaleString("en-BD")}`;
// "just now", "5 minutes ago", "2 hours ago", "3 days ago" — for queue "Time" columns.
export function timeAgo(iso) {
  const t = iso ? new Date(iso).getTime() : NaN;
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  const unit = (n, w) => `${n} ${w}${n === 1 ? "" : "s"} ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return unit(m, "minute");
  const h = Math.floor(m / 60);
  if (h < 24) return unit(h, "hour");
  const d = Math.floor(h / 24);
  if (d < 30) return unit(d, "day");
  const mo = Math.floor(d / 30);
  return mo < 12 ? unit(mo, "month") : unit(Math.floor(d / 365), "year");
}

// Who sent a requisition back for revision, and what they asked for. Works for every approver:
// a normal chain step, an IT Head PR-review revision (that step is removed from the chain, so
// the note lives on the requisition), and older records (falls back to the history entry).
export function revisionFeedback(req) {
  if (!req) return null;
  const step = (req.approval_chain || []).find((s) => s.status === "revision_requested");
  if (step && step.note) return { note: step.note, by: step.approver_name, label: step.label };
  const fb = req.revision_feedback;
  if (fb && (fb.note || fb.by)) return { note: fb.note, by: fb.by, label: fb.label };
  if (req.pr_void_reason) return { note: req.pr_void_reason, by: "IT Head", label: "IT Head — PR Review" };
  const h = [...(req.history || [])].reverse().find((x) => x.action === "revise");
  if (h) return { note: h.note, by: h.by, label: null };
  return step ? { note: null, by: step.approver_name, label: step.label } : null;
}

// IT Head's "PR Revise" note (sent back to the PR Raiser, not the employee).
export function prRevisionFeedback(req) {
  if (!req) return null;
  const fb = req.pr_revision_feedback;
  if (fb && (fb.note || fb.by)) return { note: fb.note, by: fb.by, label: fb.label };
  const h = [...(req.history || [])].reverse().find((x) => x.action === "pr_revise");
  return h ? { note: h.note, by: h.by, label: null } : null;
}