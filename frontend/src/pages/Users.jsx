import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, KeyRound, Copy, Check } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

const EMPTY = { name: "", email: "", password: "", department_id: "", role: "executive", role_label: "", can_raise_pr: false, can_create_po: false, it_team: "" };
const IT_TEAM_OPTIONS = [["Application", "Application"], ["Network_Infra", "Network & Infra"]];

export default function Users() {
  const [users, setUsers] = useState([]);
  const [depts, setDepts] = useState([]);
  const [roles, setRoles] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const { user: me } = useAuth();
  const [resetFor, setResetFor] = useState(null);       // user being reset (confirm dialog)
  const [resetting, setResetting] = useState(false);
  const [tempPw, setTempPw] = useState(null);           // { name, email, password } shown once
  const [copied, setCopied] = useState(false);

  const doReset = async () => {
    setResetting(true);
    try {
      const { data } = await api.post(`/users/${resetFor.id}/reset-password`, {});
      setTempPw({ name: resetFor.name, email: resetFor.email, password: data.temporary_password });
      setResetFor(null);
      setCopied(false);
      load().catch(() => {});
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Could not reset password");
    } finally {
      setResetting(false);
    }
  };
  const copyTemp = async () => {
    try { await navigator.clipboard.writeText(tempPw.password); setCopied(true); } catch (e) { toast.error("Copy failed - select and copy it manually"); }
  };

  const load = useCallback(async () => {
    const [u, d, r] = await Promise.all([
      api.get("/users"), api.get("/departments"), api.get("/meta/roles"),
    ]);
    setUsers(u.data); setDepts(d.data); setRoles(r.data.roles);
  }, []);

  useEffect(() => { load().catch(() => {}); }, [load]);

  // "Can Raise PR" only ever applies to the IT department, and "Can Create PO" only ever
  // applies to the Purchase department — neither is a role-wide setting. Hide each
  // checkbox for any other department, and clear it automatically if the department is
  // changed away from its matching department while editing.
  const itDeptId = depts.find((d) => d.name === "IT")?.id;
  const purchaseDeptId = depts.find((d) => d.name === "Purchase")?.id;
  const selectedIsIT = !!itDeptId && form.department_id === itDeptId;
  const selectedIsPurchase = !!purchaseDeptId && form.department_id === purchaseDeptId;

  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };
  const openEdit = (u) => {
    setEditing(u);
    setForm({ name: u.name, email: u.email, password: "", department_id: u.department_id || "", role: u.role, role_label: u.role_label || "", can_raise_pr: !!u.can_raise_pr, can_create_po: !!u.can_create_po, it_team: u.it_team || "" });
    setOpen(true);
  };

  const setDepartment = (department_id) => {
    const isIT = !!itDeptId && department_id === itDeptId;
    const isPurchase = !!purchaseDeptId && department_id === purchaseDeptId;
    setForm((f) => ({ ...f, department_id, can_raise_pr: isIT ? f.can_raise_pr : false, can_create_po: isPurchase ? f.can_create_po : false, it_team: isIT ? f.it_team : "" }));
  };

  const save = async () => {
    try {
      const payload = { ...form, it_team: form.it_team || null };   // null clears the sub-team
      if (!payload.department_id) delete payload.department_id;
      if (editing) {
        if (!payload.password) delete payload.password;
        await api.put(`/users/${editing.id}`, payload);
        toast.success("User updated");
      } else {
        await api.post("/users", payload);
        toast.success("User created");
      }
      setOpen(false);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  const del = async (u) => {
    if (!window.confirm(`Delete ${u.name}?`)) return;
    try {
      await api.delete(`/users/${u.id}`);
      toast.success("User deleted");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  return (
    <div className="space-y-6" data-testid="users-page">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">Users &amp; Roles</h2>
          <p className="text-slate-500 text-sm mt-1">Everyone with access to the system.</p>
        </div>
        <button onClick={openNew} data-testid="btn-new-user"
          className="px-4 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 transition-colors"><Plus size={16} /> New User</button>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
              <th className="px-6 py-3 font-semibold">Name</th>
              <th className="px-6 py-3 font-semibold">Email</th>
              <th className="px-6 py-3 font-semibold">Department</th>
              <th className="px-6 py-3 font-semibold">Role</th>
              <th className="px-6 py-3 font-semibold">Can Raise PR</th>
              <th className="px-6 py-3 font-semibold">Can Create PO</th>
              <th className="px-6 py-3 font-semibold">IT Team</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`user-row-${u.email}`}>
                <td className="px-6 py-3 font-medium text-slate-800">{u.name}
                  {u.must_change_password && <span className="ml-2 px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-[10px] font-semibold align-middle" title="Has a temporary password and must change it at next login">Temp password</span>}
                </td>
                <td className="px-6 py-3 text-slate-600">{u.email}</td>
                <td className="px-6 py-3 text-amber-700">{u.department_name || "—"}</td>
                <td className="px-6 py-3 text-slate-700">{u.role_label_display}</td>
                <td className="px-6 py-3">
                  {u.can_raise_pr
                    ? <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">Yes</span>
                    : <span className="text-slate-300">—</span>}
                </td>
                <td className="px-6 py-3">
                  {u.can_create_po
                    ? <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">Yes</span>
                    : <span className="text-slate-300">—</span>}
                </td>
                <td className="px-6 py-3" data-testid={`user-it-team-${u.email}`}>
                  {u.it_team
                    ? <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-700">{u.it_team === "Network_Infra" ? "Network & Infra" : u.it_team}</span>
                    : <span className="text-slate-300">—</span>}
                </td>
                <td className="px-6 py-3">
                  <div className="flex items-center justify-end gap-2">
                    {u.id !== me?.id && (
                      <button onClick={() => setResetFor(u)} data-testid={`btn-reset-password-${u.email}`}
                        className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-700 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"><KeyRound size={13} /> Reset password</button>
                    )}
                    <button onClick={() => openEdit(u)} data-testid={`btn-edit-user-${u.email}`}
                      className="px-3 py-1.5 rounded-lg border border-amber-300 text-amber-700 text-xs font-semibold hover:bg-amber-50 flex items-center gap-1.5 transition-colors"><Pencil size={13} /> Edit</button>
                    <button onClick={() => del(u)} data-testid={`btn-delete-user-${u.email}`}
                      className="px-3 py-1.5 rounded-lg border border-red-300 text-red-600 text-xs font-semibold hover:bg-red-50 flex items-center gap-1.5 transition-colors"><Trash2 size={13} /> Delete</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!resetFor} onOpenChange={(v) => { if (!v) setResetFor(null); }}>
        <DialogContent data-testid="reset-confirm-dialog">
          <DialogHeader><DialogTitle>Reset password?</DialogTitle></DialogHeader>
          <p className="text-sm text-slate-600">
            A temporary password will be created for <b>{resetFor?.name}</b> ({resetFor?.email}). They will be signed out
            everywhere and must choose a new password at their next login.
          </p>
          <DialogFooter>
            <button onClick={() => setResetFor(null)} className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 font-semibold text-sm">Cancel</button>
            <button onClick={doReset} disabled={resetting} data-testid="btn-confirm-reset"
              className="px-4 py-2 rounded-lg bg-amber-600 text-white font-semibold text-sm hover:bg-amber-700 transition-colors disabled:opacity-60">{resetting ? "Resetting…" : "Reset password"}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!tempPw} onOpenChange={(v) => { if (!v) setTempPw(null); }}>
        <DialogContent data-testid="temp-password-dialog">
          <DialogHeader><DialogTitle>Temporary password</DialogTitle></DialogHeader>
          <p className="text-sm text-slate-600">Give this to <b>{tempPw?.name}</b> ({tempPw?.email}) in person or by phone. It is shown only once.</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-4 py-3 rounded-lg bg-slate-100 border border-slate-200 font-mono text-lg tracking-wider select-all" data-testid="temp-password-value">{tempPw?.password}</code>
            <button onClick={copyTemp} className="px-3 py-3 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50" aria-label="Copy password">{copied ? <Check size={18} /> : <Copy size={18} />}</button>
          </div>
          <p className="text-xs text-slate-500">They will be asked to set their own password the first time they sign in.</p>
          <DialogFooter>
            <button onClick={() => setTempPw(null)} className="px-4 py-2 rounded-lg bg-amber-600 text-white font-semibold text-sm hover:bg-amber-700 transition-colors">Done</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="user-dialog">
          <DialogHeader><DialogTitle>{editing ? "Edit User" : "New User"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Field label="Name"><input data-testid="user-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp" /></Field>
            <Field label="Email"><input data-testid="user-email-input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="inp" /></Field>
            <Field label={editing ? "Password (leave blank to keep)" : "Password"}><input data-testid="user-password-input" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="inp" placeholder={editing ? "••••••" : "default: password123"} /></Field>
            <Field label="Department">
              <select data-testid="user-dept-select" value={form.department_id} onChange={(e) => setDepartment(e.target.value)} className="inp">
                <option value="">—</option>
                {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
            <Field label="Role">
              <select data-testid="user-role-select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="inp">
                {roles.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </Field>
            <Field label="Role Label (display, optional)"><input data-testid="user-role-label-input" value={form.role_label} onChange={(e) => setForm({ ...form, role_label: e.target.value })} className="inp" placeholder="e.g. Executive(IT)" /></Field>
            {selectedIsIT && (
              <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                <input type="checkbox" data-testid="user-can-raise-pr" checked={form.can_raise_pr} onChange={(e) => setForm({ ...form, can_raise_pr: e.target.checked })} className="w-4 h-4 accent-amber-600" />
                Can Raise PR (create Purchase Requisitions)
              </label>
            )}
            {selectedIsIT && (
              <Field label="IT Team (optional)">
                <select data-testid="user-it-team-select" value={form.it_team} onChange={(e) => setForm({ ...form, it_team: e.target.value })} className="inp">
                  <option value="">— none —</option>
                  {IT_TEAM_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <p className="text-xs text-slate-400 mt-1">Decides which IT service ticket queue an Executive sees. The role stays Executive.</p>
              </Field>
            )}
            {!selectedIsIT && form.department_id && (
              <p className="text-xs text-slate-400">Can Raise PR is only available for users in the IT department.</p>
            )}
            {selectedIsPurchase && (
              <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                <input type="checkbox" data-testid="user-can-create-po" checked={form.can_create_po} onChange={(e) => setForm({ ...form, can_create_po: e.target.checked })} className="w-4 h-4 accent-amber-600" />
                Can Create PO (create &amp; submit Purchase Orders)
              </label>
            )}
            {!selectedIsPurchase && form.department_id && (
              <p className="text-xs text-slate-400">Can Create PO is only available for users in the Purchase department.</p>
            )}
          </div>
          <DialogFooter>
            <button onClick={() => setOpen(false)} className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 font-semibold text-sm">Cancel</button>
            <button onClick={save} data-testid="btn-save-user" className="px-4 py-2 rounded-lg bg-amber-600 text-white font-semibold text-sm hover:bg-amber-700 transition-colors">Save</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <style>{`.inp{width:100%;padding:0.55rem 0.75rem;border:1px solid #cbd5e1;border-radius:0.5rem;font-size:0.875rem;outline:none}.inp:focus{border-color:#d97706}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">{label}</label>
      {children}
    </div>
  );
}