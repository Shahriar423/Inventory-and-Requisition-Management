import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ClipboardList, Clock, CheckCircle2, TrendingUp, Inbox, XCircle } from "lucide-react";
import api from "@/lib/apiClient";
import { StatusBadge, bdt } from "@/lib/status";

function StatCard({ icon: Icon, label, value, tone, testid }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm" data-testid={testid}>
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-3 ${tone}`}>
        <Icon size={20} />
      </div>
      <div className="text-2xl font-head font-bold text-slate-900">{value}</div>
      <div className="text-xs uppercase tracking-wider text-slate-500 mt-1">{label}</div>
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.get("/dashboard/stats").then(({ data }) => setStats(data)).catch(() => {});
  }, []);

  if (!stats) return <div className="text-slate-500">Loading…</div>;

  return (
    <div className="space-y-6" data-testid="dashboard">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">Overview</h2>
        <p className="text-slate-500 text-sm mt-1">Snapshot of requisitions across the organization.</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        <StatCard icon={ClipboardList} label="Total" value={stats.total} tone="bg-slate-100 text-slate-700" testid="stat-total" />
        <StatCard icon={Clock} label="Pending" value={stats.pending} tone="bg-amber-100 text-amber-700" testid="stat-pending" />
        <StatCard icon={Inbox} label="My Approvals" value={stats.my_queue} tone="bg-sky-100 text-sky-700" testid="stat-my-queue" />
        <StatCard icon={TrendingUp} label="≥ 50k BDT" value={stats.high_value} tone="bg-purple-100 text-purple-700" testid="stat-high-value" />
        <StatCard icon={CheckCircle2} label="Approved" value={stats.approved} tone="bg-emerald-100 text-emerald-700" testid="stat-approved" />
        <StatCard icon={XCircle} label="Rejected" value={stats.rejected} tone="bg-red-100 text-red-700" testid="stat-rejected" />
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <h3 className="font-head font-semibold text-slate-900">Recent Requisitions</h3>
          <Link to="/requisitions/new" className="text-sm font-semibold text-amber-600 hover:text-amber-700" data-testid="dashboard-new-req">+ New Requisition</Link>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100">
              <th className="px-6 py-3 font-semibold">Req No.</th>
              <th className="px-6 py-3 font-semibold">Requisitioner</th>
              <th className="px-6 py-3 font-semibold">Type</th>
              <th className="px-6 py-3 font-semibold">Amount</th>
              <th className="px-6 py-3 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {stats.recent.length === 0 && (
              <tr><td colSpan={5} className="px-6 py-8 text-center text-slate-400">No requisitions yet.</td></tr>
            )}
            {stats.recent.map((r) => (
              <tr key={r.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`recent-row-${r.requisition_no}`}>
                <td className="px-6 py-3 font-mono text-slate-800">{r.requisition_no}</td>
                <td className="px-6 py-3 text-slate-700">{r.requisitioner_name}</td>
                <td className="px-6 py-3 capitalize text-slate-600">{r.requisition_type}</td>
                <td className="px-6 py-3 font-mono text-slate-800">{bdt(r.total_amount)}</td>
                <td className="px-6 py-3"><StatusBadge status={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
