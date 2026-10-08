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
  pending_pr: { label: "Out of Stock — Awaiting PR", cls: "bg-orange-100 text-orange-700" },
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