import { useEffect, useState } from "react";
import { Boxes, Search } from "lucide-react";
import api from "@/lib/apiClient";

const STATUS_CLS = {
  in_stock: "bg-emerald-100 text-emerald-700",
  pending_receipt: "bg-sky-100 text-sky-700",
  assigned: "bg-amber-100 text-amber-700",
  returned: "bg-slate-100 text-slate-600",
};

export default function StockList() {
  const [assets, setAssets] = useState([]);
  const [q, setQ] = useState("");

  useEffect(() => { api.get("/assets").then(({ data }) => setAssets(data)).catch(() => {}); }, []);

  const filtered = assets.filter((a) =>
    [a.name, a.serial_no, a.tag_id, a.category_name].filter(Boolean).join(" ").toLowerCase().includes(q.toLowerCase())
  );

  return (
    <div className="space-y-6" data-testid="stock-list-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">Stock List</h2>
          <p className="text-slate-500 text-sm mt-1">All tagged assets received into stock.</p>
        </div>
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input data-testid="stock-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search assets…"
            className="pl-9 pr-4 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm w-64" />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
            <th className="px-6 py-3 font-semibold">Asset</th><th className="px-6 py-3 font-semibold">Serial No.</th><th className="px-6 py-3 font-semibold">Tag / Asset ID</th><th className="px-6 py-3 font-semibold">Category</th><th className="px-6 py-3 font-semibold">Status</th><th className="px-6 py-3 font-semibold">Assigned To</th>
          </tr></thead>
          <tbody>
            {filtered.length === 0 && <tr><td colSpan={6} className="px-6 py-10 text-center text-slate-400"><Boxes size={28} className="mx-auto mb-2 opacity-50" />No assets in stock. Receive stock via Stock GRN.</td></tr>}
            {filtered.map((a) => (
              <tr key={a.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`stock-row-${a.id}`}>
                <td className="px-6 py-3 font-medium text-slate-800">{a.name}</td>
                <td className="px-6 py-3 font-mono text-slate-600">{a.serial_no || "—"}</td>
                <td className="px-6 py-3 font-mono text-amber-700">{a.tag_id || "—"}</td>
                <td className="px-6 py-3 text-slate-600">{a.category_name || "—"}</td>
                <td className="px-6 py-3"><span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${STATUS_CLS[a.status] || "bg-slate-100 text-slate-600"}`}>{a.status.replace("_", " ")}</span></td>
                <td className="px-6 py-3 text-slate-700">{a.assigned_to || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
