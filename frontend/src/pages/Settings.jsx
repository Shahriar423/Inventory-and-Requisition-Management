import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Banknote, BellRing, Loader2 } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";

const card = "bg-white rounded-xl border border-slate-200 shadow-sm p-5";
const inp = "h-11 w-full px-3 rounded-lg border border-slate-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-amber-500";
const fmt = (n) => Number(n || 0).toLocaleString("en-US");

/** Super Admin only: business limits that used to need a code change / raw API call. */
export default function Settings() {
  const [loading, setLoading] = useState(true);
  const [md, setMd] = useState({ saved: 0, value: "" });
  const [rem, setRem] = useState({ saved: 0, value: "" });
  const [busy, setBusy] = useState("");

  useEffect(() => {
    Promise.all([api.get("/settings/po-threshold"), api.get("/settings/reminder")])
      .then(([a, b]) => {
        setMd({ saved: a.data.amount, value: String(a.data.amount) });
        setRem({ saved: b.data.reminder_hours, value: String(b.data.reminder_hours) });
      })
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not load settings"))
      .finally(() => setLoading(false));
  }, []);

  const saveMd = async () => {
    const amount = Number(md.value);
    if (md.value.trim() === "" || !Number.isFinite(amount) || amount < 0) return toast.error("Enter an amount of 0 or more");
    setBusy("md");
    try {
      const { data } = await api.put("/settings/po-threshold", { amount });
      setMd({ saved: data.amount, value: String(data.amount) });
      toast.success(`MD approval limit is now BDT ${fmt(data.amount)}`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not save");
    } finally { setBusy(""); }
  };

  const saveRem = async () => {
    const hours = Number(rem.value);
    if (rem.value.trim() === "" || !Number.isFinite(hours) || hours <= 0) return toast.error("Enter a number of hours above 0");
    setBusy("rem");
    try {
      const { data } = await api.put("/settings/reminder", { reminder_hours: hours });
      setRem({ saved: data.reminder_hours, value: String(data.reminder_hours) });
      toast.success(`Approval reminder is now ${data.reminder_hours} hour(s)`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not save");
    } finally { setBusy(""); }
  };

  if (loading) return <div className="py-16 text-center text-slate-400" data-testid="settings-loading">Loading settings…</div>;

  const mdDirty = String(md.saved) !== md.value.trim();
  const remDirty = String(rem.saved) !== rem.value.trim();
  const limit = Number(md.value) >= 0 && md.value.trim() !== "" ? Number(md.value) : md.saved;

  return (
    <div className="space-y-6 max-w-3xl" data-testid="settings-page">
      <div>
        <h2 className="font-head text-xl font-semibold text-slate-900">Settings</h2>
        <p className="text-sm text-slate-500">Business limits. Changes apply immediately, no code change needed.</p>
      </div>

      <section className={card} data-testid="md-limit-card">
        <div className="flex items-center gap-2 mb-1">
          <Banknote size={18} className="text-amber-600" />
          <h3 className="font-head font-semibold text-slate-900">MD approval limit for Purchase Orders</h3>
        </div>
        <p className="text-sm text-slate-500 mb-4">
          A Purchase Order whose total is <b>above</b> this amount also needs the Managing Director's approval.
        </p>
        <div className="grid sm:grid-cols-[1fr_auto] gap-3 items-end">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Limit (BDT)</label>
            <input type="number" min="0" step="any" value={md.value} onChange={(e) => setMd({ ...md, value: e.target.value })}
              data-testid="md-limit-input" className={inp} />
          </div>
          <button onClick={saveMd} disabled={!mdDirty || busy === "md"} data-testid="md-limit-save"
            className="h-11 px-5 rounded-lg bg-amber-600 text-white text-sm font-semibold hover:bg-amber-700 disabled:opacity-50 flex items-center justify-center gap-2">
            {busy === "md" && <Loader2 size={15} className="animate-spin" />} Save
          </button>
        </div>
        <div className="mt-4 rounded-lg bg-slate-50 border border-slate-200 px-3 py-2.5 text-sm text-slate-600 space-y-1">
          <div>Up to BDT {fmt(limit)}: Purchase Head, then Accounts Head.</div>
          <div>Above BDT {fmt(limit)}: Purchase Head, then MD, then Accounts Head.</div>
        </div>
        <p className="text-xs text-slate-400 mt-2">The rule is checked when each approver acts, so a PO already waiting for the Purchase Head follows the new limit. Set 0 to send every PO to the MD.</p>
      </section>

      <section className={card} data-testid="reminder-card">
        <div className="flex items-center gap-2 mb-1">
          <BellRing size={18} className="text-amber-600" />
          <h3 className="font-head font-semibold text-slate-900">Approval reminder</h3>
        </div>
        <p className="text-sm text-slate-500 mb-4">An approver is reminded when a request has waited this many hours for their decision.</p>
        <div className="grid sm:grid-cols-[1fr_auto] gap-3 items-end">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">Hours</label>
            <input type="number" min="0" step="any" value={rem.value} onChange={(e) => setRem({ ...rem, value: e.target.value })}
              data-testid="reminder-input" className={inp} />
          </div>
          <button onClick={saveRem} disabled={!remDirty || busy === "rem"} data-testid="reminder-save"
            className="h-11 px-5 rounded-lg bg-amber-600 text-white text-sm font-semibold hover:bg-amber-700 disabled:opacity-50 flex items-center justify-center gap-2">
            {busy === "rem" && <Loader2 size={15} className="animate-spin" />} Save
          </button>
        </div>
      </section>
    </div>
  );
}
