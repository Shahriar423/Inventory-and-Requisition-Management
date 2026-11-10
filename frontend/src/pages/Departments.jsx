import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, Building2 } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";

export default function Departments() {
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", code: "", description: "" });

  const load = useCallback(async () => {
    const { data } = await api.get("/departments");
    setRows(data);
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const openNew = () => { setEditing(null); setForm({ name: "", code: "", description: "" }); setOpen(true); };
  const openEdit = (d) => { setEditing(d); setForm({ name: d.name, code: d.code || "", description: d.description || "" }); setOpen(true); };

  const save = async () => {
    try {
      if (editing) { await api.put(`/departments/${editing.id}`, form); toast.success("Department updated"); }
      else { await api.post("/departments", form); toast.success("Department created"); }
      setOpen(false); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const del = async (d) => {
    if (!window.confirm(`Delete ${d.name}?`)) return;
    try { await api.delete(`/departments/${d.id}`); toast.success("Deleted"); load(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  return (
    <div className="space-y-6" data-testid="departments-page">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">Departments</h2>
          <p className="text-slate-500 text-sm mt-1">Organizational units and hierarchy.</p>
        </div>
        <button onClick={openNew} data-testid="btn-new-dept" className="px-4 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 transition-colors"><Plus size={16} /> New Department</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {rows.map((d) => (
          <div key={d.id} className="bg-white rounded-xl border border-slate-200 shadow-sm p-5" data-testid={`dept-card-${d.name}`}>
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center"><Building2 size={18} /></div>
                <div>
                  <div className="font-head font-semibold text-slate-900">{d.name}</div>
                  <div className="font-mono text-xs text-slate-400">{d.code || "—"}</div>
                </div>
              </div>
              <div className="flex gap-1.5">
                <button onClick={() => openEdit(d)} data-testid={`btn-edit-dept-${d.name}`} className="text-amber-600 hover:text-amber-800"><Pencil size={15} /></button>
                <button onClick={() => del(d)} data-testid={`btn-delete-dept-${d.name}`} className="text-red-500 hover:text-red-700"><Trash2 size={15} /></button>
              </div>
            </div>
            <p className="text-sm text-slate-500 mt-3">{d.description || "No description"}</p>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="dept-dialog">
          <DialogHeader><DialogTitle>{editing ? "Edit Department" : "New Department"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <input placeholder="Name" data-testid="dept-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp2" />
            <input placeholder="Code (e.g. IT)" data-testid="dept-code-input" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} className="inp2" />
            <textarea placeholder="Description" data-testid="dept-desc-input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="inp2" rows={3} />
          </div>
          <DialogFooter>
            <button onClick={() => setOpen(false)} className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 font-semibold text-sm">Cancel</button>
            <button onClick={save} data-testid="btn-save-dept" className="px-4 py-2 rounded-lg bg-amber-600 text-white font-semibold text-sm hover:bg-amber-700">Save</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <style>{`.inp2{width:100%;padding:0.55rem 0.75rem;border:1px solid #cbd5e1;border-radius:0.5rem;font-size:0.875rem;outline:none}.inp2:focus{border-color:#d97706}`}</style>
    </div>
  );
}
