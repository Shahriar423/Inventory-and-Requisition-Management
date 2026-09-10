import { useEffect, useRef, useState, useCallback } from "react";
import { Bell, CheckCircle2, Clock } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export default function NotificationBell() {
  const [notes, setNotes] = useState([]);
  const [active, setActive] = useState(null);
  const [open, setOpen] = useState(false);
  const seen = useRef(new Set());

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/notifications");
      setNotes(data);
      const receipt = data.find((n) => n.type === "asset_receipt" && n.status === "unread");
      if (receipt && !seen.current.has(receipt.id)) {
        seen.current.add(receipt.id);
        setActive(receipt);
        setOpen(true);
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
      if (action === "received") toast.success("Receipt confirmed — central stock updated (−1)");
      else toast.message("Marked as pending — you'll be reminded");
      setOpen(false);
      setActive(null);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  const openList = () => {
    const receipt = notes.find((n) => n.type === "asset_receipt");
    if (receipt) {
      setActive(receipt);
      setOpen(true);
    } else {
      toast.message("No new notifications");
    }
  };

  return (
    <>
      <button onClick={openList} className="relative text-slate-500 hover:text-slate-800 transition-colors" data-testid="notifications-btn">
        <Bell size={20} />
        {notes.length > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1 bg-red-500 text-white text-[10px] font-semibold rounded-full flex items-center justify-center" data-testid="notif-count">
            {notes.length}
          </span>
        )}
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="receipt-modal">
          <DialogHeader><DialogTitle>Confirm Asset Receipt</DialogTitle></DialogHeader>
          {active && (
            <div className="space-y-4">
              <p className="text-sm text-slate-600">
                An asset has been handed over to you via slip <span className="font-mono font-semibold">{active.slip_no}</span>. Please confirm you have physically received it.
              </p>
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-4">
                <div className="font-semibold text-slate-800" data-testid="receipt-asset-name">{active.asset_name}</div>
                {active.asset_tag && <div className="font-mono text-xs text-amber-700 mt-1">{active.asset_tag}</div>}
              </div>
              <div className="flex flex-col sm:flex-row gap-3">
                <button onClick={() => act("received")} data-testid="receipt-yes" className="flex-1 py-2.5 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700 transition-colors flex items-center justify-center gap-2">
                  <CheckCircle2 size={16} /> Yes, Received &amp; Signed
                </button>
                <button onClick={() => act("pending")} data-testid="receipt-no" className="flex-1 py-2.5 rounded-lg border border-slate-300 text-slate-600 font-semibold hover:bg-slate-50 transition-colors flex items-center justify-center gap-2">
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
