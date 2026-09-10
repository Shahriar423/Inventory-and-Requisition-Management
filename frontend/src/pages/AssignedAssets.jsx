import { useEffect, useState } from "react";
import { User, Laptop, PackageOpen, Search, FileDown } from "lucide-react";
import api, { API } from "@/lib/apiClient";

export default function AssignedAssets() {
  const [assets, setAssets] = useState([]);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  useEffect(() => { api.get("/assets").then(({ data }) => setAssets(data)).catch(() => {}); }, []);

  const match = (a) => {
    const text = [a.name, a.serial_no, a.tag_id, a.category_name, a.assigned_to].filter(Boolean).join(" ").toLowerCase();
    if (q && !text.includes(q.toLowerCase())) return false;
    if (statusFilter && a.status !== statusFilter) return false;
    return true;
  };
  const filtered = assets.filter(match);
  const assigned = filtered.filter((a) => a.status === "assigned" && a.assigned_to);
  const stock = filtered.filter((a) => a.status !== "assigned");
  const byEmployee = assigned.reduce((acc, a) => {
    (acc[a.assigned_to] = acc[a.assigned_to] || []).push(a);
    return acc;
  }, {});

  return (
    <div className="space-y-6" data-testid="assigned-assets-page">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">Assigned Assets</h2>
          <p className="text-slate-500 text-sm mt-1">Equipment history — IT equipment in the custody of employees.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input data-testid="assets-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search assets / employees…"
              className="pl-9 pr-4 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm w-64" />
          </div>
          <select data-testid="assets-status-filter" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            className="py-2.5 px-3 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm">
            <option value="">All statuses</option>
            <option value="in_stock">In stock</option>
            <option value="pending_receipt">Pending receipt</option>
            <option value="assigned">Assigned</option>
            <option value="returned">Returned</option>
          </select>
          <button onClick={() => window.open(`${API}/assets/summary/pdf`, "_blank")} data-testid="btn-download-summary"
            className="px-4 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 transition-colors"><FileDown size={16} /> Download Summary Report</button>
        </div>
      </div>

      {Object.keys(byEmployee).length === 0 && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm py-12 text-center text-slate-400" data-testid="assigned-empty">
          <PackageOpen size={30} className="mx-auto mb-2 opacity-50" />
          No assets assigned yet. Assign assets via the Handover module.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {Object.entries(byEmployee).map(([emp, list]) => (
          <div key={emp} className="bg-white rounded-xl border border-slate-200 shadow-sm p-5" data-testid={`assigned-card-${emp}`}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center"><User size={18} /></div>
              <div>
                <div className="font-head font-semibold text-slate-900">{emp}</div>
                <div className="text-xs text-slate-400">{list.length} asset(s)</div>
              </div>
            </div>
            <div className="space-y-2">
              {list.map((a) => (
                <div key={a.id} className="flex items-center gap-2 text-sm bg-slate-50 rounded-lg px-3 py-2">
                  <Laptop size={14} className="text-slate-400" />
                  <span className="font-medium text-slate-700">{a.name}</span>
                  <span className="ml-auto font-mono text-xs text-amber-700">{a.tag_id || a.serial_no || "—"}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-6 py-4 border-b border-slate-100 font-head font-semibold text-slate-900">Available Stock ({stock.length})</div>
        <div className="p-5 flex flex-wrap gap-2">
          {stock.length === 0 && <span className="text-slate-400 text-sm">No unassigned stock.</span>}
          {stock.map((a) => (
            <span key={a.id} className="px-3 py-1.5 rounded-lg bg-slate-100 text-slate-700 text-xs font-medium" data-testid={`stock-chip-${a.id}`}>
              {a.name} · <span className="font-mono text-amber-700">{a.tag_id || a.serial_no || "—"}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
