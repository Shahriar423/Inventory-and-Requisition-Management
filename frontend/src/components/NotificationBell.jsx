import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Bell, CheckCircle2, ClipboardList, Package, ThumbsDown, Upload, X } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail, requestDataRefresh } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

const REASONS = [
  ["wrong_spec", "Wrong size or specification"], ["wrong_model", "Wrong model or brand"], ["damaged", "Damaged or not working"],
  ["missing_accessory", "Missing accessory"], ["quantity_short", "Quantity short"], ["nothing_delivered", "Nothing delivered"], ["other", "Other"],
];
const CORRECTION_TYPES = ["correction_reported", "correction_update", "correction_clarification", "correction_reminder", "correction_escalated"];

function SpecRow({ label, requested, delivered, mono }) {
  const a = (requested || "").toString().trim().toLowerCase();
  const b = (delivered || "").toString().trim().toLowerCase();
  const differs = a && b && !b.includes(a) && !a.includes(b);
  return (
    <tr className="border-t border-slate-100">
      <td className="py-1.5 pr-3 text-xs text-slate-500 whitespace-nowrap">{label}</td>
      <td className="py-1.5 pr-3 text-slate-700">{requested || <span className="text-slate-300">—</span>}</td>
      <td className={`py-1.5 ${mono ? "font-mono text-xs" : ""} ${differs ? "text-red-600 font-semibold" : "text-slate-800"}`}>{delivered || <span className="text-slate-300">—</span>}</td>
    </tr>
  );
}

export default function NotificationBell() {
  const navigate = useNavigate();
  const [notes, setNotes] = useState([]);
  const [active, setActive] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [mode, setMode] = useState("view");            // "view" | "reject"
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [photo, setPhoto] = useState(null);
  const [busy, setBusy] = useState(false);
  const seenInfo = useRef(new Set());

  const load = useCallback(async () => {
    try {
      let { data } = await api.get("/notifications");
      data = data.filter((n) => n.status !== "correction");   // reported items leave the bell
      setNotes(data);
      // Informational notifications: surface as a toast once, but keep them in the list until dismissed.
      for (const n of data) {
        if (n.type !== "asset_receipt" && n.status === "unread" && !seenInfo.current.has(n.id)) {
          seenInfo.current.add(n.id);
          (n.type === "handover_not_received" || n.type === "correction_escalated" ? toast.warning : toast.message)(
            n.message || "You have a new notification", { position: "top-center", duration: 12000 });
        }
      }
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 25000);
    return () => clearInterval(t);
  }, [load]);

  const closeDialog = () => { setConfirmOpen(false); setActive(null); setMode("view"); setReason(""); setNote(""); setPhoto(null); };

  const confirmReceived = async () => {
    if (!active) return;
    setBusy(true);
    try {
      await api.post(`/notifications/${active.id}/confirm`, { action: "received" });
      toast.success("Receipt confirmed — thank you");
      requestDataRefresh();
      closeDialog();
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
    setBusy(false);
  };

  const submitProblem = async () => {
    if (!active) return;
    if (!reason) return toast.error("Choose what is wrong");
    if (note.trim().length < 3) return toast.error("Please explain the problem in writing");
    setBusy(true);
    try {
      let fileId = null, fileName = null;
      if (photo) {
        const fd = new FormData();
        fd.append("file", photo);
        const { data } = await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
        fileId = data.id; fileName = data.original_filename || photo.name;
      }
      await api.post("/corrections", { notification_id: active.id, reason, note: note.trim(), attachment_file_id: fileId, attachment_name: fileName });
      toast.success("Reported to IT. They have been notified and will correct it.");
      requestDataRefresh();
      closeDialog();
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not send the report");
    }
    setBusy(false);
  };

  const dismissInfo = async (n, e) => {
    e?.stopPropagation();
    try {
      await api.post(`/notifications/${n.id}/read`);
      setNotes((prev) => prev.filter((x) => x.id !== n.id));
      requestDataRefresh();
    } catch { /* silent */ }
  };

  const onNoteClick = async (n) => {
    if (n.type === "asset_receipt" && n.status !== "correction") {
      setActive(n); setMode("view"); setConfirmOpen(true); setListOpen(false);
    } else if (n.type === "asset_receipt" && n.correction_case_id) {
      navigate(`/corrections/${n.correction_case_id}`); setListOpen(false);
    } else if (CORRECTION_TYPES.includes(n.type) && n.link) {
      setListOpen(false);
      navigate(n.link);
      try { await api.post(`/notifications/${n.id}/read`); setNotes((p) => p.filter((x) => x.id !== n.id)); } catch { /* silent */ }
    }
  };

  const unreadCount = notes.filter((n) => n.status !== "correction").length;
  const d = active?.delivered || {};
  const r = active?.requested || {};

  return (
    <>
      <Popover open={listOpen} onOpenChange={setListOpen}>
        <PopoverTrigger asChild>
          <button className="relative text-slate-500 hover:text-slate-800 transition-colors" data-testid="notifications-btn">
            <Bell size={28} />
            {unreadCount > 0 && (
              <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1 bg-red-500 text-white text-[10px] font-semibold rounded-full flex items-center justify-center" data-testid="notif-count">
                {unreadCount}
              </span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 p-0" data-testid="notification-list">
          <div className="px-3 py-2 border-b border-slate-100"><h3 className="text-sm font-semibold text-slate-800">Notifications</h3></div>
          {notes.length === 0 ? (
            <div className="px-3 py-6 text-center text-sm text-slate-500">No new notifications</div>
          ) : (
            <ul className="max-h-80 overflow-y-auto divide-y divide-slate-100">
              {notes.map((n) => {
                const reported = n.status === "correction";
                const clickable = n.type === "asset_receipt" || (CORRECTION_TYPES.includes(n.type) && n.link);
                return (
                  <li key={n.id} onClick={() => onNoteClick(n)} data-testid={`notif-item-${n.id}`}
                    className={`px-3 py-2.5 text-sm hover:bg-slate-50 transition-colors ${clickable ? "cursor-pointer" : ""} ${n.type === "handover_not_received" || n.type === "correction_escalated" ? "bg-red-50" : ""} ${reported ? "bg-amber-50" : ""}`}>
                    <div className="flex gap-2.5 items-start">
                      <div className="mt-0.5 shrink-0">
                        {reported ? <ClipboardList size={16} className="text-amber-600" />
                          : n.type === "asset_receipt" ? <CheckCircle2 size={16} className="text-emerald-600" />
                          : n.type === "handover_not_received" || n.type === "correction_escalated" ? <AlertTriangle size={16} className="text-red-600" />
                          : CORRECTION_TYPES.includes(n.type) ? <ClipboardList size={16} className="text-sky-600" />
                          : <Package size={16} className="text-amber-600" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        {reported ? (
                          <>
                            <p className="font-medium text-amber-800 leading-snug">Reported to IT — Waiting for Correction</p>
                            <p className="text-xs text-slate-600 mt-0.5">{n.asset_name} · tap to see progress</p>
                          </>
                        ) : (
                          <p className="text-slate-700 leading-snug">{n.message || (n.type === "asset_receipt" ? `Please confirm receipt of ${n.asset_name || "item"}` : "You have a new notification")}</p>
                        )}
                        {n.type === "asset_receipt" && n.slip_no && <p className="text-xs text-slate-400 mt-0.5 font-mono">Slip {n.slip_no}</p>}
                        {n.created_at && <p className="text-[11px] text-slate-400 mt-1">{new Date(n.created_at).toLocaleString()}</p>}
                      </div>
                      {n.type !== "asset_receipt" && (
                        <button onClick={(e) => dismissInfo(n, e)} className="shrink-0 p-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100" title="Dismiss" data-testid={`notif-dismiss-${n.id}`}>
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </PopoverContent>
      </Popover>

      <Dialog open={confirmOpen} onOpenChange={(o) => { if (!o) closeDialog(); }}>
        <DialogContent className="max-w-xl max-h-[92vh] overflow-y-auto" data-testid="receipt-modal">
          <DialogHeader><DialogTitle>{mode === "reject" ? "Report a problem with this item" : "Confirm Asset Receipt"}</DialogTitle></DialogHeader>
          {active && (
            <div className="space-y-4">
              <p className="text-sm text-slate-600">
                Handed over to you on slip <span className="font-mono font-semibold">{active.slip_no}</span>
                {active.requisition_no && <> for <span className="font-mono">{active.requisition_no}</span></>}. Check it against what you asked for.
              </p>

              <div className="rounded-lg border border-slate-200 p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <div className="font-semibold text-slate-800" data-testid="receipt-asset-name">{active.asset_name}</div>
                  {(d.category || r.category) && <div className="text-xs text-slate-500">{d.category || r.category}</div>}
                </div>
                <table className="w-full text-sm mt-2">
                  <thead><tr className="text-left text-[11px] uppercase tracking-wide text-slate-400">
                    <th className="pb-1 pr-3 font-semibold"> </th><th className="pb-1 pr-3 font-semibold">You requested</th><th className="pb-1 font-semibold">You received</th></tr></thead>
                  <tbody>
                    <SpecRow label="Product" requested={r.product_name || active.asset_name} delivered={d.name || active.asset_name} />
                    <SpecRow label="Specification / size" requested={r.detailed_specs} delivered={d.specification} />
                    <SpecRow label="Brand" requested={r.preferred_brand} delivered={d.brand} />
                    <SpecRow label="Model" requested={r.model} delivered={d.model} />
                  </tbody>
                </table>
              </div>

              {mode === "view" ? (
                <div className="flex flex-col gap-2.5">
                  <button onClick={confirmReceived} disabled={busy} data-testid="receipt-yes"
                    className="w-full h-12 px-4 rounded-xl bg-emerald-600 text-white text-[15px] font-semibold shadow-sm hover:bg-emerald-700 active:scale-[0.99] disabled:opacity-60 transition flex items-center justify-center gap-2.5">
                    <CheckCircle2 size={20} className="shrink-0" />
                    <span>Yes, I Received the Correct Item</span>
                  </button>
                  <button onClick={() => setMode("reject")} disabled={busy} data-testid="receipt-no"
                    className="w-full h-12 px-4 rounded-xl border border-red-300 bg-white text-red-700 text-[15px] font-semibold hover:bg-red-50 active:scale-[0.99] disabled:opacity-60 transition flex items-center justify-center gap-2.5">
                    <ThumbsDown size={20} className="shrink-0" />
                    <span>No, Not Received / Not Correct</span>
                  </button>
                </div>
              ) : (
                <div className="space-y-3" data-testid="reject-form">
                  <label className="block">
                    <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">What is wrong? *</span>
                    <select value={reason} onChange={(e) => setReason(e.target.value)} data-testid="reject-reason"
                      className="w-full h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:border-amber-500">
                      <option value="">Select a reason…</option>
                      {REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </label>
                  <label className="block">
                    <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Explain the problem *</span>
                    <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} data-testid="reject-note"
                      placeholder="For example: I asked for a 21 inch monitor but this one is 18 inch."
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-amber-500 resize-none" />
                  </label>
                  <label className="flex items-center gap-3 rounded-lg border border-dashed border-slate-300 px-3 py-2.5 text-sm text-slate-600 cursor-pointer hover:bg-slate-50">
                    <Upload size={16} className="text-slate-400" />
                    <span className="flex-1 truncate">{photo ? photo.name : "Attach a photo (optional)"}</span>
                    {photo && <button type="button" onClick={(e) => { e.preventDefault(); setPhoto(null); }} className="text-slate-400 hover:text-slate-700"><X size={14} /></button>}
                    <input type="file" accept="image/*" className="hidden" data-testid="reject-photo" onChange={(e) => setPhoto(e.target.files?.[0] || null)} />
                  </label>
                  <div className="flex gap-3 pt-1">
                    <button onClick={() => setMode("view")} disabled={busy} className="px-4 py-2.5 rounded-lg border border-slate-300 text-slate-600 font-semibold hover:bg-slate-50">Back</button>
                    <button onClick={submitProblem} disabled={busy} data-testid="reject-submit"
                      className="flex-1 py-2.5 rounded-lg bg-red-600 text-white font-semibold hover:bg-red-700 disabled:opacity-60">
                      {busy ? "Sending…" : "Report to IT"}
                    </button>
                  </div>
                  <p className="text-xs text-slate-500">Only this item is reported. Other items you received are not affected, and you can still confirm them.</p>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}