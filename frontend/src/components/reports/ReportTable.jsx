import { AlertCircle, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Inbox, Loader2 } from "lucide-react";
import { TONE_CLS, cellText } from "./reportUtils";

const PAGE_SIZES = [10, 25, 50, 100];

function Cell({ col, row }) {
  const text = cellText(col, row);
  if (!text) return <span className="text-slate-300">—</span>;
  if (col.type === "status") {
    const tone = row[`${col.key}_tone`] || "neutral";
    return (
      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap ${TONE_CLS[tone] || TONE_CLS.neutral}`}>
        {text}
      </span>
    );
  }
  return <span>{text}</span>;
}

/** Enterprise data table: sortable headers, row dividers, status chips, pagination, and
 *  explicit loading / empty / error states. Rendering only - all data comes from the server. */
export default function ReportTable({
  columns = [], rows = [], total = 0, page = 1, pageSize = 25, sortBy, sortDir = "asc",
  loading = false, error = "", emptyTitle = "No records found", emptyHint = "", onSort, onPage, onPageSize,
}) {
  const pages = Math.max(Math.ceil(total / pageSize), 1);
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <div data-testid="report-table">
      <div className="relative overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-y border-slate-200">
              {columns.map((c) => {
                const active = sortBy === c.key;
                const right = c.type === "number" || c.type === "money";
                return (
                  <th key={c.key} className={`px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-500 whitespace-nowrap ${right ? "text-right" : "text-left"}`}>
                    <button type="button" onClick={() => onSort && onSort(c.key)} className={`inline-flex items-center gap-1 hover:text-slate-800 ${active ? "text-blue-700" : ""}`}>
                      {c.label}
                      {active ? (sortDir === "asc" ? <ChevronUp size={13} /> : <ChevronDown size={13} />) : <ChevronDown size={13} className="opacity-0" />}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className={loading ? "opacity-50" : ""}>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-100 hover:bg-blue-50/40 transition-colors">
                {columns.map((c) => (
                  <td key={c.key} className={`px-3 py-2.5 text-slate-700 align-top ${c.type === "number" || c.type === "money" ? "text-right tabular-nums" : ""}`}>
                    <Cell col={c} row={r} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>

        {loading && rows.length === 0 && (
          <div className="flex items-center justify-center gap-2 py-16 text-slate-500 text-sm" data-testid="report-loading">
            <Loader2 size={18} className="animate-spin" /> Loading report…
          </div>
        )}
        {!loading && error && (
          <div className="flex flex-col items-center gap-2 py-14 text-center" data-testid="report-error">
            <AlertCircle size={22} className="text-red-500" />
            <div className="text-sm font-medium text-slate-800">The report could not be loaded</div>
            <div className="text-sm text-slate-500 max-w-md">{error}</div>
          </div>
        )}
        {!loading && !error && rows.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-14 text-center" data-testid="report-empty">
            <Inbox size={22} className="text-slate-400" />
            <div className="text-sm font-medium text-slate-800">{emptyTitle}</div>
            {emptyHint && <div className="text-sm text-slate-500 max-w-md">{emptyHint}</div>}
          </div>
        )}
      </div>

      {!error && total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-3 border-t border-slate-200 text-sm text-slate-600">
          <div>Showing <b>{from}</b>–<b>{to}</b> of <b>{total}</b></div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-500">
              Rows
              <select value={pageSize} onChange={(e) => onPageSize && onPageSize(Number(e.target.value))}
                className="h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-700">
                {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <div className="flex items-center gap-1">
              <button type="button" disabled={page <= 1} onClick={() => onPage && onPage(page - 1)} aria-label="Previous page"
                className="h-8 w-8 grid place-items-center rounded-md border border-slate-300 hover:bg-slate-50 disabled:opacity-40"><ChevronLeft size={16} /></button>
              <span className="px-2 text-xs text-slate-500">Page {page} of {pages}</span>
              <button type="button" disabled={page >= pages} onClick={() => onPage && onPage(page + 1)} aria-label="Next page"
                className="h-8 w-8 grid place-items-center rounded-md border border-slate-300 hover:bg-slate-50 disabled:opacity-40"><ChevronRight size={16} /></button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
