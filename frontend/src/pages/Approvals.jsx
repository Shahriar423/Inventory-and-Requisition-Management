import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Save, KeyRound } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";

export default function Approvals() {
  const [perms, setPerms] = useState([]);
  const [menu, setMenu] = useState([]);

  const load = useCallback(async () => {
    const [p, m] = await Promise.all([api.get("/permissions"), api.get("/meta/menu")]);
    setPerms(p.data); setMenu(m.data.menu);
  }, []);
  useEffect(() => { load().catch(() => toast.error("Only Super Admin can manage approver access")); }, [load]);

  const toggle = (role, key) => {
    setPerms((prev) => prev.map((p) => {
      if (p.role !== role) return p;
      const has = p.items.includes(key);
      return { ...p, items: has ? p.items.filter((k) => k !== key) : [...p.items, key] };
    }));
  };

  const save = async (p) => {
    try {
      await api.put(`/permissions/${p.role}`, { items: p.items });
      toast.success(`${p.label} menu access saved`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  return (
    <div className="space-y-6" data-testid="approvals-page">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">Approver Management</h2>
        <p className="text-slate-500 text-sm mt-1">Control which sidebar menus each role can access.</p>
      </div>

      <div className="space-y-4">
        {perms.map((p) => (
          <div key={p.role} className="bg-white rounded-xl border border-slate-200 shadow-sm p-5" data-testid={`perm-role-${p.role}`}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2 font-head font-semibold text-slate-900"><KeyRound size={16} className="text-amber-600" /> {p.label}</div>
              <button onClick={() => save(p)} data-testid={`btn-save-perm-${p.role}`} className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-xs font-semibold flex items-center gap-1.5 hover:bg-amber-700 transition-colors"><Save size={13} /> Save</button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-2">
              {menu.flatMap((g) => g.items).map((it) => (
                <label key={it.key} className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                  <input type="checkbox" checked={p.items.includes(it.key)} onChange={() => toggle(p.role, it.key)}
                    data-testid={`perm-${p.role}-${it.key}`} disabled={p.role === "super_admin"} className="w-4 h-4 accent-amber-600" />
                  {it.label}
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
