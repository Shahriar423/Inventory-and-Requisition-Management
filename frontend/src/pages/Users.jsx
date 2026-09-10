import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2 } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

const EMPTY = { name: "", email: "", password: "", department_id: "", role: "executive", role_label: "", can_raise_pr: false };

export default function Users() {
  const [users, setUsers] = useState([]);
  const [depts, setDepts] = useState([]);
  const [roles, setRoles] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const load = useCallback(async () => {
    const [u, d, r] = await Promise.all([
      api.get("/users"), api.get("/departments"), api.get("/meta/roles"),
    ]);
    setUsers(u.data); setDepts(d.data); setRoles(r.data.roles);
  }, []);

  useEffect(() => { load().catch(() => {}); }, [load]);

  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };
  const openEdit = (u) => {
    setEditing(u);
    setForm({ name: u.name, email: u.email, password: "", department_id: u.department_id || "", role: u.role, role_label: u.role_label || "", can_raise_pr: !!u.can_raise_pr });
    setOpen(true);
  };

  const save = async () => {
    try {
      const payload = { ...form };
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

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
              <th className="px-6 py-3 font-semibold">Name</th>
              <th className="px-6 py-3 font-semibold">Email</th>
              <th className="px-6 py-3 font-semibold">Department</th>
              <th className="px-6 py-3 font-semibold">Role</th>
              <th className="px-6 py-3 font-semibold">Can Raise PR</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`user-row-${u.email}`}>
                <td className="px-6 py-3 font-medium text-slate-800">{u.name}</td>
                <td className="px-6 py-3 text-slate-600">{u.email}</td>
                <td className="px-6 py-3 text-amber-700">{u.department_name || "—"}</td>
                <td className="px-6 py-3 text-slate-700">{u.role_label_display}</td>
                <td className="px-6 py-3">
                  {u.can_raise_pr
                    ? <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">Yes</span>
                    : <span className="text-slate-300">—</span>}
                </td>
                <td className="px-6 py-3">
                  <div className="flex items-center justify-end gap-2">
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

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="user-dialog">
          <DialogHeader><DialogTitle>{editing ? "Edit User" : "New User"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Field label="Name"><input data-testid="user-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp" /></Field>
            <Field label="Email"><input data-testid="user-email-input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="inp" /></Field>
            <Field label={editing ? "Password (leave blank to keep)" : "Password"}><input data-testid="user-password-input" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="inp" placeholder={editing ? "••••••" : "default: password123"} /></Field>
            <Field label="Department">
              <select data-testid="user-dept-select" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} className="inp">
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
            <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" data-testid="user-can-raise-pr" checked={form.can_raise_pr} onChange={(e) => setForm({ ...form, can_raise_pr: e.target.checked })} className="w-4 h-4 accent-amber-600" />
              Can Raise PR (create requisitions)
            </label>
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
