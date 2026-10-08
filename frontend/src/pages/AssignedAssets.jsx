import { Fragment, useEffect, useMemo, useState } from "react";
import { Search, FileDown, ChevronRight, ChevronDown, PackageOpen, Users, Laptop, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import api, { API, withAuthParam, onDataRefresh, requestDataRefresh, formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";

const PAGE_SIZE = 15;

const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? "—" : d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
};

const initials = (name = "") =>
  name.split(" ").filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";

const blankDevice = () => ({ name: "", brand: "", category_id: "", tag_id: "", serial_no: "", assigned_date: "" });

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
  const canAddExisting =
    user?.role === "super_admin" ||
    (user?.role === "dept_head" && (user?.department_name === "IT" || user?.department_code === "IT"));

  useEffect(() => {
    const load = () => api.get("/assets").then(({ data }) => setAssets(data)).catch(() => {});
    load();
    return onDataRefresh(load);
  }, []);

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

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    return employees.filter((e) => {
      if (dept && e.department !== dept) return false;
      if (!term) return true;
      const text = [
        e.name, e.email, e.department,
        ...e.devices.flatMap((d) => [d.name, d.serial_no, d.tag_id, d.category_name, d.assigned_slip_no]),
      ].filter(Boolean).join(" ").toLowerCase();
      return text.includes(term);
    });
  }, [employees, q, dept]);

  useEffect(() => { setPage(1); }, [q, dept]);

  const totalDevices = filtered.reduce((n, e) => n + e.devices.length, 0);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const rows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const toggle = (name) => setOpen((o) => ({ ...o, [name]: !o[name] }));

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
              placeholder={personal ? "Search my assets…" : "Search employee, product, tag / serial…"}
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
              const isOpen = !!open[e.name];
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
                              <th className="py-1.5 pr-3">Category</th>
                              <th className="py-1.5 pr-3">Tag ID</th>
                              <th className="py-1.5 pr-3">Serial No</th>
                              <th className="py-1.5 pr-3">Handover Slip</th>
                              <th className="py-1.5">Assigned On</th>
                            </tr>
                          </thead>
                          <tbody>
                            {e.devices.map((d) => (
                              <tr key={d.id} className="border-t border-slate-200/70" data-testid={`asset-row-${d.id}`}>
                                <td className="py-2 pr-3 font-medium text-slate-800">{d.name}{d.brand ? <span className="text-slate-400 font-normal"> · {d.brand}</span> : null}</td>
                                <td className="py-2 pr-3 text-slate-600">{d.category_name || "—"}</td>
                                <td className="py-2 pr-3 font-mono text-amber-700">{d.tag_id || "—"}</td>
                                <td className="py-2 pr-3 font-mono text-slate-600">{d.serial_no || "—"}</td>
                                <td className="py-2 pr-3 font-mono text-slate-600">{d.assigned_slip_no || "—"}</td>
                                <td className="py-2 text-slate-600">{fmtDate(d.assigned_at || d.receipt_confirmed_at)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
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
    </div>
  );
}