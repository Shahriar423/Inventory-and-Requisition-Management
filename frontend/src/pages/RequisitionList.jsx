import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Eye, Check, X, ShieldCheck, FileText, FastForward } from "lucide-react";
import api, { API, formatApiErrorDetail } from "@/lib/apiClient";
import { StatusBadge, bdt } from "@/lib/status";
import { useAuth } from "@/context/AuthContext";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

const HEADINGS = {
  pending: { title: "Pending Requisition", subtitle: "Your requisitions still moving through approval." },
  approve: { title: "Approve Requisition", subtitle: "Requisitions awaiting your approval." },
  history: { title: "Requisition History", subtitle: "Approved and rejected requisitions." },
  purchase: { title: "File Purchase Requisition", subtitle: "Approved requisitions ready to be filed for purchase." },
};

export default function RequisitionList({ scope }) {
  const { user } = useAuth();
  const [rows, setRows] = useState([]);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchScope = scope === "purchase" ? "history" : scope;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/requisitions?scope=${fetchScope}`);
      const filtered = scope === "purchase" ? data.filter((r) => r.status === "approved") : data;
      setRows(filtered);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  }, [fetchScope, scope]);

  useEffect(() => { load(); }, [load]);

  const act = async (id, action) => {
    try {
      await api.post(`/requisitions/${id}/action`, { action });
      toast.success(action === "approve" ? "Requisition approved" : "Requisition rejected");
      setDetail(null);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  const serviceAdvance = async (id) => {
    try {
      const { data } = await api.post(`/requisitions/${id}/service-transition`, {});
      toast.success(`Moved to: ${data.status.replaceAll("_", " ")}`);
      setDetail(null);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };
  const openPdf = (id) => window.open(`${API}/requisitions/${id}/pdf`, "_blank");

  const h = HEADINGS[scope] || HEADINGS.pending;
  const canApproveHere = scope === "approve";

  return (
    <div className="space-y-6" data-testid={`req-list-${scope}`}>
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">{h.title}</h2>
        <p className="text-slate-500 text-sm mt-1">{h.subtitle}</p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
              <th className="px-6 py-3 font-semibold">Req No.</th>
              <th className="px-6 py-3 font-semibold">Requisitioner</th>
              <th className="px-6 py-3 font-semibold">Type</th>
              <th className="px-6 py-3 font-semibold">Items</th>
              <th className="px-6 py-3 font-semibold">Amount</th>
              <th className="px-6 py-3 font-semibold">Status</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="px-6 py-8 text-center text-slate-400">Loading…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={7} className="px-6 py-10 text-center text-slate-400">No requisitions found.</td></tr>}
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`req-row-${r.requisition_no}`}>
                <td className="px-6 py-3 font-mono text-slate-800">{r.requisition_no}</td>
                <td className="px-6 py-3 text-slate-700">{r.requisitioner_name}</td>
                <td className="px-6 py-3 capitalize text-slate-600">{r.requisition_type}</td>
                <td className="px-6 py-3 text-slate-600">{r.items.length}</td>
                <td className="px-6 py-3 font-mono text-slate-800">{bdt(r.total_amount)}</td>
                <td className="px-6 py-3"><StatusBadge status={r.status} /></td>
                <td className="px-6 py-3">
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={() => setDetail(r)} data-testid={`btn-view-${r.requisition_no}`}
                      className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"><Eye size={14} /> View</button>
                    {r.requisition_type === "product" && (
                      <button onClick={() => openPdf(r.id)} data-testid={`btn-pdf-${r.requisition_no}`}
                        className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"><FileText size={14} /> PDF</button>
                    )}
                    {canApproveHere && r.requisition_type === "service" && (
                      <button onClick={() => serviceAdvance(r.id)} data-testid={`btn-service-advance-${r.requisition_no}`}
                        className="px-3 py-1.5 rounded-lg bg-sky-600 text-white text-xs font-semibold hover:bg-sky-700 flex items-center gap-1.5 transition-colors"><FastForward size={14} /> Advance</button>
                    )}
                    {canApproveHere && r.requisition_type !== "service" && (
                      <>
                        <button onClick={() => act(r.id, "approve")} data-testid={`btn-approve-${r.requisition_no}`}
                          className="px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 flex items-center gap-1.5 transition-colors"><Check size={14} /> Approve</button>
                        <button onClick={() => act(r.id, "reject")} data-testid={`btn-reject-${r.requisition_no}`}
                          className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-xs font-semibold hover:bg-red-700 flex items-center gap-1.5 transition-colors"><X size={14} /> Reject</button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-w-2xl" data-testid="req-detail-dialog">
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle className="font-mono flex items-center gap-3">{detail.requisition_no}
                  <StatusBadge status={detail.status} /></DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div><div className="text-xs uppercase text-slate-400">Requisitioner</div><div className="font-medium">{detail.requisitioner_name}</div></div>
                  <div><div className="text-xs uppercase text-slate-400">Type</div><div className="font-medium capitalize">{detail.requisition_type}</div></div>
                  <div><div className="text-xs uppercase text-slate-400">Total</div><div className="font-mono font-semibold">{bdt(detail.total_amount)}</div></div>
                  <div><div className="text-xs uppercase text-slate-400">Note</div><div className="font-medium">{detail.requester_note || "—"}</div></div>
                </div>

                <div>
                  <div className="text-xs uppercase text-slate-400 mb-2">Items</div>
                  <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
                    {detail.items.map((it, i) => (
                      <div key={i} className="flex items-center justify-between px-4 py-2 text-sm">
                        <span>{it.product_name} <span className="text-slate-400">({it.product_type})</span></span>
                        <span className="font-mono">{it.quantity} × {bdt(it.rate)}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-xs uppercase text-slate-400 mb-2 flex items-center gap-1.5"><ShieldCheck size={14} /> Approval Chain</div>
                  <div className="space-y-2">
                    {detail.approval_chain.map((s, i) => (
                      <div key={i} className="flex items-center justify-between px-4 py-2 rounded-lg bg-slate-50 text-sm">
                        <span><span className="font-mono text-xs text-slate-400 mr-2">L{s.level}</span>{s.label} — <span className="font-medium">{s.approver_name || "—"}</span></span>
                        <StatusBadge status={s.status === "pending" ? (detail.status) : (s.status === "approved" ? "approved" : "rejected")} />
                      </div>
                    ))}
                  </div>
                </div>

                {(canApproveHere || detail.requisition_type === "product") && (
                  <div className="flex gap-3 pt-2">
                    {detail.requisition_type === "product" && (
                      <button onClick={() => openPdf(detail.id)} data-testid="dialog-pdf-btn" className="px-4 py-2.5 rounded-lg border border-slate-300 text-slate-600 font-semibold hover:bg-slate-50 transition-colors flex items-center gap-2"><FileText size={16} /> Purchase PDF</button>
                    )}
                    {canApproveHere && detail.requisition_type === "service" && (
                      <button onClick={() => serviceAdvance(detail.id)} data-testid="dialog-advance-btn" className="flex-1 py-2.5 rounded-lg bg-sky-600 text-white font-semibold hover:bg-sky-700 transition-colors">Advance Service Stage</button>
                    )}
                    {canApproveHere && detail.requisition_type !== "service" && (
                      <>
                        <button onClick={() => act(detail.id, "approve")} className="flex-1 py-2.5 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700 transition-colors">Approve</button>
                        <button onClick={() => act(detail.id, "reject")} className="flex-1 py-2.5 rounded-lg bg-red-600 text-white font-semibold hover:bg-red-700 transition-colors">Reject</button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
