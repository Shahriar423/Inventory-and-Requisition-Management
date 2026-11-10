import { useEffect, useState } from "react";
import { CalendarOff, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const inp = "w-full h-10 px-3 rounded-lg border border-slate-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-amber-500";

function Label({ children, hint }) {
  return (
    <div className="mb-1">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{children}</div>
      {hint && <div className="text-xs text-slate-400 mt-0.5">{hint}</div>}
    </div>
  );
}

/** Header button + dialog: choose who approves on your behalf while you are on leave. */
export default function DelegationDialog() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [users, setUsers] = useState([]);
  const [state, setState] = useState(null);
  const [delegateId, setDelegateId] = useState("");
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [saving, setSaving] = useState(false);
  const [doneMsg, setDoneMsg] = useState("");   // non-empty => show the "Done!" popup

  const load = async () => {
    try {
      const [d, u] = await Promise.all([api.get("/me/delegation"), api.get("/users/lookup")]);
      setState(d.data);
      setUsers(u.data.filter((x) => x.id !== user?.id));
      setDelegateId(d.data.delegate_user_id || "");
      setFrom(d.data.delegate_from || "");
      setUntil(d.data.delegate_until || "");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  useEffect(() => { if (open) load(); }, [open]); // eslint-disable-line

  // The "Done!" popup dismisses itself after a couple of seconds.
  useEffect(() => {
    if (!doneMsg) return undefined;
    const t = setTimeout(() => setDoneMsg(""), 2200);
    return () => clearTimeout(t);
  }, [doneMsg]);

  // Executives never approve anything, so they don't need this.
  if (!user || user.role === "executive") return null;

  const save = async (clear = false) => {
    if (!clear && delegateId && (!from || !until)) return toast.error("Choose the leave start and end dates");
    setSaving(true);
    try {
      const { data } = await api.put("/me/delegation", {
        delegate_user_id: clear ? null : (delegateId || null),
        delegate_from: clear ? null : (from || null),
        delegate_until: clear ? null : (until || null),
      });
      setState(data);
      if (clear) { setDelegateId(""); setFrom(""); setUntil(""); }
      setOpen(false);                                   // close the form
      setDoneMsg(clear ? "Delegation removed successfully." : "Your delegation has been saved successfully.");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const opt = (u) => <option key={u.id} value={u.id}>{u.name}{u.department_name ? ` — ${u.department_name}` : ""}</option>;

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} data-testid="delegation-btn"
        title="Leave / Delegate approvals"
        className={`relative text-slate-500 hover:text-slate-800 transition-colors ${state?.active ? "text-amber-600" : ""}`}>
        <CalendarOff size={24} />
        {state?.active && <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-amber-500" />}
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg" data-testid="delegation-modal">
          <DialogHeader><DialogTitle>Leave &amp; approval delegation</DialogTitle></DialogHeader>

          {state?.active && (
            <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-800">
              {state.delegate_name} is approving on your behalf until {state.delegate_until}.
            </div>
          )}

          <div className="space-y-4">
            <div>
              <Label hint="While you are on leave, this person can see and approve everything addressed to you.">Delegate (while on leave)</Label>
              <select className={inp} value={delegateId} onChange={(e) => setDelegateId(e.target.value)} data-testid="delegate-select">
                <option value="">— none —</option>
                {users.map(opt)}
              </select>
            </div>

            {delegateId && (
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Leave from</Label><input type="date" className={inp} value={from} onChange={(e) => setFrom(e.target.value)} data-testid="delegate-from" /></div>
                <div><Label>Leave until</Label><input type="date" className={inp} value={until} min={from || undefined} onChange={(e) => setUntil(e.target.value)} data-testid="delegate-until" /></div>
              </div>
            )}

          </div>

          <div className="flex justify-between pt-2">
            <button type="button" onClick={() => save(true)} disabled={saving || !state?.delegate_user_id}
              className="px-4 py-2 rounded-lg border border-slate-300 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-40">
              Remove delegation
            </button>
            <button type="button" onClick={() => save(false)} disabled={saving} data-testid="delegation-save"
              className="px-5 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-semibold disabled:opacity-60">
              Save
            </button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Success popup */}
      <Dialog open={!!doneMsg} onOpenChange={(v) => { if (!v) setDoneMsg(""); }}>
        <DialogContent className="max-w-sm text-center" data-testid="delegation-done-modal">
          <div className="flex flex-col items-center gap-3 py-4">
            <div className="w-16 h-16 rounded-full bg-emerald-50 flex items-center justify-center">
              <CheckCircle2 size={40} className="text-emerald-600" />
            </div>
            <DialogTitle className="text-xl font-bold text-slate-900">Done!</DialogTitle>
            <p className="text-sm text-slate-500">{doneMsg}</p>
            <button type="button" onClick={() => setDoneMsg("")} data-testid="delegation-done-ok"
              className="mt-2 px-6 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-semibold">
              OK
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
