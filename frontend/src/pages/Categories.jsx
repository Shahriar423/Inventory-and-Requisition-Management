import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, Tag } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";

export default function Categories() {
  const [rows, setRows] = useState([]);
  const [depts, setDepts] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", department_id: "", description: "" });

  const load = useCallback(async () => {
    const [c, d] = await Promise.all([api.get("/categories"), api.get("/departments")]);
    setRows(c.data); setDepts(d.data);
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const openNew = () => { setEditing(null); setForm({ name: "", department_id: "", description: "" }); setOpen(true); };
  const openEdit = (c) => { setEditing(c); setForm({ name: c.name, department_id: c.department_id || "", description: c.description || "" }); setOpen(true); };

  const save = async () => {
    try {
      const payload = { ...form };
      if (!payload.department_id) delete payload.department_id;
      if (editing) { await api.put(`/categories/${editing.id}`, payload); toast.success("Category updated"); }
      else { await api.post("/categories", payload); toast.success("Category created"); }
      setOpen(false); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const del = async (c) => {
    if (!window.confirm(`Delete ${c.name}?`)) return;
    try { await api.delete(`/categories/${c.id}`); toast.success("Deleted"); load(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  return (
    <div className="space-y-6" data-testid="categories-page">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">Categories</h2>
          <p className="text-slate-500 text-sm mt-1">Item categories grouped by department.</p>
        </div>
        <button onClick={openNew} data-testid="btn-new-category" className="px-4 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 transition-colors"><Plus size={16} /> New Category</button>
      </div>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
              <th className="px-6 py-3 font-semibold">Category</th>
              <th className="px-6 py-3 font-semibold">Department</th>
              <th className="px-6 py-3 font-semibold">Description</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`cat-row-${c.name}`}>
                <td className="px-6 py-3 font-medium text-slate-800 flex items-center gap-2"><Tag size={15} className="text-amber-600" /> {c.name}</td>
                <td className="px-6 py-3 text-amber-700">{c.department_name || "—"}</td>
                <td className="px-6 py-3 text-slate-500">{c.description || "—"}</td>
                <td className="px-6 py-3">
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={() => openEdit(c)} data-testid={`btn-edit-cat-${c.name}`} className="px-3 py-1.5 rounded-lg border border-amber-300 text-amber-700 text-xs font-semibold hover:bg-amber-50 flex items-center gap-1.5 transition-colors"><Pencil size={13} /> Edit</button>
                    <button onClick={() => del(c)} data-testid={`btn-delete-cat-${c.name}`} className="px-3 py-1.5 rounded-lg border border-red-300 text-red-600 text-xs font-semibold hover:bg-red-50 flex items-center gap-1.5 transition-colors"><Trash2 size={13} /> Delete</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="cat-dialog">
          <DialogHeader><DialogTitle>{editing ? "Edit Category" : "New Category"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <input placeholder="Name" data-testid="cat-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp3" />
            <select data-testid="cat-dept-select" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} className="inp3">
              <option value="">— Department —</option>
              {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
            <textarea placeholder="Description" data-testid="cat-desc-input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="inp3" rows={3} />
          </div>
          <DialogFooter>
            <button onClick={() => setOpen(false)} className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 font-semibold text-sm">Cancel</button>
            <button onClick={save} data-testid="btn-save-cat" className="px-4 py-2 rounded-lg bg-amber-600 text-white font-semibold text-sm hover:bg-amber-700">Save</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <style>{`.inp3{width:100%;padding:0.55rem 0.75rem;border:1px solid #cbd5e1;border-radius:0.5rem;font-size:0.875rem;outline:none}.inp3:focus{border-color:#d97706}`}</style>
    </div>
  );
}
