import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Search, FileText, Printer, User, Building2, Clock, Hash } from "lucide-react";
import api, { API, withAuthParam, formatApiErrorDetail } from "@/lib/apiClient";
import { StatusBadge } from "@/lib/status";

/**
 * Audit Search - type any Requisition No. (REQ-2026-0433, or a filed PR number) to get a summary card
 * and the Master Audit PDF. The PDF is rendered by the server in memory every time it is opened;
 * nothing is stored. The button opens it in a new tab so it can be printed (Ctrl+P) or downloaded.
 */
const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

export default function AuditSearch() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") || "");
  const [loading, setLoading] = useState(false);
  const [card, setCard] = useState(null);
  const [error, setError] = useState("");

  const search = useCallback(async (value) => {
    const ref = (value ?? q).trim();
    if (!ref) { setError("Enter a requisition number"); setCard(null); return; }
    setLoading(true); setError(""); setCard(null);
    try {
      const { data } = await api.get(`/audit/requisitions/${encodeURIComponent(ref)}`);
      setCard(data);
      setParams({ q: ref }, { replace: true });
    } catch (e) {
      setError(formatApiErrorDetail(e.response?.data?.detail) || "Could not load the requisition");
    } finally { setLoading(false); }
  }, [q, setParams]);

  // Deep link: /audit/search?q=REQ-2026-0433 searches straight away.
  useEffect(() => { if (params.get("q")) search(params.get("q")); /* eslint-disable-next-line */ }, []);

  // The new tab cannot send the Authorization header, so (like the other PDF links) the tab's
  // token travels as ?auth=. The PDF endpoint re-checks access for this exact requisition.
  const openPdf = () => {
    const url = withAuthParam(`${API}/requisitions/${encodeURIComponent(card.requisition_no)}/audit-pdf`);
    const w = window.open(url, "_blank");
    if (!w) toast.error("The browser blocked the new tab - allow pop-ups for this site and click again.");
  };

  return (
    <div className="max-w-3xl mx-auto space-y-5" data-testid="audit-search-page">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">Audit Search</h2>
        <p className="text-slate-500 text-sm mt-0.5">Find any Product (PR) or Service (SR) requisition and open its full lifecycle report.</p>
      </div>

      <form onSubmit={(e) => { e.preventDefault(); search(); }} className="flex gap-2" data-testid="audit-form">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Requisition No., e.g. REQ-2026-0433" autoFocus
            data-testid="audit-input"
            className="w-full h-11 pl-9 pr-3 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm" />
        </div>
        <button type="submit" disabled={loading} data-testid="audit-search-btn"
          className="px-5 h-11 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm disabled:opacity-50">
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" data-testid="audit-error">{error}</div>}

      {card && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4" data-testid="audit-card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xl font-bold text-slate-900" data-testid="audit-req-no">{card.requisition_no}</span>
                <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${card.request_type === "SR" ? "bg-teal-100 text-teal-700" : "bg-indigo-100 text-indigo-700"}`}>
                  {card.request_type === "SR" ? "Service Requisition" : "Product Requisition"}
                </span>
              </div>
              <div className="mt-1.5"><StatusBadge status={card.status} /></div>
            </div>
            <button onClick={openPdf} data-testid="audit-view-pdf"
              className="px-4 py-2.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-sm font-semibold flex items-center gap-2">
              <FileText size={16} /> View Master PDF / Print <Printer size={14} className="opacity-70" />
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm text-slate-600">
            <div className="flex items-center gap-2"><User size={14} className="text-slate-400" /> {card.requisitioner_name}{card.requisition_for && card.requisition_for !== card.requisitioner_name ? ` (for ${card.requisition_for})` : ""}</div>
            <div className="flex items-center gap-2"><Building2 size={14} className="text-slate-400" /> {card.department_name || "—"}</div>
            <div className="flex items-center gap-2"><Clock size={14} className="text-slate-400" /> Created {fmt(card.created_at)}</div>
            <div className="flex items-center gap-2"><Clock size={14} className="text-slate-400" /> Last activity {fmt(card.last_event_at)}</div>
            {card.it_team && <div className="flex items-center gap-2"><Hash size={14} className="text-slate-400" /> {card.it_team}{card.handled_by ? ` · ${card.handled_by}` : ""}</div>}
            {card.po_numbers?.length > 0 && <div className="flex items-center gap-2"><Hash size={14} className="text-slate-400" /> PO: {card.po_numbers.join(", ")}</div>}
            {card.slip_numbers?.length > 0 && <div className="flex items-center gap-2"><Hash size={14} className="text-slate-400" /> Slip: {card.slip_numbers.join(", ")}</div>}
          </div>

          <div className="border-t border-slate-100 pt-3 text-sm">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">{card.request_type === "SR" ? "Service" : "Items"}</div>
            <ul className="text-slate-700 space-y-0.5">
              {card.items.map((it, i) => <li key={i}>{it.name}{card.request_type === "PR" && it.quantity ? ` × ${it.quantity}` : ""}</li>)}
            </ul>
            <p className="text-xs text-slate-400 mt-2">{card.event_count} recorded lifecycle event{card.event_count === 1 ? "" : "s"}. The PDF is generated fresh from the database when you open it.</p>
          </div>
        </div>
      )}
    </div>
  );
}
