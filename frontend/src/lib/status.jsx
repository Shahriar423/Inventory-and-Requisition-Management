export const STATUS_META = {
  pending_dept: { label: "Pending Dept Head", cls: "bg-amber-100 text-amber-700" },
  pending_it_service: { label: "Pending IT (Service)", cls: "bg-sky-100 text-sky-700" },
  product_collected_by_it: { label: "Collected by IT", cls: "bg-sky-100 text-sky-700" },
  sent_to_service_center: { label: "At Service Center", cls: "bg-sky-100 text-sky-700" },
  pending_it: { label: "Pending IT Head", cls: "bg-amber-100 text-amber-700" },
  pending_accounts: { label: "Pending Accounts", cls: "bg-amber-100 text-amber-700" },
  pending_md: { label: "Pending MD", cls: "bg-purple-100 text-purple-700" },
  pending_purchase: { label: "Pending Purchase", cls: "bg-amber-100 text-amber-700" },
  approved: { label: "Approved", cls: "bg-emerald-100 text-emerald-700" },
  rejected: { label: "Rejected", cls: "bg-red-100 text-red-700" },
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
