import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { UploadCloud, FileText, Trash2, Search, Loader2, X, CheckCircle2, ExternalLink, ScrollText } from "lucide-react";
import api, { API, withAuthParam, formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { compressAll } from "@/lib/imageTools";

const KINDS = [
  { value: "handover", label: "Handover" },
  { value: "takeover", label: "Takeover (return)" },
  { value: "swap", label: "Swap" },
];
const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.value, k.label]));
const KIND_CLS = { handover: "bg-emerald-100 text-emerald-700", takeover: "bg-amber-100 text-amber-700", swap: "bg-indigo-100 text-indigo-700" };
const MAX_MB = 15;
const OK_EXT = ["jpg", "jpeg", "png", "webp", "gif", "pdf"];

const card = "bg-white rounded-xl border border-slate-200 shadow-sm";
const inp = "w-full bg-white border border-slate-300 rounded-lg px-2.5 py-2 text-sm text-slate-800 focus:outline-none focus:ring-1 focus:ring-amber-500";

const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
};
const ext = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");
const fileUrl = (id) => withAuthParam(`${API}/files/${id}/download`);

export default function PaperRecords() {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const [users, setUsers] = useState([]);
  const [rows, setRows] = useState([]);          // files waiting to be saved, one row per paper form
  const [saving, setSaving] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const inputRef = useRef(null);
  const nextId = useRef(1);
  const assetCache = useRef({});             // employee id -> that employee's assigned devices

  useEffect(() => { api.get("/users").then(({ data }) => setUsers(data)).catch(() => {}); }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/paper-records", { params: { q: q || undefined, kind: kindFilter || undefined } });
      setRecords(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not load the records");
    } finally {
      setLoading(false);
    }
  }, [q, kindFilter]);

  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);

  // free the thumbnail URLs when rows go away
  const rowsRef = useRef([]);
  rowsRef.current = rows;
  useEffect(() => () => rowsRef.current.forEach((r) => r.preview && URL.revokeObjectURL(r.preview)), []);

  const sortedUsers = useMemo(() => [...users].sort((a, b) => (a.name || "").localeCompare(b.name || "")), [users]);

  const addFiles = async (fileList) => {
    const picked = [];
    for (const f of Array.from(fileList || [])) {
      if (!OK_EXT.includes(ext(f.name))) { toast.error(`${f.name}: only JPG, PNG, WEBP, GIF or PDF`); continue; }
      picked.push(f);
    }
    if (inputRef.current) inputRef.current.value = "";
    if (!picked.length) return;
    setPreparing(true);
    const prepared = await compressAll(picked);          // phone photos are shrunk before upload
    setPreparing(false);
    const added = [];
    for (const f of prepared) {
      if (f.size > MAX_MB * 1024 * 1024) { toast.error(`${f.name}: larger than ${MAX_MB} MB`); continue; }
      added.push({
        key: nextId.current++, file: f, employee_id: "", kind: "handover", doc_date: "", form_no: "", remarks: "",
        assets: [], asset_ids: [],
        preview: f.type.startsWith("image/") ? URL.createObjectURL(f) : null, status: "ready", error: "",
      });
    }
    if (added.length) setRows((p) => [...p, ...added]);
  };

  // Choosing an employee loads their devices so the form can be tied to the right ones (all ticked by default).
  const chooseEmployee = async (key, employeeId) => {
    setRow(key, { employee_id: employeeId, assets: [], asset_ids: [] });
    if (!employeeId) return;
    let list = assetCache.current[employeeId];
    if (!list) {
      try { list = (await api.get(`/paper-records/employee-assets/${employeeId}`)).data; } catch (e) { list = []; }
      assetCache.current[employeeId] = list;
    }
    setRows((p) => p.map((r) => (r.key === key && r.employee_id === employeeId ? { ...r, assets: list, asset_ids: list.map((a) => a.id) } : r)));
  };
  const toggleAsset = (key, id) => setRows((p) => p.map((r) => (r.key === key
    ? { ...r, asset_ids: r.asset_ids.includes(id) ? r.asset_ids.filter((x) => x !== id) : [...r.asset_ids, id] } : r)));

  const setRow = (key, patch) => setRows((p) => p.map((r) => (r.key === key ? { ...r, ...patch, status: r.status === "error" ? "ready" : r.status } : r)));
  const removeRow = (key) => setRows((p) => { const r = p.find((x) => x.key === key); if (r?.preview) URL.revokeObjectURL(r.preview); return p.filter((x) => x.key !== key); });
  const applyAll = (patch) => setRows((p) => p.map((r) => (r.status === "done" ? r : { ...r, ...patch })));

  const pending = rows.filter((r) => r.status !== "done");
  const missing = pending.filter((r) => !r.employee_id).length;

  const saveAll = async () => {
    if (!pending.length) return;
    if (missing) return toast.error(`Choose an employee for every file (${missing} missing)`);
    setSaving(true);
    setProgress(0);
    let done = 0, failed = 0;
    for (const r of pending) {
      const fd = new FormData();
      fd.append("employee_id", r.employee_id);
      fd.append("kind", r.kind);
      if (r.doc_date) fd.append("doc_date", r.doc_date);
      if (r.form_no) fd.append("form_no", r.form_no);
      if (r.remarks) fd.append("remarks", r.remarks);
      if (r.asset_ids.length) fd.append("asset_ids", r.asset_ids.join(","));
      fd.append("files", r.file);
      try {
        await api.post("/paper-records", fd);
        setRows((p) => p.map((x) => (x.key === r.key ? { ...x, status: "done", error: "" } : x)));
        done += 1;
      } catch (e) {
        failed += 1;
        const msg = formatApiErrorDetail(e.response?.data?.detail) || "Upload failed";
        setRows((p) => p.map((x) => (x.key === r.key ? { ...x, status: "error", error: msg } : x)));
      }
      setProgress(done + failed);
    }
    setSaving(false);
    if (done) toast.success(`${done} scan(s) saved`);
    if (failed) toast.error(`${failed} could not be saved - see the red rows`);
    if (done) {
      load();
      // leave failed rows for another try, clear the finished ones
      setTimeout(() => setRows((p) => { p.filter((x) => x.status === "done").forEach((x) => x.preview && URL.revokeObjectURL(x.preview)); return p.filter((x) => x.status !== "done"); }), 900);
    }
  };

  const remove = async (rec) => {
    if (!window.confirm(`Delete this record of ${rec.employee_name}? The scanned files will be removed.`)) return;
    try {
      await api.delete(`/paper-records/${rec.id}`);
      toast.success("Record deleted");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not delete");
    }
  };

  return (
    <div className="space-y-6 max-w-6xl" data-testid="paper-records-page">
      <div>
        <h2 className="font-head text-xl font-bold text-slate-900">Paper Records</h2>
        <p className="text-sm text-slate-500">Keep photos or scans of handover / takeover forms that were filled in by hand, linked to the employee.</p>
      </div>

      {/* Upload */}
      <div className={`${card} p-5 space-y-4`}>
        <div className="flex items-center gap-3">
          <span className="w-7 h-7 rounded-full bg-amber-100 text-amber-700 text-sm font-bold flex items-center justify-center">1</span>
          <h3 className="font-head font-semibold text-slate-900">Choose the scanned forms</h3>
        </div>
        <label className="flex flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-slate-300 hover:border-amber-400 hover:bg-amber-50/40 transition-colors cursor-pointer py-7 text-center"
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); addFiles(e.dataTransfer.files); }} data-testid="paper-dropzone">
          <UploadCloud className="text-amber-600" />
          <span className="text-sm font-semibold text-slate-700">{preparing ? "Preparing photos…" : "Click to choose files, or drop them here"}</span>
          <span className="text-xs text-slate-500">JPG, PNG, WEBP, GIF or PDF, up to {MAX_MB} MB each. Select many at once - each file becomes one record. Phone photos are shrunk automatically.</span>
          <input ref={inputRef} type="file" multiple accept=".jpg,.jpeg,.png,.webp,.gif,.pdf,image/*,application/pdf" className="hidden"
            onChange={(e) => addFiles(e.target.files)} data-testid="paper-file-input" />
        </label>

        {rows.length > 0 && (
          <>
            <div className="flex items-center gap-3 pt-1">
              <span className="w-7 h-7 rounded-full bg-amber-100 text-amber-700 text-sm font-bold flex items-center justify-center">2</span>
              <h3 className="font-head font-semibold text-slate-900">Say whose form it is</h3>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm rounded-lg bg-slate-50 border border-slate-200 px-3 py-2">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Set for all files:</span>
              <select className={`${inp} !w-auto`} defaultValue="" onChange={(e) => e.target.value && applyAll({ kind: e.target.value })} data-testid="paper-all-kind">
                <option value="">Type…</option>
                {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
              </select>
              <input type="date" className={`${inp} !w-auto`} onChange={(e) => applyAll({ doc_date: e.target.value })} title="Form date for all" />
              <button onClick={() => setRows((p) => { p.forEach((r) => r.preview && URL.revokeObjectURL(r.preview)); return []; })}
                className="ml-auto text-xs text-red-600 hover:text-red-700 font-semibold">Clear list</button>
            </div>

            <div className="space-y-2">
              {rows.map((r) => (
                <div key={r.key} data-testid={`paper-row-${r.key}`}
                  className={`grid grid-cols-12 gap-2 items-center p-2.5 rounded-lg border ${r.status === "done" ? "border-emerald-200 bg-emerald-50/60" : r.status === "error" ? "border-red-300 bg-red-50/60" : "border-slate-200 bg-white"}`}>
                  <div className="col-span-12 md:col-span-3 flex items-center gap-2 min-w-0">
                    {r.preview
                      ? <a href={r.preview} target="_blank" rel="noreferrer"><img src={r.preview} alt="" className="w-12 h-12 rounded object-cover border border-slate-200" /></a>
                      : <span className="w-12 h-12 rounded bg-red-50 text-red-500 flex items-center justify-center border border-red-100"><FileText size={20} /></span>}
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-slate-800 truncate" title={r.file.name}>{r.file.name}</div>
                      <div className="text-[11px] text-slate-400">{(r.file.size / 1024 / 1024).toFixed(2)} MB</div>
                    </div>
                  </div>
                  <select className={`${inp} col-span-12 md:col-span-3`} value={r.employee_id} disabled={r.status === "done"} onChange={(e) => chooseEmployee(r.key, e.target.value)} data-testid={`paper-emp-${r.key}`}>
                    <option value="">Employee *</option>
                    {sortedUsers.map((u) => <option key={u.id} value={u.id}>{u.name}{u.department_name ? ` — ${u.department_name}` : ""}</option>)}
                  </select>
                  <select className={`${inp} col-span-6 md:col-span-2`} value={r.kind} disabled={r.status === "done"} onChange={(e) => setRow(r.key, { kind: e.target.value })}>
                    {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                  </select>
                  <input type="date" className={`${inp} col-span-6 md:col-span-2`} value={r.doc_date} disabled={r.status === "done"} onChange={(e) => setRow(r.key, { doc_date: e.target.value })} title="Date on the form" />
                  <input className={`${inp} col-span-9 md:col-span-1`} placeholder="Form no" value={r.form_no} disabled={r.status === "done"} onChange={(e) => setRow(r.key, { form_no: e.target.value })} />
                  <div className="col-span-3 md:col-span-1 flex justify-end">
                    {r.status === "done" ? <CheckCircle2 className="text-emerald-600" size={18} />
                      : <button onClick={() => removeRow(r.key)} className="text-slate-400 hover:text-red-600" aria-label="Remove"><X size={18} /></button>}
                  </div>
                  {r.assets.length > 0 && r.status !== "done" && (
                    <div className="col-span-12 flex flex-wrap items-center gap-1.5 pl-1" data-testid={`paper-assets-${r.key}`}>
                      <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold mr-1">Covers:</span>
                      {r.assets.map((a) => {
                        const on = r.asset_ids.includes(a.id);
                        return (
                          <button type="button" key={a.id} onClick={() => toggleAsset(r.key, a.id)}
                            className={`px-2 py-0.5 rounded-full border text-[11px] ${on ? "bg-amber-100 border-amber-300 text-amber-800" : "bg-white border-slate-200 text-slate-400 line-through"}`}>
                            {a.name}{a.tag_id ? ` · ${a.tag_id}` : a.serial_no ? ` · ${a.serial_no}` : ""}
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {r.error && <div className="col-span-12 text-xs text-red-600 pl-1">{r.error}</div>}
                </div>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button onClick={saveAll} disabled={saving || !pending.length} data-testid="paper-save-all"
                className="px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold disabled:opacity-50 flex items-center gap-2">
                {saving ? <Loader2 size={16} className="animate-spin" /> : <UploadCloud size={16} />}
                {saving ? `Saving ${progress} of ${pending.length + progress}…` : `Save ${pending.length} record(s)`}
              </button>
              {missing > 0 && !saving && <span className="text-xs text-amber-700">{missing} file(s) still need an employee.</span>}
            </div>
          </>
        )}
      </div>

      {/* Saved records */}
      <div className={card}>
        <div className="px-5 py-4 border-b border-slate-100 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <ScrollText size={18} className="text-amber-600" />
            <h3 className="font-head font-semibold text-slate-900">Saved records</h3>
            <span className="text-xs text-slate-400">({records.length})</span>
          </div>
          <div className="ml-auto flex flex-wrap gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
              <input className={`${inp} !pl-8 !w-64`} placeholder="Search employee, email, form no…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="paper-search" />
            </div>
            <select className={`${inp} !w-auto`} value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}>
              <option value="">All types</option>
              {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wider">
              <tr>
                <th className="px-5 py-2.5 text-left font-semibold">Employee</th>
                <th className="px-3 py-2.5 text-left font-semibold">Type</th>
                <th className="px-3 py-2.5 text-left font-semibold">Form date</th>
                <th className="px-3 py-2.5 text-left font-semibold">Form no</th>
                <th className="px-3 py-2.5 text-left font-semibold">Files</th>
                <th className="px-3 py-2.5 text-left font-semibold">Added by</th>
                {isSuper && <th className="px-3 py-2.5"></th>}
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={7} className="px-5 py-8 text-center text-slate-400"><Loader2 className="inline animate-spin mr-2" size={16} />Loading…</td></tr>}
              {!loading && records.length === 0 && <tr><td colSpan={7} className="px-5 py-10 text-center text-slate-400">No paper records yet.</td></tr>}
              {!loading && records.map((rec) => (
                <tr key={rec.id} className="border-t border-slate-100 align-top" data-testid={`paper-record-${rec.id}`}>
                  <td className="px-5 py-3">
                    <div className="font-medium text-slate-800">{rec.employee_name}</div>
                    <div className="text-xs text-slate-500">{[rec.department_name, rec.employee_email].filter(Boolean).join(" · ")}</div>
                  </td>
                  <td className="px-3 py-3"><span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${KIND_CLS[rec.kind] || "bg-slate-100 text-slate-600"}`}>{KIND_LABEL[rec.kind] || rec.kind}</span></td>
                  <td className="px-3 py-3 text-slate-600">{fmtDate(rec.doc_date)}</td>
                  <td className="px-3 py-3 font-mono text-slate-600">{rec.form_no || "—"}</td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      {rec.files.map((f) => (
                        <a key={f.id} href={fileUrl(f.id)} target="_blank" rel="noreferrer" title={f.name}
                          className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-slate-200 hover:border-amber-400 hover:bg-amber-50 text-xs text-slate-700 max-w-[200px]">
                          {f.content_type?.startsWith("image/")
                            ? <img src={fileUrl(f.id)} alt="" className="w-8 h-8 rounded object-cover" loading="lazy" />
                            : <FileText size={16} className="text-red-500 shrink-0" />}
                          <span className="truncate">{f.name}</span><ExternalLink size={11} className="shrink-0 text-slate-400" />
                        </a>
                      ))}
                    </div>
                    {rec.assets?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {rec.assets.map((a) => <span key={a.id} className="px-1.5 py-0.5 rounded bg-slate-100 text-[11px] text-slate-600">{a.name}{a.tag_id ? ` · ${a.tag_id}` : ""}</span>)}
                      </div>
                    )}
                    {rec.remarks && <div className="text-xs text-slate-500 mt-1">{rec.remarks}</div>}
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-500">{rec.created_by}<div>{fmtDate(rec.created_at)}</div></td>
                  {isSuper && <td className="px-3 py-3 text-right"><button onClick={() => remove(rec)} className="text-slate-400 hover:text-red-600" aria-label="Delete record"><Trash2 size={16} /></button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}