import { useRef, useState } from "react";
import { toast } from "sonner";
import { Upload, Download, FileSpreadsheet, CheckCircle2, AlertTriangle, XCircle, Users as UsersIcon, Package, Loader2, ShieldAlert } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";

const KINDS = {
  users: {
    label: "Employees (users)", icon: UsersIcon,
    blurb: "Create login accounts for your existing employees. Each gets a temporary password and must choose their own at first login.",
    columns: "Name, Email, Department, Role (optional: Role Label, IT Team, Can Raise PR, Can Create PO)",
  },
  assets: {
    label: "Assets they already hold", icon: Package,
    blurb: "Record devices that employees already have. Import the employees first - every asset is matched to a user by email.",
    columns: "Employee Email, Product Name (optional: Brand, Category, Serial No, Tag ID, Assigned Date, Remarks)",
  },
};

const STATUS = {
  ok: { label: "Ready", cls: "bg-emerald-100 text-emerald-700", icon: CheckCircle2 },
  skip: { label: "Skipped", cls: "bg-amber-100 text-amber-700", icon: AlertTriangle },
  error: { label: "Error", cls: "bg-red-100 text-red-700", icon: XCircle },
};

const card = "bg-white rounded-xl border border-slate-200 shadow-sm";

function StepTitle({ n, children }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="w-7 h-7 rounded-full bg-amber-100 text-amber-700 text-sm font-bold flex items-center justify-center">{n}</span>
      <h3 className="font-head font-semibold text-slate-900">{children}</h3>
    </div>
  );
}

function Stat({ label, value, tone }) {
  return (
    <div className="rounded-lg border border-slate-200 px-4 py-3 bg-white">
      <div className={`text-2xl font-head font-bold ${tone}`}>{value}</div>
      <div className="text-xs uppercase tracking-wider text-slate-500 mt-0.5">{label}</div>
    </div>
  );
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

const csvCell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;

export default function BulkImport() {
  const { user } = useAuth();
  const [kind, setKind] = useState("users");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);     // result of the dry run
  const [result, setResult] = useState(null);       // result of the real import
  const [busy, setBusy] = useState(false);
  const [allowPartial, setAllowPartial] = useState(false);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const inputRef = useRef(null);

  if (user && user.role !== "super_admin") {
    return (
      <div className={`${card} p-8 max-w-lg flex items-start gap-3`} data-testid="import-denied">
        <ShieldAlert className="text-red-500 shrink-0" />
        <div>
          <h2 className="font-head font-semibold text-slate-900">Super Admin only</h2>
          <p className="text-sm text-slate-600 mt-1">Bulk import can only be used by a Super Admin.</p>
        </div>
      </div>
    );
  }

  const reset = () => { setFile(null); setPreview(null); setResult(null); setAllowPartial(false); setOnlyProblems(false); if (inputRef.current) inputRef.current.value = ""; };
  const switchKind = (k) => { if (k !== kind) { reset(); setKind(k); } };
  const onPick = (f) => { setFile(f || null); setPreview(null); setResult(null); setAllowPartial(false); };

  const downloadTemplate = async (fmt) => {
    try {
      const { data } = await api.get(`/import/template/${kind}`, { params: { fmt }, responseType: "blob" });
      saveBlob(data, `${kind}_import_template.${fmt}`);
    } catch (e) {
      // blob error bodies need decoding to show the server's message
      let msg = "Could not download the template";
      try { msg = formatApiErrorDetail(JSON.parse(await e.response.data.text()).detail); } catch (_) { /* keep default */ }
      toast.error(msg);
    }
  };

  const send = async (dryRun) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("dry_run", dryRun ? "true" : "false");
    fd.append("allow_partial", allowPartial ? "true" : "false");
    setBusy(true);
    try {
      const { data } = await api.post(`/import/${kind}`, fd);
      if (dryRun) { setPreview(data); setOnlyProblems(data.errors > 0); }
      else { setResult(data); setPreview(null); toast.success(`${data.created} ${kind === "users" ? "user(s)" : "asset(s)"} imported`); }
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Import failed");
    } finally {
      setBusy(false);
    }
  };

  const downloadCredentials = () => {
    const lines = ["Name,Email,Temporary Password", ...result.credentials.map((c) => [c.name, c.email, c.temporary_password].map(csvCell).join(","))];
    saveBlob(new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }), `new_user_credentials_${result.batch_id}.csv`);
  };

  const shownRows = preview ? preview.rows.filter((r) => !onlyProblems || r.status !== "ok") : [];
  const canImport = preview && preview.ok > 0 && (preview.errors === 0 || allowPartial) && !busy;
  const noun = kind === "users" ? "user" : "asset";

  return (
    <div className="space-y-6 max-w-5xl" data-testid="bulk-import-page">
      <div>
        <h2 className="font-head text-xl font-bold text-slate-900">Bulk Import</h2>
        <p className="text-sm text-slate-500">Load many employees or assets at once from an Excel or CSV file. Super Admin only.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {Object.entries(KINDS).map(([k, v]) => {
          const Icon = v.icon;
          const active = k === kind;
          return (
            <button key={k} onClick={() => switchKind(k)} data-testid={`import-kind-${k}`}
              className={`text-left rounded-xl border p-4 transition-all ${active ? "border-amber-400 bg-amber-50/60 shadow-sm" : "border-slate-200 bg-white hover:border-amber-300"}`}>
              <div className="flex items-center gap-3">
                <span className={`w-10 h-10 rounded-lg flex items-center justify-center ${active ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500"}`}><Icon size={20} /></span>
                <div>
                  <div className="font-head font-semibold text-slate-900">{k === "users" ? "1. " : "2. "}{v.label}</div>
                  <div className="text-xs text-slate-500 mt-0.5">{v.blurb}</div>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Step 1 */}
      <div className={`${card} p-5`}>
        <StepTitle n={1}>Download the template and fill it in</StepTitle>
        <p className="text-sm text-slate-600 mb-3">Columns: {KINDS[kind].columns}. Columns marked * are required. Keep the heading row as it is.</p>
        <div className="flex flex-wrap gap-3">
          <button onClick={() => downloadTemplate("xlsx")} data-testid="import-template-xlsx"
            className="px-4 py-2 rounded-lg border border-amber-300 text-amber-700 text-sm font-semibold hover:bg-amber-50 flex items-center gap-2"><FileSpreadsheet size={16} /> Excel template</button>
          <button onClick={() => downloadTemplate("csv")} data-testid="import-template-csv"
            className="px-4 py-2 rounded-lg border border-slate-300 text-slate-700 text-sm font-semibold hover:bg-slate-50 flex items-center gap-2"><Download size={16} /> CSV template</button>
        </div>
      </div>

      {/* Step 2 */}
      {!result && (
        <div className={`${card} p-5`}>
          <StepTitle n={2}>Upload the file and check it</StepTitle>
          <p className="text-sm text-slate-600 mb-3">Nothing is saved at this step - the file is only checked and every problem is listed by row.</p>
          <div className="flex flex-wrap items-center gap-3">
            <input ref={inputRef} type="file" accept=".xlsx,.csv" onChange={(e) => onPick(e.target.files?.[0])} data-testid="import-file"
              className="block text-sm text-slate-600 file:mr-3 file:px-4 file:py-2 file:rounded-lg file:border-0 file:bg-slate-100 file:text-slate-700 file:font-semibold hover:file:bg-slate-200" />
            <button onClick={() => send(true)} disabled={!file || busy} data-testid="import-check"
              className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-semibold disabled:opacity-50 flex items-center gap-2">
              {busy && !preview ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />} Check file
            </button>
          </div>
        </div>
      )}

      {/* Step 3: preview */}
      {preview && (
        <div className={`${card} p-5 space-y-4`} data-testid="import-preview">
          <StepTitle n={3}>Review, then import</StepTitle>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Rows in file" value={preview.total} tone="text-slate-900" />
            <Stat label="Ready to import" value={preview.ok} tone="text-emerald-600" />
            <Stat label="Skipped" value={preview.skipped} tone="text-amber-600" />
            <Stat label="Errors" value={preview.errors} tone="text-red-600" />
          </div>

          {preview.rows.some((r) => r.status !== "ok") && (
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input type="checkbox" className="w-4 h-4 accent-amber-600" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
              Show only rows with problems
            </label>
          )}

          <div className="rounded-lg border border-slate-200 overflow-auto max-h-[420px]">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wider sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold w-16">Row</th>
                  <th className="px-3 py-2 text-left font-semibold w-28">Status</th>
                  <th className="px-3 py-2 text-left font-semibold">{kind === "users" ? "Employee" : "Asset → Employee"}</th>
                  <th className="px-3 py-2 text-left font-semibold">What to fix</th>
                </tr>
              </thead>
              <tbody>
                {shownRows.map((r) => {
                  const S = STATUS[r.status]; const Icon = S.icon;
                  return (
                    <tr key={r.row} className="border-t border-slate-100 align-top" data-testid={`import-row-${r.row}`}>
                      <td className="px-3 py-2 font-mono text-slate-500">{r.row}</td>
                      <td className="px-3 py-2"><span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold ${S.cls}`}><Icon size={12} /> {S.label}</span></td>
                      <td className="px-3 py-2 text-slate-800">{r.summary}</td>
                      <td className="px-3 py-2 text-slate-600">{r.messages.length ? r.messages.map((m, i) => <div key={i}>{m}</div>) : "—"}</td>
                    </tr>
                  );
                })}
                {shownRows.length === 0 && <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-400">No rows to show</td></tr>}
              </tbody>
            </table>
          </div>

          {preview.errors > 0 && (
            <label className="flex items-start gap-2 text-sm text-slate-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
              <input type="checkbox" className="w-4 h-4 mt-0.5 accent-amber-600" checked={allowPartial} onChange={(e) => setAllowPartial(e.target.checked)} data-testid="import-allow-partial" />
              <span>Import only the {preview.ok} ready row(s) and leave out the {preview.errors} row(s) with errors. (Or fix the file and check it again.)</span>
            </label>
          )}

          <div className="flex flex-wrap gap-3">
            <button onClick={() => send(false)} disabled={!canImport} data-testid="import-confirm"
              className="px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold disabled:opacity-50 flex items-center gap-2">
              {busy && <Loader2 size={16} className="animate-spin" />} Import {preview.ok} {noun}(s)
            </button>
            <button onClick={reset} className="px-4 py-2.5 rounded-lg border border-slate-300 text-slate-600 text-sm font-semibold hover:bg-slate-50">Start over</button>
          </div>
        </div>
      )}

      {/* Done */}
      {result && (
        <div className={`${card} p-5 space-y-4`} data-testid="import-result">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="text-emerald-600 shrink-0 mt-0.5" />
            <div>
              <h3 className="font-head font-semibold text-slate-900">{result.created} {noun}(s) imported</h3>
              <p className="text-sm text-slate-600">
                {result.skipped > 0 && `${result.skipped} skipped. `}{result.errors > 0 && `${result.errors} left out because of errors. `}
                Batch reference: <span className="font-mono">{result.batch_id}</span>
              </p>
            </div>
          </div>

          {kind === "users" && result.credentials.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-4 space-y-3">
              <p className="text-sm text-slate-700">
                <b>Temporary passwords - shown only now.</b> They are not stored anywhere readable, so download the list and hand each person their own.
                Everyone must choose a new password at first login.
              </p>
              <button onClick={downloadCredentials} data-testid="import-download-credentials"
                className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-semibold flex items-center gap-2"><Download size={16} /> Download credentials (CSV)</button>
              <div className="rounded-lg border border-slate-200 bg-white overflow-auto max-h-64">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wider sticky top-0">
                    <tr><th className="px-3 py-2 text-left font-semibold">Name</th><th className="px-3 py-2 text-left font-semibold">Email</th><th className="px-3 py-2 text-left font-semibold">Temporary password</th></tr>
                  </thead>
                  <tbody>
                    {result.credentials.map((c) => (
                      <tr key={c.email} className="border-t border-slate-100">
                        <td className="px-3 py-1.5">{c.name}</td><td className="px-3 py-1.5 text-slate-600">{c.email}</td>
                        <td className="px-3 py-1.5 font-mono select-all">{c.temporary_password}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-3">
            {kind === "users" && (
              <button onClick={() => { reset(); setKind("assets"); }} className="px-4 py-2 rounded-lg border border-amber-300 text-amber-700 text-sm font-semibold hover:bg-amber-50">Next: import their assets →</button>
            )}
            <button onClick={reset} className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 text-sm font-semibold hover:bg-slate-50">Import another file</button>
          </div>
        </div>
      )}
    </div>
  );
}
