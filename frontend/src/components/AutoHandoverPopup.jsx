import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import { Handshake, Printer, CheckCircle2 } from "lucide-react";
import api, { API, formatApiErrorDetail, withAuthParam, requestDataRefresh } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

// Auto-pops the moment IT Head approval clears stock and a handover is auto-generated
// (requisition status -> pending_handover). IT Head prints it, physically delivers the
// item, then clicks "Handover Done" — which is what actually raises the requester's bell
// notification. Table layout mirrors the printed "HAND OVER" slip exactly.
export default function AutoHandoverPopup() {
  const { user } = useAuth();
  const [queue, setQueue] = useState([]); // requisitions with status pending_handover
  const [active, setActive] = useState(null); // full handover doc for the modal
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const seen = useRef(new Set());

  const isItHeadOrAdmin = user?.role === "super_admin" || (user?.role === "dept_head" && user?.department_name === "IT");

  const load = useCallback(async () => {
    if (!isItHeadOrAdmin) return;
    try {
      const { data } = await api.get("/requisitions", { params: { scope: "handover" } });
      setQueue(data);
      const fresh = data.find((r) => r.handover_id && !seen.current.has(r.handover_id));
      if (fresh && !open) {
        seen.current.add(fresh.handover_id);
        const { data: h } = await api.get(`/handovers/${fresh.handover_id}`);
        setActive(h);
        setOpen(true);
      }
    } catch (e) {
      /* silent */
    }
  }, [isItHeadOrAdmin, open]);

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  if (!isItHeadOrAdmin) return null;

  const printSlip = () => active && window.open(withAuthParam(`${API}/handovers/${active.id}/pdf`), "_blank");

  const markDone = async () => {
    if (!active) return;
    setBusy(true);
    try {
      await api.post(`/handovers/${active.id}/deliver`);
      toast.success("Handover marked done — requisition is now Waiting for User Confirmation.");
      setOpen(false);
      setActive(null);
      load();
      // Requisition moved to awaiting_requester_confirmation — refresh any mounted
      // Dashboard / RequisitionList so the status badge and counters update live.
      requestDataRefresh();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-3xl" data-testid="auto-handover-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Handshake size={18} className="text-amber-600" /> Handover Form — {active?.slip_no}</DialogTitle>
        </DialogHeader>
        {active && (
          <div className="space-y-4">
            <p className="text-sm text-slate-500">
              Stock is available — this handover was generated automatically. Print it, physically deliver the item(s), then confirm below.
            </p>
            <div className="overflow-hidden rounded-lg border border-slate-300">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-100 text-left text-xs uppercase tracking-wider text-slate-600 border-b border-slate-300">
                    <th className="px-3 py-2 font-semibold border-r border-slate-300 w-14">S.N.</th>
                    <th className="px-3 py-2 font-semibold border-r border-slate-300">Name</th>
                    <th className="px-3 py-2 font-semibold border-r border-slate-300">Dept.</th>
                    <th className="px-3 py-2 font-semibold border-r border-slate-300">Item</th>
                    <th className="px-3 py-2 font-semibold border-r border-slate-300">Brand</th>
                    <th className="px-3 py-2 font-semibold">Quantity</th>
                  </tr>
                </thead>
                <tbody>
                  {active.items.map((it, i) => (
                    <tr key={i} className="border-b border-slate-200 last:border-0" data-testid={`auto-handover-row-${i}`}>
                      <td className="px-3 py-2 border-r border-slate-200 text-slate-600">{i + 1}</td>
                      <td className="px-3 py-2 border-r border-slate-200 font-medium text-slate-800">{active.employee_name}</td>
                      <td className="px-3 py-2 border-r border-slate-200 text-slate-600">{active.department_name || "—"}</td>
                      <td className="px-3 py-2 border-r border-slate-200 text-slate-800">{it.item}</td>
                      <td className="px-3 py-2 border-r border-slate-200 text-slate-600">{it.brand || "—"}</td>
                      <td className="px-3 py-2 font-mono">{it.quantity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col sm:flex-row gap-3">
              <button onClick={printSlip} data-testid="auto-handover-print"
                className="flex-1 py-2.5 rounded-lg border border-slate-300 text-slate-600 font-semibold hover:bg-slate-50 transition-colors flex items-center justify-center gap-2">
                <Printer size={16} /> Print Handover Copy
              </button>
              <button onClick={markDone} disabled={busy} data-testid="auto-handover-done"
                className="flex-1 py-2.5 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700 transition-colors flex items-center justify-center gap-2 disabled:opacity-60">
                <CheckCircle2 size={16} /> Handover Done
              </button>
            </div>
            {queue.length > 1 && (
              <p className="text-xs text-slate-400 text-center">
                {queue.length - 1} more item{queue.length - 1 > 1 ? "s" : ""} waiting in the Handover Queue.
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}