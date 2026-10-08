import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Inbox, Wrench, Hand, Loader2 } from "lucide-react";
import api from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { StatusBadge } from "@/lib/status";

/**
 * Dashboard card: incoming IT service orders for the IT department.
 * Shown only to people who can open the IT Service Queue (IT Head, Super Admin and IT executives
 * with an IT team) - the server lists that permission as the "it-service-queue" menu key, and the
 * data itself comes from the same team-filtered endpoint the queue page uses, so an Application
 * executive only ever sees Application orders and a Network & Infra executive only theirs.
 */
const PRIORITY_CLS = { low: "bg-slate-100 text-slate-600", medium: "bg-sky-100 text-sky-700", high: "bg-amber-100 text-amber-700", critical: "bg-red-100 text-red-700" };
const TEAM_CLS = { Application: "bg-violet-100 text-violet-700", Network_Infra: "bg-teal-100 text-teal-700" };

const ago = (iso) => {
  if (!iso) return "";
  const m = Math.max(Math.floor((Date.now() - new Date(iso).getTime()) / 60000), 0);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
};

function Tile({ label, value, tone, icon: Icon, testid }) {
  return (
    <Link to="/it-service/queue" data-testid={testid}
      className="block bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:border-amber-300 hover:-translate-y-0.5 transition-all duration-200">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-3 ${tone}`}>
        <Icon size={20} />
      </div>
      <div className="text-2xl font-head font-bold text-slate-900">{value}</div>
      <div className="text-xs uppercase tracking-wider text-slate-500 mt-1">{label}</div>
    </Link>
  );
}

/** Fetches the IT queue once; Dashboard calls this and hands the result to the tiles and the card. */
export function useITServiceQueue() {
  const { allowed } = useAuth();
  const enabled = (allowed || []).includes("it-service-queue");
  const [data, setData] = useState(null);

  const load = useCallback(() => {
    api.get("/it-service/queue", { params: { view: "open", limit: 5, _t: Date.now() } })
      .then(({ data: d }) => setData(d)).catch(() => {});
  }, []);

  useEffect(() => { if (enabled) load(); }, [enabled, load]);
  // New orders are raised by other people while this page is open: refresh every 15s and on return to the tab.
  useEffect(() => {
    if (!enabled) return undefined;
    const when = () => { if (document.visibilityState === "visible") load(); };
    const t = setInterval(when, 15000);
    document.addEventListener("visibilitychange", when);
    window.addEventListener("focus", when);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", when); window.removeEventListener("focus", when); };
  }, [enabled, load]);

  return { enabled, data };
}

/** The four count tiles. Render inside the dashboard's stat-card grid so they sit beside the other cards. */
export function ITQueueTiles({ queue }) {
  if (!queue?.enabled) return null;
  const c = queue.data?.counts || {};
  const isHead = (queue.data?.allowed_teams || []).length > 1;   // only IT Head / Super Admin see both queues
  return (
    <>
      <Tile label="New orders" value={c.open ?? 0} tone="bg-red-100 text-red-700" icon={Inbox} testid="it-queue-open" />
      <Tile label="In progress" value={c.active ?? 0} tone="bg-indigo-100 text-indigo-700" icon={Loader2} testid="it-queue-active" />
      <Tile label={isHead && c.repair_approvals > 0 ? `Repairs (${c.repair_approvals} to approve)` : "At repair"} value={c.repair ?? 0} tone="bg-purple-100 text-purple-700" icon={Wrench} testid="it-queue-repair" />
      <Tile label="Mine" value={c.mine ?? 0} tone="bg-emerald-100 text-emerald-700" icon={Hand} testid="it-queue-mine" />
    </>
  );
}

export default function ITServiceQueueCard({ queue }) {
  const enabled = !!queue?.enabled;
  const data = queue?.data;

  if (!enabled) return null;
  if (!data) {
    return <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 text-slate-400 text-sm flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading IT service queue…</div>;
  }

  const c = data.counts || {};
  const multi = (data.allowed_teams || []).length > 1;
  const teamLabel = (k) => (data.allowed_teams || []).find((t) => t.key === k)?.label || k;
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm" data-testid="it-queue-card">
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4 border-b border-slate-100">
        <div className="flex items-center gap-2.5">
          <span className="relative flex w-9 h-9 rounded-lg bg-amber-100 text-amber-700 items-center justify-center">
            <Inbox size={18} />
            {c.open > 0 && <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-red-500 border-2 border-white animate-pulse" data-testid="it-queue-new-dot" />}
          </span>
          <div>
            <h3 className="font-head font-semibold text-slate-900">IT Service Queue</h3>
            <p className="text-xs text-slate-500">{multi ? "Application + Network & Infra" : data.allowed_teams?.[0]?.label} · new orders appear here</p>
          </div>
        </div>
        <Link to="/it-service/queue" className="text-sm font-semibold text-amber-700 hover:underline" data-testid="it-queue-open-link">Open queue →</Link>
      </div>

      <div className="px-5 py-4">
        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Latest waiting orders</div>
        {data.tickets.length === 0 ? (
          <div className="text-sm text-slate-400 py-3" data-testid="it-queue-empty">No orders waiting - the queue is clear.</div>
        ) : (
          <ul className="divide-y divide-slate-100 border border-slate-200 rounded-lg">
            {data.tickets.map((t) => (
              <li key={t.id}>
                <Link to="/it-service/queue" data-testid={`it-queue-row-${t.requisition_no}`}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm hover:bg-amber-50/50">
                  <span className="font-mono font-semibold text-slate-800">{t.requisition_no}</span>
                  <span className="text-slate-700 flex-1 min-w-[10rem]">{t.items?.[0]?.product_name}{t.items?.length > 1 ? ` +${t.items.length - 1}` : ""}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold capitalize ${PRIORITY_CLS[t.priority] || ""}`}>{t.priority}</span>
                  {multi && <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${TEAM_CLS[t.it_team] || ""}`}>{teamLabel(t.it_team)}</span>}
                  <span className="text-slate-500">{t.requisition_for || t.requisitioner_name}</span>
                  <span className="text-xs text-slate-400 w-16 text-right">{ago(t.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {c.open > data.tickets.length && <p className="text-xs text-slate-400 mt-2">+ {c.open - data.tickets.length} more waiting in the queue.</p>}
      </div>
    </div>
  );
}
