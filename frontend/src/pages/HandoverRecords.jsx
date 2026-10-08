import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Eye, Handshake, ArrowLeftRight, RefreshCw, FileText, CheckCircle2, PackageCheck } from "lucide-react";
import api, { API, formatApiErrorDetail, withAuthParam } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const TYPE_META = {
  handover: { label: "Handover", cls: "bg-emerald-100 text-emerald-700", Icon: Handshake },
  takeover: { label: "Takeover", cls: "bg-sky-100 text-sky-700", Icon: ArrowLeftRight },
  swap: { label: "Swap", cls: "bg-amber-100 text-amber-700", Icon: RefreshCw },
};
const CONDITIONS = [["good", "Good"], ["damaged", "Damaged"], ["missing_parts", "Missing parts"]];
const DESTINATIONS = [["in_stock", "Back to stock"], ["under_repair", "Under repair"], ["scrapped", "Scrap"]];
const DEST_LABEL = Object.fromEntries(DESTINATIONS);
const COND_LABEL = Object.fromEntries(CONDITIONS);

// One place that decides what the Status column says, for every slip type.
// Old takeover slips (created before return tracking) have no return_items and stay "Recorded".
function statusOf(h) {
  const hasReturns = (h.return_items || []).length > 0;
  if (h.type === "takeover") {
    if (!hasReturns) return { label: "Recorded", cls: "bg-slate-100 text-slate-500" };
    return h.status === "completed"
      ? { label: "Completed ✓ Received by IT", cls: "bg-emerald-100 text-emerald-700" }
      : { label: "Awaiting IT receipt", cls: "bg-amber-100 text-amber-700" };
  }
  if (h.status === "confirmed") {
    return { label: h.type === "swap" ? "Completed ✓ Confirmed" : "Delivered ✓ Confirmed", cls: "bg-emerald-100 text-emerald-700" };
  }
  if (h.status === "delivered") return { label: "Awaiting Confirmation", cls: "bg-sky-100 text-sky-700" };
  return { label: "Prepared", cls: "bg-amber-100 text-amber-700" };
}

export default function HandoverRecords() {
  const [rows, setRows] = useState([]);
  const [detail, setDetail] = useState(null);
  const [recv, setRecv] = useState(null);      // slip being received: {slip, lines: {asset_id: {...}}}
  const [busy, setBusy] = useState(false);

  const load = () => { api.get("/handovers").then(({ data }) => setRows(data)).catch(() => {}); };
  useEffect(load, []);

  const markDelivered = async (h) => {
    try {
      await api.post(`/handovers/${h.id}/deliver`);
      toast.success(h.type === "swap"
        ? "Done - old device received, new device delivered. Waiting for the employee to confirm receipt."
        : "Marked delivered — waiting for the employee to confirm receipt on their bell notification.");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
      load();
    }
  };

  const openReceive = (h) => setRecv({
    slip: h,
    lines: Object.fromEntries((h.return_items || []).map((r) => [r.asset_id, {
      condition: r.condition || "good", next_status: r.next_status || "in_stock",
      data_wiped: !!r.data_wiped, accessories: r.accessories || [],
    }])),
  });
  const setLine = (id, patch) => setRecv((r) => ({ ...r, lines: { ...r.lines, [id]: { ...r.lines[id], ...patch } } }));

  const confirmReceive = async () => {
    setBusy(true);
    try {
      const lines = Object.entries(recv.lines).map(([asset_id, v]) => ({ asset_id, ...v }));
      await api.post(`/handovers/${recv.slip.id}/receive-return`, { lines });
      toast.success("Received - asset status updated.");
      setRecv(null);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
      load();
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-6" data-testid="handover-records-page">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">Handover Records</h2>
        <p className="text-slate-500 text-sm mt-1">All hand over / take over / replacement slips.</p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
            <th className="px-6 py-3 font-semibold">Slip No.</th><th className="px-6 py-3 font-semibold">Type</th><th className="px-6 py-3 font-semibold">Employee</th><th className="px-6 py-3 font-semibold">Department</th><th className="px-6 py-3 font-semibold">Items</th><th className="px-6 py-3 font-semibold">Status</th><th className="px-6 py-3 font-semibold">Date</th><th className="px-6 py-3 font-semibold text-right">Actions</th>
          </tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={8} className="px-6 py-10 text-center text-slate-400">No handover records yet.</td></tr>}
            {rows.map((h) => {
              const m = TYPE_META[h.type] || TYPE_META.takeover;
              const st = statusOf(h);
              const outN = (h.items || []).length;
              const inN = (h.return_items || []).length;
              const needsReceipt = inN > 0 && !h.return_received;
              return (
                <tr key={h.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`ho-row-${h.slip_no}`}>
                  <td className="px-6 py-3 font-mono text-slate-800">{h.slip_no}</td>
                  <td className="px-6 py-3">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${m.cls}`}>
                      <m.Icon size={12} />{m.label}
                    </span>
                  </td>
                  <td className="px-6 py-3 text-slate-700">{h.employee_name}</td>
                  <td className="px-6 py-3 text-amber-700">{h.department_name || "—"}</td>
                  <td className="px-6 py-3 text-slate-600">
                    {h.type === "swap" ? `${outN} out / ${inN} in` : h.type === "takeover" && inN > 0 ? `${inN} in` : outN}
                  </td>
                  <td className="px-6 py-3">
                    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${st.cls}`}>{st.label}</span>
                  </td>
                  <td className="px-6 py-3 text-slate-500">{(h.handover_date || "").slice(0, 10)}</td>
                  <td className="px-6 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {needsReceipt && (
                        <button onClick={() => openReceive(h)} data-testid={`ho-receive-${h.slip_no}`}
                          title={h.type === "swap" ? "Receive the old device now (Handover Done also does this)" : "Confirm IT has the device"}
                          className="px-3 py-1.5 rounded-lg bg-sky-600 text-white text-xs font-semibold hover:bg-sky-700 flex items-center gap-1.5 transition-colors"><PackageCheck size={14} /> Received by IT</button>
                      )}
                      {(h.type === "handover" || h.type === "swap") && h.status === "prepared" && (
                        <button onClick={() => markDelivered(h)} data-testid={`ho-deliver-${h.slip_no}`}
                          title={h.type === "swap" ? "Receives the old device and delivers the new one" : undefined}
                          className="px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 flex items-center gap-1.5 transition-colors"><CheckCircle2 size={14} /> Handover Done</button>
                      )}
                      <button onClick={() => window.open(withAuthParam(`${API}/handovers/${h.id}/pdf`), "_blank")} data-testid={`ho-pdf-${h.slip_no}`} className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"><FileText size={14} /> PDF</button>
                      <button onClick={() => setDetail(h)} data-testid={`ho-view-${h.slip_no}`} className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"><Eye size={14} /> View</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Slip details */}
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
                {(detail.return_items || []).length > 0 && (
                  <div>
                    <div className="text-xs uppercase text-slate-400 mb-2">Returned by employee {detail.return_received ? "· received" : "· awaiting IT"}</div>
                    <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
                      {detail.return_items.map((it, i) => (
                        <div key={i} className="px-4 py-2">
                          <div className="flex items-center justify-between">
                            <span>{it.item} {it.brand && <span className="text-slate-400">· {it.brand}</span>}</span>
                            <span className="font-mono text-slate-500 text-xs">{it.tag_id || it.serial_no || "—"}</span>
                          </div>
                          <div className="text-xs text-slate-500 mt-0.5">
                            {COND_LABEL[it.condition] || "—"} → {DEST_LABEL[it.next_status] || "—"}
                            {(it.accessories || []).length > 0 && ` · with ${it.accessories.join(", ")}`}
                            {it.data_wiped && " · data wiped"}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {(detail.items || []).length > 0 && (
                  <div>
                    <div className="text-xs uppercase text-slate-400 mb-2">{detail.type === "swap" ? "Issued to employee" : "Items"}</div>
                    <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
                      {detail.items.map((it, i) => (
                        <div key={i} className="flex items-center justify-between px-4 py-2">
                          <span>{it.item} {it.brand && <span className="text-slate-400">· {it.brand}</span>}</span>
                          <span className="font-mono">×{it.quantity}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
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

      {/* Received by IT: confirm / correct condition and destination while inspecting the device */}
      <Dialog open={!!recv} onOpenChange={(o) => !o && !busy && setRecv(null)}>
        <DialogContent className="max-w-xl" data-testid="ho-receive-dialog">
          {recv && (
            <>
              <DialogHeader><DialogTitle className="font-mono">Receive returned assets · {recv.slip.slip_no}</DialogTitle></DialogHeader>
              <p className="text-sm text-slate-500">Check each device and correct anything that differs from what was entered on the slip.</p>
              <div className="space-y-3 max-h-[55vh] overflow-y-auto">
                {recv.slip.return_items.map((r) => {
                  const v = recv.lines[r.asset_id];
                  return (
                    <div key={r.asset_id} className="border border-slate-200 rounded-lg p-3 space-y-2" data-testid={`ho-receive-line-${r.asset_id}`}>
                      <div className="flex items-center justify-between text-sm">
                        <span className="font-medium">{r.item}</span>
                        <span className="font-mono text-xs text-slate-500">{r.tag_id || r.serial_no || "—"}</span>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Condition
                          <select value={v.condition} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-normal normal-case tracking-normal text-slate-800"
                            onChange={(e) => setLine(r.asset_id, { condition: e.target.value, next_status: e.target.value === "good" ? "in_stock" : (v.next_status === "in_stock" ? "under_repair" : v.next_status) })}>
                            {CONDITIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                          </select>
                        </label>
                        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Then
                          <select value={v.next_status} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-normal normal-case tracking-normal text-slate-800"
                            onChange={(e) => setLine(r.asset_id, { next_status: e.target.value })}>
                            {DESTINATIONS.filter(([k]) => k !== "in_stock" || v.condition === "good").map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                          </select>
                        </label>
                      </div>
                      <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
                        <input type="checkbox" checked={v.data_wiped} onChange={(e) => setLine(r.asset_id, { data_wiped: e.target.checked })} /> Data wiped
                      </label>
                    </div>
                  );
                })}
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button onClick={() => setRecv(null)} disabled={busy} className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 text-sm font-semibold hover:bg-slate-50 disabled:opacity-50">Cancel</button>
                <button onClick={confirmReceive} disabled={busy} data-testid="ho-receive-confirm" className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold disabled:opacity-60">{busy ? "Saving…" : "Confirm received"}</button>
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