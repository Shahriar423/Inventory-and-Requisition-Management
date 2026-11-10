import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { FileBarChart, Loader2 } from "lucide-react";
import api from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { PERM_LABELS } from "@/components/reports/PermBoxes";
import ReportViewer from "@/components/reports/ReportViewer";
import { errorMessage, fmtDateTime } from "@/components/reports/reportUtils";

export default function MyReports() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { allowed, menu } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (id) return;
    setLoading(true);
    api.get("/reports/mine")
      .then(({ data }) => setRows(data))
      .catch(async (e) => setError(await errorMessage(e, "Could not load your reports.")))
      .finally(() => setLoading(false));
  }, [id]);

  // the menu entry only exists while the user holds an active grant
  if (menu.length > 0 && !(allowed || []).includes("my-reports")) return <Navigate to="/" replace />;

  if (id) {
    return <ReportViewer reportId={id} onBack={() => navigate("/reports/mine")} />;
  }

  return (
    <div className="space-y-6" data-testid="my-reports">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">My Reports</h2>
        <p className="text-slate-500 text-sm mt-1">Reports shared with you. Each one always shows the latest data you are allowed to see.</p>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2.5">Report name</th><th className="px-4 py-2.5">Type</th>
              <th className="px-4 py-2.5">Description</th><th className="px-4 py-2.5">Access</th><th className="px-4 py-2.5">Last opened</th>
              <th className="px-4 py-2.5 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-100 hover:bg-blue-50/40">
                <td className="px-4 py-3 font-medium text-slate-800">{r.name}</td>
                <td className="px-4 py-3 text-slate-600">{r.type_label}</td>
                <td className="px-4 py-3 text-slate-500 max-w-xs truncate">{r.description || r.scope_label}</td>
                <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">{(r.permissions || ["read"]).map((k) => PERM_LABELS[k]).join(" · ")}</td>
                <td className="px-4 py-3 text-slate-500 whitespace-nowrap">{r.last_opened_at ? fmtDateTime(r.last_opened_at) : "Never"}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => navigate(`/reports/mine/${r.id}`)} data-testid={`open-report-${r.id}`}
                    className="h-8 px-3 rounded-md bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700">Open</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" /> Loading…</div>}
        {!loading && error && <div className="py-12 text-center text-sm text-red-600">{error}</div>}
        {!loading && !error && rows.length === 0 && (
          <div className="py-14 text-center text-sm text-slate-500"><FileBarChart className="mx-auto mb-2 text-slate-400" size={22} />No reports have been shared with you yet.</div>
        )}
      </div>
    </div>
  );
}