import { useEffect, useState } from "react";
import { Eye, Handshake, ArrowLeftRight, FileText } from "lucide-react";
import api, { API } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export default function HandoverRecords() {
  const [rows, setRows] = useState([]);
  const [detail, setDetail] = useState(null);

  useEffect(() => { api.get("/handovers").then(({ data }) => setRows(data)).catch(() => {}); }, []);

  return (
    <div className="space-y-6" data-testid="handover-records-page">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">Handover Records</h2>
        <p className="text-slate-500 text-sm mt-1">All hand over / take over slips.</p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
            <th className="px-6 py-3 font-semibold">Slip No.</th><th className="px-6 py-3 font-semibold">Type</th><th className="px-6 py-3 font-semibold">Employee</th><th className="px-6 py-3 font-semibold">Department</th><th className="px-6 py-3 font-semibold">Items</th><th className="px-6 py-3 font-semibold">Date</th><th className="px-6 py-3 font-semibold text-right">Actions</th>
          </tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={7} className="px-6 py-10 text-center text-slate-400">No handover records yet.</td></tr>}
            {rows.map((h) => (
              <tr key={h.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`ho-row-${h.slip_no}`}>
                <td className="px-6 py-3 font-mono text-slate-800">{h.slip_no}</td>
                <td className="px-6 py-3">
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${h.type === "handover" ? "bg-amber-100 text-amber-700" : "bg-sky-100 text-sky-700"}`}>
                    {h.type === "handover" ? <Handshake size={12} /> : <ArrowLeftRight size={12} />}{h.type}
                  </span>
                </td>
                <td className="px-6 py-3 text-slate-700">{h.employee_name}</td>
                <td className="px-6 py-3 text-amber-700">{h.department_name || "—"}</td>
                <td className="px-6 py-3 text-slate-600">{h.items.length}</td>
                <td className="px-6 py-3 text-slate-500">{(h.handover_date || "").slice(0, 10)}</td>
                <td className="px-6 py-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={() => window.open(`${API}/handovers/${h.id}/pdf`, "_blank")} data-testid={`ho-pdf-${h.slip_no}`} className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"><FileText size={14} /> PDF</button>
                    <button onClick={() => setDetail(h)} data-testid={`ho-view-${h.slip_no}`} className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"><Eye size={14} /> View</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-w-lg" data-testid="ho-detail-dialog">
          {detail && (
            <>
              <DialogHeader><DialogTitle className="font-mono capitalize">{detail.slip_no} · {detail.type}</DialogTitle></DialogHeader>
              <div className="space-y-4 text-sm">
                <div className="grid grid-cols-2 gap-3">
                  <div><div className="text-xs uppercase text-slate-400">Employee</div><div className="font-medium">{detail.employee_name}</div></div>
                  <div><div className="text-xs uppercase text-slate-400">Department</div><div className="font-medium">{detail.department_name || "—"}</div></div>
                </div>
                <div>
                  <div className="text-xs uppercase text-slate-400 mb-2">Items</div>
                  <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
                    {detail.items.map((it, i) => (
                      <div key={i} className="flex items-center justify-between px-4 py-2">
                        <span>{it.item} {it.brand && <span className="text-slate-400">· {it.brand}</span>}</span>
                        <span className="font-mono">×{it.quantity}</span>
                      </div>
                    ))}
                  </div>
                </div>
                {detail.note && <div><div className="text-xs uppercase text-slate-400">Note</div><div>{detail.note}</div></div>}
                <div className="grid grid-cols-2 gap-4">
                  <SigView label="Prepared By" src={detail.prepared_by_sign} />
                  <SigView label="Received By" src={detail.received_by_sign} />
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SigView({ label, src }) {
  return (
    <div>
      <div className="text-xs uppercase text-slate-400 mb-1">{label}</div>
      {src ? <img src={src} alt={label} className="h-20 border border-slate-200 rounded-lg bg-white object-contain w-full" />
        : <div className="h-20 border border-dashed border-slate-200 rounded-lg flex items-center justify-center text-xs text-slate-300">No signature</div>}
    </div>
  );
}
