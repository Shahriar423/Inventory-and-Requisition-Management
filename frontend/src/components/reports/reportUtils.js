import api, { formatApiErrorDetail } from "@/lib/apiClient";

export const TONE_CLS = {
  ok: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  info: "bg-blue-50 text-blue-700 ring-blue-200",
  warn: "bg-amber-50 text-amber-700 ring-amber-200",
  danger: "bg-red-50 text-red-700 ring-red-200",
  neutral: "bg-slate-100 text-slate-600 ring-slate-200",
};

export function fmtDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function cellText(col, row) {
  const v = row[col.key];
  if (v === null || v === undefined || v === "") return "";
  if (col.type === "date") return fmtDateTime(v);
  if (col.type === "money") return Number(v).toLocaleString("en-BD", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return String(v);
}

/** Turn an axios error (including a blob error body from a file download) into a readable message. */
export async function errorMessage(e, fallback = "Something went wrong. Please try again.") {
  let data = e?.response?.data;
  if (data instanceof Blob) {
    try { data = JSON.parse(await data.text()); } catch { data = null; }
  }
  const detail = data?.detail;
  return (detail && formatApiErrorDetail(detail)) || fallback;
}

/** POST to an export endpoint and hand the file to the browser. */
export async function downloadExport(url, body) {
  const res = await api.post(url, body, { responseType: "blob" });
  const m = /filename="?([^";]+)"?/.exec(res.headers["content-disposition"] || "");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(res.data);
  a.download = m ? m[1] : `report.${body.format === "xlsx" ? "xlsx" : "pdf"}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Print exactly the rows the server returned (already filtered and authorised) in a clean window. */
export function printReport({ title, scopeLabel, result }) {
  const w = window.open("", "_blank", "width=1100,height=800");
  if (!w) return false;
  const head = result.columns.map((c) => `<th>${esc(c.label)}</th>`).join("");
  const body = result.rows
    .map((r) => `<tr>${result.columns.map((c) => `<td class="${c.type === "number" || c.type === "money" ? "num" : ""}">${esc(cellText(c, r)) || "-"}</td>`).join("")}</tr>`)
    .join("");
  const filters = (result.filters_applied || []).map((f) => `${esc(f.label)}: <b>${esc(f.value)}</b>`).join(" &nbsp;·&nbsp; ") || "None";
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title><style>
    @page{size:A4 landscape;margin:12mm}
    body{font-family:Arial,Helvetica,sans-serif;color:#0f172a;font-size:11px}
    h1{font-size:18px;margin:0 0 4px} .meta{color:#475569;margin:2px 0}
    table{width:100%;border-collapse:collapse;margin-top:12px}
    th{background:#1e3a5f;color:#fff;text-align:left;padding:5px 6px;font-size:10px}
    td{padding:4px 6px;border-bottom:1px solid #e2e8f0;vertical-align:top} td.num{text-align:right}
    tr:nth-child(even) td{background:#f8fafc} thead{display:table-header-group}
    .foot{margin-top:8px;color:#475569}
  </style></head><body>
    <h1>${esc(title)}</h1>
    <div class="meta">Generated: ${esc(fmtDateTime(result.generated_at))}${scopeLabel ? ` &nbsp;·&nbsp; Data scope: ${esc(scopeLabel)}` : ""}</div>
    <div class="meta">Filters: ${filters}</div>
    ${(result.warnings || []).map((x) => `<div class="meta">${esc(x)}</div>`).join("")}
    <table><thead><tr>${head}</tr></thead><tbody>${body || `<tr><td colspan="${result.columns.length}">No records match this report.</td></tr>`}</tbody></table>
    <div class="foot">${result.rows.length} record(s)</div>
    <script>window.onload=function(){window.focus();window.print();}<\/script>
  </body></html>`);
  w.document.close();
  return true;
}