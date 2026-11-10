import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import { toast } from "sonner";
import { FileSpreadsheet, FileText, KeyRound, Loader2, Pencil, Printer, Search, ShieldOff, Trash2, X, Eye, RotateCcw } from "lucide-react";
import api from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import ReportTable from "@/components/reports/ReportTable";
import ReportViewer from "@/components/reports/ReportViewer";
import FilterFields, { SearchPicker, inputCls } from "@/components/reports/FilterFields";
import MasterFilterPanel, { MASTER_KEYS, VIEW_OPTIONS } from "@/components/reports/MasterFilterPanel";
import PermBoxes from "@/components/reports/PermBoxes";
import { downloadExport, errorMessage, fmtDateTime, printReport } from "@/components/reports/reportUtils";

const btn = "h-9 px-3 rounded-md border border-slate-300 bg-white text-sm text-slate-700 hover:bg-slate-50 inline-flex items-center gap-2 disabled:opacity-50";
const btnPrimary = "h-9 px-4 rounded-md bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 inline-flex items-center gap-2 disabled:opacity-50";

const clean = (f) => Object.fromEntries(Object.entries(f || {}).filter(([, v]) => String(v ?? "").trim() !== ""));

function ScopePicker({ meta, type, scope, onChange }) {
  const allowed = meta.types.find((t) => t.key === type)?.scopes || ["all"];
  const toggleDept = (id) => {
    const cur = scope.department_ids || [];
    onChange({ ...scope, department_ids: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] });
  };
  return (
    <div className="space-y-2">
      <select value={scope.type} onChange={(e) => onChange({ type: e.target.value, department_ids: [] })} className={inputCls} data-testid="scope-type">
        {allowed.map((s) => <option key={s} value={s}>{meta.scope_labels[s]}</option>)}
      </select>
      {scope.type === "selected_departments" && (
        <div className="flex flex-wrap gap-1.5">
          {meta.departments.map((d) => (
            <button type="button" key={d.id} onClick={() => toggleDept(d.id)}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${(scope.department_ids || []).includes(d.id) ? "border-blue-500 bg-blue-50 text-blue-700" : "border-slate-300 text-slate-600"}`}>{d.name}</button>
          ))}
        </div>
      )}
      <p className="text-xs text-slate-500">
        {scope.type === "all" && "The user sees every record that matches the criteria. Use only for explicitly authorised users."}
        {["own_assets", "own_employee_records"].includes(scope.type) && "Each assignee sees only records linked to their own account, whatever criteria are saved."}
        {scope.type === "own_performed" && "Each assignee sees only the movements they performed themselves."}
        {scope.type === "own_department" && "Each assignee sees only their own department's records."}
        {scope.type === "selected_departments" && "Only records of the chosen departments are ever shown."}
      </p>
    </div>
  );
}

/* --------------------------- Save & Assign dialog --------------------------- */
function SaveDialog({ open, meta, type, filters, onClose, onSaved }) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [scope, setScope] = useState({ type: "all", department_ids: [] });
  const [users, setUsers] = useState([]);
  const [perms, setPerms] = useState(["read"]);
  const [pick, setPick] = useState("");
  const [saving, setSaving] = useState(false);
  const typeDef = meta.types.find((t) => t.key === type);
  const viewLabel = VIEW_OPTIONS.find(([k]) => k === type)?.[1] || typeDef.label;

  useEffect(() => { if (open) { setName(""); setDesc(""); setScope({ type: "all", department_ids: [] }); setUsers([]); setPerms(["read"]); setPick(""); } }, [open, type]);

  const empOptions = meta.employees.filter((e) => !users.includes(e.id)).map((e) => ({ value: e.id, label: e.name, sub: [e.code, e.department].filter(Boolean).join(" · ") }));
  const nameOf = (id) => meta.employees.find((e) => e.id === id)?.name || id;
  const personalTip = filters.employee_user_id && scope.type === "all";

  const save = async () => {
    if (!name.trim()) return toast.error("Give the report a name");
    setSaving(true);
    try {
      await api.post("/reports/saved", {
        name, description: desc || null, report_type: type, filters, scope,
        permissions: perms, grants: users.map((u) => ({ user_id: u })),
      });
      toast.success(users.length ? "Report saved and assigned" : "Report saved");
      onSaved(); onClose();
    } catch (e) { toast.error(await errorMessage(e)); }
    setSaving(false);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="save-report-dialog">
        <DialogHeader><DialogTitle>Save &amp; Assign Report</DialogTitle></DialogHeader>
        <p className="text-sm text-slate-500">
          This saves the <b>search criteria</b>, not the results. Whoever opens it always sees the latest inventory data they are allowed to see.
        </p>
        <div className="grid gap-4">
          <label className="block"><span className="block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Report Name *</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={`e.g. IT department - ${viewLabel}`} className={inputCls} data-testid="save-name" /></label>
          <label className="block"><span className="block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Short description</span>
            <input value={desc} onChange={(e) => setDesc(e.target.value)} className={inputCls} /></label>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Report View Type</div>
              <div className="h-9 flex items-center rounded-md border border-slate-200 bg-slate-50 px-3 text-sm text-slate-700" data-testid="save-view-type">{viewLabel}</div>
            </div>
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Data scope</div>
              <ScopePicker meta={meta} type={type} scope={scope} onChange={setScope} />
            </div>
          </div>

          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Applied Filters (JSON)</div>
            <pre className="max-h-40 overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700" data-testid="save-filters-json">
              {JSON.stringify({ report_view: type, filters }, null, 2)}
            </pre>
            {personalTip && typeDef.scopes.includes("own_assets") && (
              <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                Tip: this report is filtered on one employee. Choose <b>Own Assets Only</b> so the user is tied to their own account and can never see anyone else's records.
              </div>
            )}
          </div>

          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Assigned Users</div>
            <SearchPicker options={empOptions} value={pick} onChange={(v) => { if (v) { setUsers((u) => [...u, v]); setPick(""); } }} placeholder="Search and add a user…" testId="grant-user-picker" />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {users.map((u) => (
                <span key={u} className="inline-flex items-center gap-1 rounded-full bg-blue-50 border border-blue-200 text-blue-700 text-xs px-2.5 py-0.5">
                  {nameOf(u)}<button type="button" aria-label="Remove" onClick={() => setUsers((x) => x.filter((i) => i !== u))}><X size={12} /></button>
                </span>
              ))}
              {users.length === 0 && <span className="text-xs text-slate-500">No one yet — you can also assign users later from Saved Reports.</span>}
            </div>
          </div>

          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Permissions</div>
            <PermBoxes value={perms} onChange={setPerms} />
            <p className="mt-1.5 text-xs text-slate-500">Users can only ever see data inside the data scope above, whatever permissions they have.</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button className={btn} onClick={onClose}>Cancel</button>
          <button className={btnPrimary} onClick={save} disabled={saving} data-testid="save-report-submit">{saving && <Loader2 size={15} className="animate-spin" />} Save &amp; Assign</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* --------------------------- Access management dialog --------------------------- */
function AccessDialog({ report, meta, onClose, onChanged }) {
  const [grants, setGrants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pick, setPick] = useState("");
  const [newPerms, setNewPerms] = useState(["read"]);

  const load = useCallback(async () => {
    setLoading(true);
    try { const { data } = await api.get(`/reports/saved/${report.id}/access`); setGrants(data); }
    catch (e) { toast.error(await errorMessage(e)); }
    setLoading(false);
  }, [report.id]);
  useEffect(() => { load(); }, [load]);

  const call = async (fn) => { try { const { data } = await fn(); setGrants(data); onChanged(); } catch (e) { toast.error(await errorMessage(e)); } };
  const add = async () => { if (!pick) return; await call(() => api.post(`/reports/saved/${report.id}/access`, { user_ids: [pick], permissions: newPerms })); setPick(""); };
  const taken = new Set(grants.filter((g) => g.status === "active").map((g) => g.user_id));
  const options = meta.employees.filter((e) => !taken.has(e.id)).map((e) => ({ value: e.id, label: e.name, sub: [e.code, e.department].filter(Boolean).join(" · ") }));

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="access-dialog">
        <DialogHeader><DialogTitle>Access — {report.name}</DialogTitle></DialogHeader>
        <p className="text-sm text-slate-500">
          Data scope: <b>{report.scope_label}</b>. People listed here can open this report only — never other reports or the Report Center. Print and Export work only where ticked.
        </p>

        <div className="rounded-md border border-slate-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <th className="px-3 py-2">User</th><th className="px-3 py-2">Permissions</th><th className="px-3 py-2">Status</th><th className="px-3 py-2 text-right">Action</th></tr></thead>
            <tbody>
              {grants.map((g) => {
                const off = g.status !== "active";
                return (
                  <tr key={g.user_id} className={`border-t border-slate-100 ${off ? "opacity-60" : ""}`}>
                    <td className="px-3 py-2"><div className="font-medium text-slate-800">{g.user_name}</div>
                      <div className="text-xs text-slate-400">{off ? `Revoked ${fmtDateTime(g.revoked_at)}` : g.last_opened_at ? `Last opened ${fmtDateTime(g.last_opened_at)}` : "Not opened yet"}</div></td>
                    <td className="px-3 py-2">{off ? <span className="text-xs text-slate-400">—</span>
                      : <PermBoxes value={g.permissions || ["read"]} data-testid={`perms-${g.user_id}`}
                          onChange={(v) => call(() => api.put(`/reports/saved/${report.id}/access/${g.user_id}`, { permissions: v }))} />}</td>
                    <td className="px-3 py-2">{off
                      ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">Revoked</span>
                      : <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700 ring-1 ring-inset ring-emerald-200">Active</span>}</td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {off ? (
                        <button className="text-xs text-blue-700 hover:underline inline-flex items-center gap-1" onClick={() => call(() => api.post(`/reports/saved/${report.id}/access`, { user_ids: [g.user_id], permissions: g.permissions || ["read"] }))}><RotateCcw size={12} /> Re-grant</button>
                      ) : (
                        <button className="text-xs text-red-600 hover:underline inline-flex items-center gap-1" data-testid={`revoke-${g.user_id}`}
                          onClick={() => call(() => api.delete(`/reports/saved/${report.id}/access/${g.user_id}`))}><ShieldOff size={12} /> Revoke</button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {loading && <div className="p-4 text-sm text-slate-500 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</div>}
          {!loading && grants.length === 0 && <div className="p-6 text-center text-sm text-slate-500">Nobody has access to this report yet.</div>}
        </div>

        <div className="rounded-md border border-slate-200 p-3 space-y-3">
          <div className="text-sm font-semibold text-slate-800">Assign this report to another user</div>
          <SearchPicker options={options} value={pick} onChange={setPick} placeholder="Search a user…" />
          <PermBoxes value={newPerms} onChange={setNewPerms} />
          <div className="flex justify-end"><button className={btnPrimary} disabled={!pick} onClick={add}><KeyRound size={15} /> Grant access</button></div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* --------------------------- Edit saved report dialog --------------------------- */
function EditDialog({ report, meta, onClose, onSaved }) {
  const typeDef = meta.types.find((t) => t.key === report.report_type);
  const [name, setName] = useState(report.name);
  const [desc, setDesc] = useState(report.description || "");
  const [filters, setFilters] = useState(report.filters || {});
  const [scope, setScope] = useState({ type: report.scope.type, department_ids: report.scope.department_ids || [] });
  const save = async () => {
    try {
      await api.put(`/reports/saved/${report.id}`, { name, description: desc, filters: clean(filters), scope });
      toast.success("Report updated"); onSaved(); onClose();
    } catch (e) { toast.error(await errorMessage(e)); }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto" data-testid="edit-saved-dialog">
        <DialogHeader><DialogTitle>Edit saved report — {typeDef.label}</DialogTitle></DialogHeader>
        <div className="grid gap-4">
          <label className="block"><span className="block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Report name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} /></label>
          <label className="block"><span className="block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Description</span>
            <input value={desc} onChange={(e) => setDesc(e.target.value)} className={inputCls} /></label>
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">Criteria</div>
            <FilterFields fields={typeDef.fields.filter((f) => !f.hidden)} values={filters} lookups={meta} onChange={(k, v) => setFilters((p) => ({ ...p, [k]: v }))} />
          </div>
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Data scope</div>
            <ScopePicker meta={meta} type={report.report_type} scope={scope} onChange={setScope} />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2"><button className={btn} onClick={onClose}>Cancel</button><button className={btnPrimary} onClick={save}>Save changes</button></div>
      </DialogContent>
    </Dialog>
  );
}

/* --------------------------- Saved reports tab --------------------------- */
function SavedReports({ meta, onOpen }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [access, setAccess] = useState(null);
  const [edit, setEdit] = useState(null);
  const [del, setDel] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { const { data } = await api.get("/reports/saved"); setRows(data); }
    catch (e) { setError(await errorMessage(e, "Could not load saved reports.")); }
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const shown = rows.filter((r) => `${r.name} ${r.type_label} ${r.created_by}`.toLowerCase().includes(q.trim().toLowerCase()));
  const doDelete = async () => {
    try { await api.delete(`/reports/saved/${del.id}`); toast.success("Saved report deleted"); setDel(null); load(); }
    catch (e) { toast.error(await errorMessage(e)); }
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white" data-testid="saved-reports">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div><div className="font-semibold text-slate-900">Saved reports &amp; access</div>
          <div className="text-xs text-slate-500">{rows.length} saved configuration{rows.length === 1 ? "" : "s"} · they store criteria only, never inventory data</div></div>
        <div className="relative"><Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search saved reports" className="h-9 w-64 rounded-md border border-slate-300 pl-9 pr-3 text-sm focus:outline-none focus:border-blue-500" /></div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="bg-slate-50 border-y border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <th className="px-4 py-2.5">Report</th><th className="px-4 py-2.5">Type</th><th className="px-4 py-2.5">Criteria</th>
            <th className="px-4 py-2.5">Data scope</th><th className="px-4 py-2.5 text-center">Users</th><th className="px-4 py-2.5">Created</th><th className="px-4 py-2.5 text-right">Actions</th></tr></thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className="border-b border-slate-100 hover:bg-blue-50/40 align-top">
                <td className="px-4 py-3"><div className="font-medium text-slate-800">{r.name}</div></td>
                <td className="px-4 py-3 text-slate-600">{r.type_label}</td>
                <td className="px-4 py-3 max-w-xs"><div className="flex flex-wrap gap-1">
                  {r.filter_summary.length === 0 ? <span className="text-slate-400">—</span> : r.filter_summary.map((f) => <span key={f.label} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">{f.label}: {f.value}</span>)}
                </div></td>
                <td className="px-4 py-3 text-slate-600">{r.scope_label}</td>
                <td className="px-4 py-3 text-center">{r.active_grants}</td>
                <td className="px-4 py-3 text-slate-500 whitespace-nowrap"><div>{r.created_by}</div><div className="text-xs">{fmtDateTime(r.created_at)}</div></td>
                <td className="px-4 py-3"><div className="flex justify-end gap-1.5">
                  <button className={btn} title="Open" onClick={() => onOpen(r.id)} data-testid={`saved-open-${r.id}`}><Eye size={14} /></button>
                  <button className={btn} title="Manage access" onClick={() => setAccess(r)} data-testid={`saved-access-${r.id}`}><KeyRound size={14} /></button>
                  <button className={btn} title="Edit criteria & scope" onClick={() => setEdit(r)}><Pencil size={14} /></button>
                  <button className={`${btn} text-red-600 border-red-200 hover:bg-red-50`} title="Delete" onClick={() => setDel(r)}><Trash2 size={14} /></button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" /> Loading…</div>}
        {!loading && error && <div className="py-12 text-center text-sm text-red-600">{error}</div>}
        {!loading && !error && shown.length === 0 && <div className="py-14 text-center text-sm text-slate-500">{rows.length ? "No saved report matches your search." : "No saved reports yet. Run a search in Report Center and press Save & Assign Report."}</div>}
      </div>
      {access && <AccessDialog report={access} meta={meta} onClose={() => setAccess(null)} onChanged={load} />}
      {edit && <EditDialog report={edit} meta={meta} onClose={() => setEdit(null)} onSaved={load} />}
      <Dialog open={!!del} onOpenChange={(o) => !o && setDel(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>Delete “{del?.name}”?</DialogTitle></DialogHeader>
          <p className="text-sm text-slate-600">This removes the saved report and everyone's access to it. Inventory, employees, assignments and history are <b>not</b> affected.</p>
          <div className="flex justify-end gap-2 pt-2"><button className={btn} onClick={() => setDel(null)}>Cancel</button>
            <button className="h-9 px-4 rounded-md bg-red-600 text-white text-sm font-semibold hover:bg-red-700" onClick={doDelete}>Delete</button></div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* --------------------------- page --------------------------- */
export default function ReportCenter() {
  const { user, allowed, menu } = useAuth();
  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState("");
  const [tab, setTab] = useState("reports");
  const [view, setView] = useState("all_inventory");
  const [values, setValues] = useState({});                   // one set of filters shared by every report view
  const [applied, setApplied] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [sort, setSort] = useState({ by: null, dir: "asc" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState("");
  const [viewing, setViewing] = useState(null);

  useEffect(() => {
    api.get("/reports/meta").then(({ data }) => setMeta(data)).catch(async (e) => setMetaError(await errorMessage(e, "Could not load the Report Center.")));
  }, []);

  const typeDef = useMemo(() => meta?.types.find((t) => t.key === view), [meta, view]);
  // filters this view understands; the rest are greyed out and never sent
  const applicable = useMemo(() => new Set((typeDef?.fields || []).filter((f) => !f.hidden).map((f) => f.key).filter((k) => MASTER_KEYS.includes(k))), [typeDef]);
  const activeFilters = useMemo(() => clean(Object.fromEntries(Object.entries(values).filter(([k]) => applicable.has(k)))), [values, applicable]);
  const viewLabel = VIEW_OPTIONS.find(([k]) => k === view)?.[1] || typeDef?.label;

  const fetchRows = useCallback(async (crit, s, p, ps) => {
    setLoading(true); setError("");
    try {
      const { data } = await api.post("/reports/run", { report_type: crit.type, filters: crit.filters, show_all: !!crit.showAll, sort_by: s.by, sort_dir: s.dir, page: p, page_size: ps });
      setResult(data);
    } catch (e) { setResult(null); setError(await errorMessage(e, "The search failed.")); }
    setLoading(false);
  }, []);

  if (menu.length > 0 && !(allowed || []).includes("report-center")) return <Navigate to="/" replace />;
  if (user && user.role !== "super_admin") return <Navigate to="/" replace />;

  const run = (showAll) => {
    const a = { type: view, filters: activeFilters, showAll: showAll || Object.keys(activeFilters).length === 0 };
    setApplied(a); setPage(1); fetchRows(a, sort, 1, pageSize);
  };
  const reset = () => { setApplied(null); setResult(null); setError(""); setSort({ by: null, dir: "asc" }); setPage(1); };
  const clear = () => { setValues({}); reset(); };
  const switchView = (k) => { setView(k); reset(); };
  const onSort = (key) => {
    if (!applied) return;
    const next = sort.by === key ? { by: key, dir: sort.dir === "asc" ? "desc" : "asc" } : { by: key, dir: "asc" };
    setSort(next); setPage(1); fetchRows(applied, next, 1, pageSize);
  };
  const onPage = (p) => { setPage(p); fetchRows(applied, sort, p, pageSize); };
  const onPageSize = (n) => { setPageSize(n); setPage(1); fetchRows(applied, sort, 1, n); };

  const doPrint = async () => {
    setBusy("print");
    try {
      const { data } = await api.post("/reports/run", { report_type: applied.type, filters: applied.filters, show_all: !!applied.showAll, sort_by: sort.by, sort_dir: sort.dir, purpose: "print" });
      if (!printReport({ title: viewLabel, scopeLabel: "All Inventory", result: data })) toast.error("Allow pop-ups to print the report.");
    } catch (e) { toast.error(await errorMessage(e)); }
    setBusy("");
  };
  const doExport = async (format) => {
    setBusy(format);
    try { await downloadExport("/reports/export", { report_type: applied.type, filters: applied.filters, show_all: !!applied.showAll, sort_by: sort.by, sort_dir: sort.dir, format }); }
    catch (e) { toast.error(await errorMessage(e, "Export failed.")); }
    setBusy("");
  };

  if (metaError) return <div className="rounded-lg border border-slate-200 bg-white p-10 text-center text-sm text-red-600">{metaError}</div>;
  if (!meta) return <div className="flex items-center gap-2 text-sm text-slate-500 p-6"><Loader2 size={16} className="animate-spin" /> Loading Report Center…</div>;
  if (viewing) return <ReportViewer reportId={viewing} isAdmin onBack={() => setViewing(null)} />;

  const canAct = !!applied && !!result && !busy;

  return (
    <div className="space-y-5" data-testid="report-center">
      <div className="flex flex-wrap items-end justify-between gap-3 no-print">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">Report Center</h2>
          <p className="text-slate-500 text-sm mt-1">Search, filter, and manage enterprise inventory reports.</p>
        </div>
        <div className="inline-flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
          {[["reports", "Reports"], ["saved", "Saved Reports & Access"]].map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)} data-testid={`tab-${k}`}
              className={`px-3.5 h-8 rounded ${tab === k ? "bg-blue-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}>{label}</button>
          ))}
        </div>
      </div>

      {tab === "saved" ? <SavedReports meta={meta} onOpen={setViewing} /> : (
        <>
          <MasterFilterPanel meta={meta} view={view} onView={switchView} values={values} applicable={applicable}
            onValue={(k, v) => setValues((p) => ({ ...p, [k]: v }))}
            onSearch={() => run(false)} onShowAll={() => run(true)} onClear={clear} onSave={() => setSaving(true)} loading={loading} />

          <div className="rounded-lg border border-slate-200 bg-white">
            <div className="px-4 py-3">
              <div className="font-semibold text-slate-900">{viewLabel}</div>
              <div className="text-xs text-slate-500">{result ? `${result.total} record${result.total === 1 ? "" : "s"} · live data as of ${fmtDateTime(result.generated_at)}` : "Press Search or Show All to see records"}</div>
            </div>
            {(result?.filters_applied || []).length > 0 && (
              <div className="px-4 pb-2 flex flex-wrap gap-1.5">
                {result.filters_applied.map((f) => <span key={f.label} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-xs text-slate-600">{f.label}: <b className="font-medium">{f.value}</b></span>)}
              </div>
            )}
            {(result?.warnings || []).map((w) => <div key={w} className="mx-4 mb-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{w}</div>)}
            <ReportTable
              columns={result?.columns || typeDef.columns} rows={result?.rows || []} total={result?.total || 0}
              page={result?.page || page} pageSize={result?.page_size || pageSize} sortBy={result?.sort_by} sortDir={result?.sort_dir}
              loading={loading} error={error} onSort={onSort} onPage={onPage} onPageSize={onPageSize}
              emptyTitle={applied ? "No records match your search" : "No search yet"}
              emptyHint={applied ? "Try removing a filter or using a shorter keyword. All filled-in filters must match." : "Fill in any filters above and press Search, or press Show All to list every record."}
            />
            <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-4 py-3 no-print" data-testid="report-actions">
              <button className={btn} disabled={!canAct} onClick={doPrint} data-testid="btn-print">{busy === "print" ? <Loader2 size={15} className="animate-spin" /> : <Printer size={15} />} Print</button>
              <button className={btn} disabled={!canAct} onClick={() => doExport("pdf")} data-testid="btn-pdf">{busy === "pdf" ? <Loader2 size={15} className="animate-spin" /> : <FileText size={15} />} Export PDF</button>
              <button className={btn} disabled={!canAct} onClick={() => doExport("xlsx")} data-testid="btn-xlsx">{busy === "xlsx" ? <Loader2 size={15} className="animate-spin" /> : <FileSpreadsheet size={15} />} Export Excel</button>
            </div>
          </div>
        </>
      )}

      {saving && (
        <SaveDialog open meta={meta} type={view} filters={activeFilters}
          onClose={() => setSaving(false)} onSaved={() => setTab("saved")} />
      )}
    </div>
  );
}