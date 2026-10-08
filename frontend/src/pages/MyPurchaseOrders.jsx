import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PackageOpen } from "lucide-react";
import api from "@/lib/apiClient";
import { bdt, StatusBadge } from "@/lib/status";

// Purchase Orders created by the logged-in user (mirrors "PRs Filed by Me").
export default function MyPurchaseOrders() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);

  useEffect(() => {
    api.get("/purchase-orders", { params: { mine: true } })
      .then(({ data }) => setRows(Array.isArray(data) ? data : []))
      .catch(() => setRows([]));
  }, []);

  return (
    <div className="space-y-6" data-testid="my-pos-page">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">Purchase Orders Created by Me</h2>
        <p className="text-slate-500 text-sm mt-1">Every PO you created, with its current approval status.</p>
      </div>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100">
              <th className="px-6 py-3 font-semibold">PO No.</th>
              <th className="px-6 py-3 font-semibold">Requisition</th>
              <th className="px-6 py-3 font-semibold">Vendor</th>
              <th className="px-6 py-3 font-semibold">Date</th>
              <th className="px-6 py-3 font-semibold text-right">Amount</th>
              <th className="px-6 py-3 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows === null && <tr><td colSpan={6} className="px-6 py-8 text-center text-slate-400">Loading…</td></tr>}
            {rows && rows.length === 0 && (
              <tr><td colSpan={6} className="px-6 py-10 text-center text-slate-400">
                <PackageOpen size={28} className="mx-auto mb-2 opacity-50" /> You haven't created any Purchase Orders yet.
              </td></tr>
            )}
            {(rows || []).map((po) => (
              <tr key={po.id} onClick={() => navigate(`/purchase/orders/${po.id}`)}
                className="border-b border-slate-50 hover:bg-slate-50/60 cursor-pointer transition-colors" data-testid={`my-po-${po.po_number}`}>
                <td className="px-6 py-3 font-mono text-slate-800">{String(po.po_number ?? "—")}</td>
                <td className="px-6 py-3 font-mono text-slate-600">{String(po.requisition_no || "—")}</td>
                <td className="px-6 py-3 text-slate-700">{String(po.vendor_name || "—")}</td>
                <td className="px-6 py-3 text-slate-600">{String(po.po_date || "—")}</td>
                <td className="px-6 py-3 font-mono text-slate-800 text-right">{bdt(po.grand_total)}</td>
                <td className="px-6 py-3"><StatusBadge status={po.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}