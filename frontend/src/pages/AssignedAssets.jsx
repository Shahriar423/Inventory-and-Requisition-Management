import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Search, FileDown, ChevronRight, ChevronDown, PackageOpen, Users, Laptop, Plus, Trash2, FileText, Camera, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import api, { API, withAuthParam, onDataRefresh, requestDataRefresh, formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { compressAll } from "@/lib/imageTools";

const PAGE_SIZE = 15;

const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? "—" : d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
};

const initials = (name = "") =>
  name.split(" ").filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";

const blankDevice = () => ({ name: "", brand: "", category_id: "", tag_id: "", serial_no: "", specification: "", assigned_date: "" });

// Register devices an existing employee already holds (no handover slip behind them).
function AddExistingDialog({ open, onOpenChange }) {
  const [users, setUsers] = useState([]);
  const [cats, setCats] = useState([]);
  const [userQ, setUserQ] = useState("");
  const [userId, setUserId] = useState("");
  const [devices, setDevices] = useState([blankDevice()]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.get("/users").then(({ data }) => setUsers(data)).catch(() => {});
    api.get("/categories").then(({ data }) => setCats(data)).catch(() => {});
    setUserQ(""); setUserId(""); setDevices([blankDevice()]);
  }, [open]);

  const shownUsers = users.filter((u) =>
    [u.name, u.email, u.department_name].filter(Boolean).join(" ").toLowerCase().includes(userQ.toLowerCase()));
  const setDev = (i, k, v) => setDevices((p) => p.map((d, idx) => (idx === i ? { ...d, [k]: v } : d)));

  const save = async () => {
    if (!userId) return toast.error("Select an employee");
    if (devices.some((d) => !d.name.trim())) return toast.error("Every device needs a product name");
    setSaving(true);
    try {
      const { data } = await api.post("/assets/assign-existing", {
        user_id: userId,
        devices: devices.map((d) => ({
          ...d, category_id: d.category_id || null,
          assigned_date: d.assigned_date ? new Date(d.assigned_date).toISOString() : null,
        })),
      });
      toast.success(`${data.created} device(s) added to ${data.employee}`);
      requestDataRefresh();
      onOpenChange(false);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const inp = "px-3 py-2 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm w-full";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto" data-testid="add-existing-dialog">
        <DialogHeader><DialogTitle>Add existing asset to an employee</DialogTitle></DialogHeader>
        <p className="text-xs text-slate-500 -mt-1">
          For devices the employee already holds. They are recorded as assigned and do not change the available stock.
        </p>

        <div className="space-y-2">
          <label className="text-xs font-semibold text-slate-600">Employee</label>
          <input value={userQ} onChange={(e) => setUserQ(e.target.value)} placeholder="Type to filter employees…" className={inp} data-testid="existing-user-search" />
          <select value={userId} onChange={(e) => setUserId(e.target.value)} className={inp} data-testid="existing-user-select" size={Math.min(Math.max(shownUsers.length, 2), 5)}>
            {shownUsers.map((u) => (
              <option key={u.id} value={u.id}>{u.name}{u.department_name ? ` — ${u.department_name}` : ""}</option>
            ))}
          </select>
        </div>

        <div className="space-y-3">
          <label className="text-xs font-semibold text-slate-600">Devices</label>
          {devices.map((d, i) => (
            <div key={i} className="grid grid-cols-2 md:grid-cols-6 gap-2 p-3 rounded-lg bg-slate-50 border border-slate-200" data-testid={`existing-device-${i}`}>
              <input className={`${inp} md:col-span-2`} placeholder="Product name *" value={d.name} onChange={(e) => setDev(i, "name", e.target.value)} />
              <input className={inp} placeholder="Brand / model" value={d.brand} onChange={(e) => setDev(i, "brand", e.target.value)} />
              <select className={inp} value={d.category_id} onChange={(e) => setDev(i, "category_id", e.target.value)}>
                <option value="">Category</option>
                {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <input className={inp} placeholder="Tag ID" value={d.tag_id} onChange={(e) => setDev(i, "tag_id", e.target.value)} />
              <input className={inp} placeholder="Serial No" value={d.serial_no} onChange={(e) => setDev(i, "serial_no", e.target.value)} />
              <input className={`${inp} col-span-2 md:col-span-6`} placeholder="Specification (e.g. Core i5 / 8 GB RAM / 256 GB SSD / 14 inch)" value={d.specification} onChange={(e) => setDev(i, "specification", e.target.value)} data-testid={`existing-spec-${i}`} />
              <input type="date" className={`${inp} md:col-span-2`} value={d.assigned_date} onChange={(e) => setDev(i, "assigned_date", e.target.value)} title="Assigned on" />
              <div className="md:col-span-4 flex justify-end">
                {devices.length > 1 && (
                  <button onClick={() => setDevices((p) => p.filter((_, idx) => idx !== i))} className="text-red-500 hover:text-red-700 text-xs flex items-center gap-1">
                    <Trash2 size={14} /> Remove
                  </button>
                )}
              </div>
            </div>
          ))}
          <button onClick={() => setDevices((p) => [...p, blankDevice()])} className="text-sm font-semibold text-amber-600 hover:text-amber-700 flex items-center gap-1" data-testid="existing-add-device">
            <Plus size={14} /> Add another device
          </button>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={() => onOpenChange(false)} className="px-4 py-2 rounded-lg border border-slate-300 text-sm">Cancel</button>
          <button onClick={save} disabled={saving} className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-semibold disabled:opacity-50" data-testid="existing-save">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const KIND_SHORT = { handover: "Handover", takeover: "Takeover", swap: "Swap" };
const fileUrl = (id) => withAuthParam(`${API}/files/${id}/download`);

// Clickable thumbnails of the scanned paper forms; click opens the photo / PDF (save it from the viewer).
function FormChips({ records, assetId, onChanged }) {
  const [removing, setRemoving] = useState(null);
  if (!records?.length) return <span className="text-slate-300">—</span>;

  const remove = async (rec, f) => {
    const shared = assetId && (rec.asset_count || 0) > 1;
    const msg = shared
      ? "Remove this form photo from this device? Other devices that use the same form keep it."
      : `Remove this ${KIND_SHORT[rec.kind] || ""} form photo (${f.name})? This cannot be undone.`;
    if (!window.confirm(msg)) return;
    setRemoving(f.id);
    try {
      await api.delete(`/paper-records/${rec.id}/files/${f.id}`, { params: assetId ? { asset_id: assetId } : {} });
      toast.success("Photo removed");
      onChanged?.();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not remove the photo");
    } finally {
      setRemoving(null);
    }
  };

  return (
    <div className="flex flex-wrap gap-1.5">
      {records.flatMap((rec) =>
        rec.files.map((f) => (
          <div key={`${rec.id}-${f.id}`} className="relative">
            <a href={fileUrl(f.id)} target="_blank" rel="noreferrer"
              title={`${KIND_SHORT[rec.kind] || rec.kind}${rec.form_no ? ` · Form ${rec.form_no}` : ""} · ${f.name}`}
              className="group flex items-center gap-1 pl-1 pr-2 py-0.5 rounded-md border border-slate-200 bg-white hover:border-amber-400 hover:bg-amber-50 text-[11px] text-slate-700"
              data-testid="form-photo-link">
              {f.content_type?.startsWith("image/")
                ? <img src={fileUrl(f.id)} alt="" loading="lazy" className="w-7 h-7 rounded object-cover" />
                : <span className="w-7 h-7 rounded bg-red-50 text-red-500 flex items-center justify-center"><FileText size={14} /></span>}
              <span>{KIND_SHORT[rec.kind] || rec.kind}</span>
            </a>
            <button type="button" onClick={() => remove(rec, f)} disabled={removing === f.id}
              title="Remove this photo" aria-label="Remove this photo" data-testid="form-photo-remove"
              className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-white border border-slate-300 text-slate-500 hover:bg-red-500 hover:border-red-500 hover:text-white flex items-center justify-center shadow-sm disabled:opacity-50">
              {removing === f.id ? <Loader2 size={9} className="animate-spin" /> : <X size={10} />}
            </button>
          </div>
        ))
      )}
    </div>
  );
}

// Attach a photo / scan of the hand-filled form to ONE device (and its holder).
function AttachPhotoDialog({ device, onClose, onSaved }) {
  const [kind, setKind] = useState("handover");
  const [date, setDate] = useState("");
  const [formNo, setFormNo] = useState("");
  const [picked, setPicked] = useState([]);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const inp = "w-full bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm";

  const choose = async (list) => {
    setBusy(true);
    setPicked(await compressAll(Array.from(list || [])));
    setBusy(false);
  };
  const save = async () => {
    if (!device) return;
    if (!device.assigned_to_user_id) return toast.error("This device is not linked to a user account");
    if (!picked.length) return toast.error("Choose a photo or PDF first");
    const fd = new FormData();
    fd.append("employee_id", device.assigned_to_user_id);
    fd.append("kind", kind);
    fd.append("asset_ids", device.id);
    if (date) fd.append("doc_date", date);
    if (formNo) fd.append("form_no", formNo);
    picked.forEach((f) => fd.append("files", f, f.name));
    setSaving(true);
    try {
      await api.post("/paper-records", fd);
      toast.success("Photo saved");
      onSaved();
      onClose();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not save the photo");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={!!device} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="max-w-md" data-testid="attach-photo-dialog">
        <DialogHeader><DialogTitle>Add form photo</DialogTitle></DialogHeader>
        <p className="text-sm text-slate-600">
          For <b>{device?.name}</b>{device?.tag_id ? <span className="font-mono"> ({device.tag_id})</span> : null} held by <b>{device?.assigned_to}</b>.
        </p>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <select className={inp} value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="handover">Handover form</option>
              <option value="takeover">Takeover (return) form</option>
              <option value="swap">Swap form</option>
            </select>
            <input type="date" className={inp} value={date} onChange={(e) => setDate(e.target.value)} title="Date on the form" />
          </div>
          <input className={inp} placeholder="Paper form no (optional)" value={formNo} onChange={(e) => setFormNo(e.target.value)} />
          <label className="flex items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-300 hover:border-amber-400 py-5 text-sm text-slate-600 cursor-pointer">
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Camera size={16} className="text-amber-600" />}
            {picked.length ? `${picked.length} file(s): ${picked.map((f) => f.name).join(", ").slice(0, 60)}` : "Choose photo or PDF"}
            <input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.gif,.pdf,image/*,application/pdf" className="hidden" data-testid="attach-photo-input" onChange={(e) => choose(e.target.files)} />
          </label>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-slate-300 text-sm">Cancel</button>
          <button onClick={save} disabled={saving || busy} data-testid="attach-photo-save"
            className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-semibold disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Inventory-style register: one row per employee (scales to hundreds of users); expand a row
// to see every device that employee holds, with tag/serial, category and handover slip.
export default function AssignedAssets() {
  const { user } = useAuth();
  const personal = user?.role === "executive";
  const [assets, setAssets] = useState([]);
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("");
  const [open, setOpen] = useState({});
  const [page, setPage] = useState(1);
  const [addOpen, setAddOpen] = useState(false);
  const [paperMap, setPaperMap] = useState({ by_asset: {}, by_employee: {} });   // scanned forms per asset
  const [attachFor, setAttachFor] = useState(null);
  const canAddExisting =
    user?.role === "super_admin" ||
    (user?.role === "dept_head" && user?.department_type === "it");

  const loadForms = useCallback(() => {
    if (!canAddExisting) return;
    api.get("/paper-records/asset-map").then(({ data }) => setPaperMap(data)).catch(() => {});
  }, [canAddExisting]);

  useEffect(() => {
    const load = () => { api.get("/assets").then(({ data }) => setAssets(data)).catch(() => {}); loadForms(); };
    load();
    return onDataRefresh(load);
  }, [loadForms]);

  // Group the assigned assets by employee.
  const employees = useMemo(() => {
    const map = {};
    assets
      .filter((a) => (a.status === "assigned" || a.status === "return_pending") && a.assigned_to)
      .forEach((a) => {
        const key = a.assigned_to;
        if (!map[key]) {
          map[key] = { name: key, email: a.assigned_email, department: a.assigned_department_name || "—", devices: [] };
        }
        map[key].devices.push(a);
        if (!map[key].email && a.assigned_email) map[key].email = a.assigned_email;
        if (map[key].department === "—" && a.assigned_department_name) map[key].department = a.assigned_department_name;
      });
    return Object.values(map).sort((x, y) => x.name.localeCompare(y.name));
  }, [assets]);

  const departments = useMemo(
    () => [...new Set(employees.map((e) => e.department).filter((d) => d && d !== "—"))].sort(),
    [employees]
  );

  // Every word typed must match somewhere on the employee (name, email, department) or one of their
  // devices, in any order - so "rahim laptop" finds Rahim's laptops, and "laptop" finds everyone holding one.
  const words = useMemo(() => q.trim().toLowerCase().split(/\s+/).filter(Boolean), [q]);
  const searching = words.length > 0;
  const deviceText = (d) => [d.name, d.brand, d.serial_no, d.tag_id, d.category_name, d.assigned_slip_no, d.specification, d.remarks]
    .filter(Boolean).join(" ").toLowerCase();
  const deviceMatches = (d) => searching && words.some((w) => deviceText(d).includes(w));

  const filtered = useMemo(() => {
    return employees.filter((e) => {
      if (dept && e.department !== dept) return false;
      if (!words.length) return true;
      const text = [e.name, e.email, e.department, ...e.devices.map(deviceText)].filter(Boolean).join(" ").toLowerCase();
      return words.every((w) => text.includes(w));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employees, words, dept]);

  useEffect(() => { setPage(1); setOpen({}); }, [q, dept]);

  const totalDevices = filtered.reduce((n, e) => n + e.devices.length, 0);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const rows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  // While searching, matching employees open automatically (up to 25 at a time) so the devices are visible at once;
  // clicking a row still opens/closes it by hand.
  const autoOpen = searching && filtered.length <= 25;
  const isRowOpen = (name) => (name in open ? open[name] : autoOpen);
  const toggle = (name) => setOpen((o) => ({ ...o, [name]: !isRowOpen(name) }));
  const matchedDevices = searching ? filtered.reduce((n, e) => n + e.devices.filter(deviceMatches).length, 0) : 0;

  const productSummary = (devices) => {
    const counts = {};
    devices.forEach((d) => { counts[d.name] = (counts[d.name] || 0) + 1; });
    const parts = Object.entries(counts).map(([n, c]) => (c > 1 ? `${n} ×${c}` : n));
    return parts.length > 3 ? `${parts.slice(0, 3).join(", ")} +${parts.length - 3} more` : parts.join(", ");
  };

  return (
    <div className="space-y-6" data-testid="assigned-assets-page">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">{personal ? "My Assets" : "Assigned Assets"}</h2>
          <p className="text-slate-500 text-sm mt-1">
            {personal ? "Equipment currently assigned to you." : "Equipment history — IT equipment in the custody of employees."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input data-testid="assets-search" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder={personal ? "Search my assets…" : "Search employee, asset name, tag, serial, spec…"}
              className="pl-9 pr-4 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm w-72" />
          </div>
          {!personal && (
            <select data-testid="assets-dept-filter" value={dept} onChange={(e) => setDept(e.target.value)}
              className="py-2.5 px-3 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm">
              <option value="">All departments</option>
              {departments.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          )}
          {canAddExisting && (
            <button onClick={() => setAddOpen(true)} data-testid="btn-add-existing"
              className="px-4 py-2.5 rounded-lg border border-amber-600 text-amber-700 hover:bg-amber-50 font-semibold text-sm flex items-center gap-2 transition-colors">
              <Plus size={16} /> Add Existing Asset
            </button>
          )}
          {!personal && (
            <button onClick={() => window.open(withAuthParam(`${API}/assets/summary/pdf`), "_blank")} data-testid="btn-download-summary"
              className="px-4 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 transition-colors">
              <FileDown size={16} /> Download Summary Report
            </button>
          )}
        </div>
      </div>

      {!personal && (
        <div className="flex flex-wrap gap-3 text-sm">
          <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-100 text-slate-700">
            <Users size={14} /> <b>{filtered.length}</b> employee(s)
          </span>
          <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-50 text-amber-700">
            <Laptop size={14} /> <b>{totalDevices}</b> device(s) assigned
          </span>
          {searching && matchedDevices > 0 && (
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 text-emerald-700" data-testid="search-match-count">
              <Search size={14} /> <b>{matchedDevices}</b> matching device(s) highlighted
            </span>
          )}
          {searching && !autoOpen && filtered.length > 25 && (
            <span className="inline-flex items-center px-3 py-1.5 text-xs text-slate-500">Narrow the search to open rows automatically</span>
          )}
        </div>
      )}

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
        <table className="w-full text-sm" data-testid="assigned-table">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-100">
              <th className="px-5 py-3 w-10"></th>
              <th className="px-3 py-3">Employee</th>
              <th className="px-3 py-3">Department</th>
              <th className="px-3 py-3">Products</th>
              <th className="px-3 py-3 text-right pr-6">Devices</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr data-testid="assigned-empty">
                <td colSpan={5} className="py-12 text-center text-slate-400">
                  <PackageOpen size={30} className="mx-auto mb-2 opacity-50" />
                  {personal ? "No assets currently assigned to you." : "No assigned assets found. Assign assets via the Handover module."}
                </td>
              </tr>
            )}
            {rows.map((e) => {
              const isOpen = isRowOpen(e.name);
              return (
                <Fragment key={e.name}>
                  <tr onClick={() => toggle(e.name)} data-testid={`assigned-row-${e.name}`}
                    className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer">
                    <td className="px-5 py-3 text-slate-400">{isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-semibold">{initials(e.name)}</div>
                        <div>
                          <div className="font-semibold text-slate-900">{e.name}</div>
                          {e.email && <div className="text-xs text-slate-400">{e.email}</div>}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3 text-slate-700">{e.department}</td>
                    <td className="px-3 py-3 text-slate-600">{productSummary(e.devices)}</td>
                    <td className="px-3 py-3 pr-6 text-right">
                      <span className="inline-flex min-w-[28px] justify-center px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-xs font-semibold">{e.devices.length}</span>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="bg-slate-50/60 border-b border-slate-100">
                      <td></td>
                      <td colSpan={4} className="px-3 py-3">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-left text-[10px] uppercase tracking-wider text-slate-400">
                              <th className="py-1.5 pr-3">Product</th>
                              <th className="py-1.5 pr-3">Specification</th>
                              <th className="py-1.5 pr-3">Category</th>
                              <th className="py-1.5 pr-3">Tag ID</th>
                              <th className="py-1.5 pr-3">Serial No</th>
                              <th className="py-1.5 pr-3">Handover Slip</th>
                              <th className="py-1.5 pr-3">Assigned On</th>
                              {canAddExisting && <th className="py-1.5">Form photo</th>}
                            </tr>
                          </thead>
                          <tbody>
                            {e.devices.map((d) => (
                              <tr key={d.id} className={`border-t border-slate-200/70 ${deviceMatches(d) ? "bg-amber-100/70" : ""}`} data-testid={`asset-row-${d.id}`}>
                                <td className="py-2 pr-3 font-medium text-slate-800">{d.name}{d.brand ? <span className="text-slate-400 font-normal"> · {d.brand}</span> : null}</td>
                                <td className="py-2 pr-3 text-slate-600 max-w-[260px]">{d.specification || "—"}</td>
                                <td className="py-2 pr-3 text-slate-600">{d.category_name || "—"}</td>
                                <td className="py-2 pr-3 font-mono text-amber-700">{d.tag_id || "—"}</td>
                                <td className="py-2 pr-3 font-mono text-slate-600">{d.serial_no || "—"}</td>
                                <td className="py-2 pr-3 font-mono text-slate-600">{d.assigned_slip_no || "—"}</td>
                                <td className="py-2 pr-3 text-slate-600">{fmtDate(d.assigned_at || d.receipt_confirmed_at)}</td>
                                {canAddExisting && (
                                  <td className="py-2" data-testid={`asset-forms-${d.id}`}>
                                    <div className="flex flex-wrap items-center gap-1.5">
                                      <FormChips records={paperMap.by_asset[d.id]} assetId={d.id} onChanged={loadForms} />
                                      <button onClick={() => setAttachFor(d)} title="Add a photo of the paper form"
                                        className="w-7 h-7 rounded-md border border-dashed border-slate-300 text-slate-400 hover:text-amber-600 hover:border-amber-400 flex items-center justify-center" data-testid={`btn-add-photo-${d.id}`}>
                                        <Plus size={14} />
                                      </button>
                                    </div>
                                  </td>
                                )}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {canAddExisting && (paperMap.by_employee[e.devices[0]?.assigned_to_user_id] || []).length > 0 && (
                          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                            <span className="font-semibold uppercase tracking-wider text-[10px] text-slate-400">Other forms for {e.name}:</span>
                            <FormChips records={paperMap.by_employee[e.devices[0]?.assigned_to_user_id]} onChanged={loadForms} />
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>

        {pages > 1 && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-100 text-xs text-slate-500">
            <span>Page {page} of {pages}</span>
            <div className="flex gap-2">
              <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="px-3 py-1.5 rounded border border-slate-300 disabled:opacity-40">Previous</button>
              <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded border border-slate-300 disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </div>
      <AddExistingDialog open={addOpen} onOpenChange={setAddOpen} />
      {canAddExisting && <AttachPhotoDialog device={attachFor} onClose={() => setAttachFor(null)} onSaved={loadForms} />}
    </div>
  );
}