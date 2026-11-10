import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { ArrowLeft, FileSpreadsheet, FileText, Loader2, Lock, Printer } from "lucide-react";
import api from "@/lib/apiClient";
import ReportTable from "./ReportTable";
import { downloadExport, errorMessage, fmtDateTime, printReport } from "./reportUtils";

const btn = "h-9 px-3 rounded-md border border-slate-300 bg-white text-sm text-slate-700 hover:bg-slate-50 inline-flex items-center gap-2 disabled:opacity-50";

/** One saved report. Users see the latest data; Print / PDF / Excel appear only when the Super Admin
 *  granted them (the server enforces the same permissions). Everything shown comes from the server, already limited to what the
 *  viewer is allowed to see. */
export default function ReportViewer({ reportId, isAdmin = false, onBack }) {
  const [detail, setDetail] = useState(null);
  const [previewAs, setPreviewAs] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState({ by: null, dir: "asc" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [busy, setBusy] = useState("");

  const perms = isAdmin ? ["read", "print", "export"] : (detail?.permissions || ["read"]);
  const canPrint = perms.includes("print");
  const canExport = perms.includes("export");
  const needsPreview = isAdmin && detail && ["own_assets", "own_employee_records", "own_performed", "own_department"].includes(detail.scope?.type);
  const assignees = (detail?.grants || []).filter((g) => g.status === "active");

  useEffect(() => {
    let live = true;
    setDetail(null); setResult(null); setError(""); setLoading(true);
    api.get(`/reports/saved/${reportId}`)
      .then(({ data }) => { if (live) setDetail(data); })
      .catch(async (e) => { if (live) { setError(await errorMessage(e, "This report is not available.")); setLoading(false); } });
    return () => { live = false; };
  }, [reportId]);

  const run = useCallback(async (over = {}) => {
    if (!detail) return;
    if (needsPreview && !previewAs) { setResult(null); setLoading(false); return; }
    setLoading(true); setError("");
    const s = over.sort || sort;
    try {
      const { data } = await api.post(`/reports/saved/${reportId}/run`, {
        sort_by: s.by, sort_dir: s.dir, page: over.page || page, page_size: over.pageSize || pageSize, as_user_id: previewAs || null,
      });
      setResult(data);
    } catch (e) {
      setResult(null);
      setError(await errorMessage(e, "The report could not be loaded."));
    } finally { setLoading(false); }
  }, [detail, needsPreview, previewAs, reportId, sort, page, pageSize]);

  useEffect(() => { if (detail) run(); /* eslint-disable-next-line */ }, [detail, previewAs]);

  const onSort = (key) => {
    const next = sort.by === key ? { by: key, dir: sort.dir === "asc" ? "desc" : "asc" } : { by: key, dir: "asc" };
    setSort(next); setPage(1); run({ sort: next, page: 1 });
  };
  const onPage = (p) => { setPage(p); run({ page: p }); };
  const onPageSize = (n) => { setPageSize(n); setPage(1); run({ pageSize: n, page: 1 }); };

  const doPrint = async () => {
    setBusy("print");
    try {
      const { data } = await api.post(`/reports/saved/${reportId}/run`, { purpose: "print", sort_by: sort.by, sort_dir: sort.dir, as_user_id: previewAs || null });
      if (!printReport({ title: detail.name, scopeLabel: detail.scope_label, result: data })) toast.error("Allow pop-ups to print the report.");
    } catch (e) { toast.error(await errorMessage(e, "Could not prepare the print view.")); }
    setBusy("");
  };
  const doExport = async (format) => {
    setBusy(format);
    try { await downloadExport(`/reports/saved/${reportId}/export`, { format, sort_by: sort.by, sort_dir: sort.dir, as_user_id: previewAs || null }); }
    catch (e) { toast.error(await errorMessage(e, "Export failed.")); }
    setBusy("");
  };

  if (error && !detail) {
    return (
      <div className="space-y-4">
        <button className={btn} onClick={onBack}><ArrowLeft size={15} /> Back</button>
        <div className="rounded-lg border border-slate-200 bg-white p-10 text-center text-sm text-slate-600" data-testid="viewer-unavailable">
          <Lock className="mx-auto mb-2 text-slate-400" size={22} />{error}
        </div>
      </div>
    );
  }
  if (!detail) return <div className="flex items-center gap-2 text-sm text-slate-500 p-6"><Loader2 size={16} className="animate-spin" /> Loading…</div>;

  return (
    <div className="space-y-5" data-testid="report-viewer">
      <div className="min-w-0">
        <button className="text-sm text-slate-500 hover:text-slate-800 inline-flex items-center gap-1 mb-1" onClick={onBack}><ArrowLeft size={14} /> Back</button>
        <h2 className="font-head text-2xl font-bold text-slate-900 truncate">{detail.name}</h2>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">
          <span className="font-medium text-slate-700">{detail.type_label}</span>
          <span>Data scope: {detail.scope_label}</span>
        </div>
        {detail.description && <p className="text-sm text-slate-500 mt-1">{detail.description}</p>}
        {(detail.filter_summary || []).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {detail.filter_summary.map((f) => (
              <span key={f.label} className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-xs text-slate-600">
                {f.label}: <b className="font-medium">{f.value}</b>
              </span>
            ))}
          </div>
        )}
      </div>

      {needsPreview && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 flex flex-wrap items-center gap-3">
          This report shows each assignee only their own data. Preview as:
          <select value={previewAs} onChange={(e) => { setPreviewAs(e.target.value); setPage(1); }} className="h-8 rounded-md border border-amber-300 bg-white px-2 text-sm" data-testid="preview-as">
            <option value="">Choose an assigned user…</option>
            {assignees.map((g) => <option key={g.user_id} value={g.user_id}>{g.user_name}</option>)}
          </select>
          {assignees.length === 0 && <span>No one is assigned yet.</span>}
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <div className="font-semibold text-slate-900">Results</div>
            <div className="text-xs text-slate-500">
              {result ? `${result.total} record${result.total === 1 ? "" : "s"} · live data as of ${fmtDateTime(result.generated_at)}` : "Live data"}
            </div>
          </div>
          {(canPrint || canExport) && (
            <div className="flex flex-wrap gap-2 no-print" data-testid="report-actions">
              {canPrint && <button className={btn} disabled={!result || !!busy} onClick={doPrint} data-testid="btn-print">{busy === "print" ? <Loader2 size={15} className="animate-spin" /> : <Printer size={15} />} Print</button>}
              {canExport && <button className={btn} disabled={!result || !!busy} onClick={() => doExport("pdf")} data-testid="btn-pdf">{busy === "pdf" ? <Loader2 size={15} className="animate-spin" /> : <FileText size={15} />} Export PDF</button>}
              {canExport && <button className={btn} disabled={!result || !!busy} onClick={() => doExport("xlsx")} data-testid="btn-xlsx">{busy === "xlsx" ? <Loader2 size={15} className="animate-spin" /> : <FileSpreadsheet size={15} />} Export Excel</button>}
            </div>
          )}
        </div>
        {(result?.warnings || []).map((w) => <div key={w} className="mx-4 mb-2 rounded bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">{w}</div>)}
        <ReportTable
          columns={result?.columns || []} rows={result?.rows || []} total={result?.total || 0}
          page={result?.page || page} pageSize={result?.page_size || pageSize} sortBy={result?.sort_by} sortDir={result?.sort_dir}
          loading={loading} error={error} onSort={onSort} onPage={onPage} onPageSize={onPageSize}
          emptyTitle={needsPreview && !previewAs ? "Choose a user to preview" : "No records match this report"}
          emptyHint={needsPreview && !previewAs ? "" : "The report runs on current data, so records appear here as soon as they match."}
        />
      </div>
    </div>
  );
}