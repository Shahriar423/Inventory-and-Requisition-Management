import { useEffect, useRef, useState, useCallback } from "react";
import { Bell, CheckCircle2, Clock, Package, X } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail, requestDataRefresh } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export default function NotificationBell() {
  const [notes, setNotes] = useState([]);
  const [active, setActive] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const seenInfo = useRef(new Set());

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/notifications");
      setNotes(data);
      // Informational notifications (e.g. stock has arrived in IT and is being prepared for
      // handover): surface as a toast once, but do NOT mark them read so they stay in the
      // notification list until the user dismisses them.
      // Asset receipt notifications also stay in the list — the confirm dialog only opens
      // when the user clicks the item in the notification list (never auto-popup).
      for (const n of data) {
        if (n.type !== "asset_receipt" && n.status === "unread" && !seenInfo.current.has(n.id)) {
          seenInfo.current.add(n.id);
          toast.message(n.message || "You have a new notification", { position: "top-center", duration: 8000 });
        }
      }
    } catch (e) {
      /* silent */
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 25000); // 25s polling
    return () => clearInterval(t);
  }, [load]);

  const act = async (action) => {
    if (!active) return;
    try {
      await api.post(`/notifications/${active.id}/confirm`, { action });
      if (action === "received") {
        toast.success("Receipt confirmed — central stock updated (−1)");
        // Requisition just flipped to "approved" and central stock changed — tell any
        // mounted Dashboard/RequisitionList page to refetch so counts/status don't look stuck.
        requestDataRefresh();
      } else {
        toast.message("Marked as pending — you'll be reminded");
      }
      setConfirmOpen(false);
      setActive(null);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  const dismissInfo = async (n, e) => {
    e?.stopPropagation();
    try {
      await api.post(`/notifications/${n.id}/read`);
      setNotes((prev) => prev.filter((x) => x.id !== n.id));
      requestDataRefresh();
    } catch {
      /* silent */
    }
  };

  const onNoteClick = (n) => {
    if (n.type === "asset_receipt") {
      setActive(n);
      setConfirmOpen(true);
      setListOpen(false);
    }
  };

  const unreadCount = notes.length;

  return (
    <>
      <Popover open={listOpen} onOpenChange={setListOpen}>
        <PopoverTrigger asChild>
          <button
            className="relative text-slate-500 hover:text-slate-800 transition-colors"
            data-testid="notifications-btn"
          >
            <Bell size={28} />
            {unreadCount > 0 && (
              <span
                className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1 bg-red-500 text-white text-[10px] font-semibold rounded-full flex items-center justify-center"
                data-testid="notif-count"
              >
                {unreadCount}
              </span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 p-0" data-testid="notification-list">
          <div className="px-3 py-2 border-b border-slate-100">
            <h3 className="text-sm font-semibold text-slate-800">Notifications</h3>
          </div>
          {notes.length === 0 ? (
            <div className="px-3 py-6 text-center text-sm text-slate-500">
              No new notifications
            </div>
          ) : (
            <ul className="max-h-72 overflow-y-auto divide-y divide-slate-100">
              {notes.map((n) => (
                <li
                  key={n.id}
                  className={`px-3 py-2.5 text-sm hover:bg-slate-50 transition-colors ${
                    n.type === "asset_receipt" ? "cursor-pointer" : ""
                  }`}
                  onClick={() => onNoteClick(n)}
                  data-testid={`notif-item-${n.id}`}
                >
                  <div className="flex gap-2.5 items-start">
                    <div className="mt-0.5 shrink-0">
                      {n.type === "asset_receipt" ? (
                        <CheckCircle2 size={16} className="text-emerald-600" />
                      ) : (
                        <Package size={16} className="text-amber-600" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-slate-700 leading-snug">
                        {n.message ||
                          (n.type === "asset_receipt"
                            ? `Please confirm receipt of ${n.asset_name || "item"}`
                            : "You have a new notification")}
                      </p>
                      {n.type === "asset_receipt" && n.slip_no && (
                        <p className="text-xs text-slate-400 mt-0.5 font-mono">Slip {n.slip_no}</p>
                      )}
                      {n.created_at && (
                        <p className="text-[11px] text-slate-400 mt-1">
                          {new Date(n.created_at).toLocaleString()}
                        </p>
                      )}
                    </div>
                    {n.type !== "asset_receipt" && (
                      <button
                        onClick={(e) => dismissInfo(n, e)}
                        className="shrink-0 p-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100"
                        title="Dismiss"
                        data-testid={`notif-dismiss-${n.id}`}
                      >
                        <X size={14} />
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </PopoverContent>
      </Popover>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent data-testid="receipt-modal">
          <DialogHeader>
            <DialogTitle>Confirm Asset Receipt</DialogTitle>
          </DialogHeader>
          {active && (
            <div className="space-y-4">
              <p className="text-sm text-slate-600">
                An asset has been handed over to you via slip{" "}
                <span className="font-mono font-semibold">{active.slip_no}</span>. Please confirm
                you have physically received it.
              </p>
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-4">
                <div className="font-semibold text-slate-800" data-testid="receipt-asset-name">
                  {active.asset_name}
                </div>
                {active.asset_tag && (
                  <div className="font-mono text-xs text-amber-700 mt-1">{active.asset_tag}</div>
                )}
              </div>
              <div className="flex flex-col sm:flex-row gap-3">
                <button
                  onClick={() => act("received")}
                  data-testid="receipt-yes"
                  className="flex-1 py-2.5 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700 transition-colors flex items-center justify-center gap-2"
                >
                  <CheckCircle2 size={16} /> Yes, Received!
                </button>
                <button
                  onClick={() => act("pending")}
                  data-testid="receipt-no"
                  className="flex-1 py-2.5 rounded-lg border border-slate-300 text-slate-600 font-semibold hover:bg-slate-50 transition-colors flex items-center justify-center gap-2"
                >
                  <Clock size={16} /> No, Pending
                </button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}