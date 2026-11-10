import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Users as UsersIcon, ToggleLeft, ToggleRight } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";

/**
 * My Team – scoped permission management for Department Heads.
 * Purchase Dept Head → toggle can_create_po for Purchase members.
 * IT Dept Head → toggle can_raise_pr for IT members.
 * Super Admin can also use this view.
 */
export default function MyTeam() {
  const { user } = useAuth();
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);

  const isPurchaseHead =
    user?.role === "dept_head" &&
    (user?.department_name === "Purchase" || user?.department_code === "PUR");
  const isItHead =
    user?.role === "dept_head" &&
    (user?.department_name === "IT" || user?.department_code === "IT");
  const isSuper = user?.role === "super_admin";

  const flagKey = isPurchaseHead || (isSuper && user?.department_name === "Purchase")
    ? "can_create_po"
    : "can_raise_pr";
  const flagLabel = flagKey === "can_create_po" ? "Can Create PO" : "Can Raise PR";
  const deptLabel = isPurchaseHead || flagKey === "can_create_po" ? "Purchase" : "IT";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/users?scope=my_team");
      setMembers(data || []);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not load team");
      setMembers([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = async (member) => {
    const next = !member[flagKey];
    try {
      await api.patch(`/users/${member.id}/permissions`, { [flagKey]: next });
      setMembers((list) =>
        list.map((u) => (u.id === member.id ? { ...u, [flagKey]: next } : u))
      );
      toast.success(`${member.name}: ${flagLabel} set to ${next ? "ON" : "OFF"}`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  if (!isPurchaseHead && !isItHead && !isSuper) {
    return (
      <div className="py-16 text-center text-slate-500">
        Only Department Heads (IT / Purchase) or Super Admin can manage My Team permissions.
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="my-team-page">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center">
          <UsersIcon size={20} className="text-amber-700" />
        </div>
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">My Team</h2>
          <p className="text-slate-500 text-sm mt-0.5">
            {deptLabel} Department – toggle <strong>{flagLabel}</strong> for active members.
            Changes apply instantly (no Super Admin approval required).
          </p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
        {loading ? (
          <div className="py-12 text-center text-slate-400">Loading team…</div>
        ) : members.length === 0 ? (
          <div className="py-12 text-center text-slate-400">No team members found.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
                <th className="px-6 py-3 font-semibold">Name</th>
                <th className="px-6 py-3 font-semibold">Email</th>
                <th className="px-6 py-3 font-semibold">Role</th>
                <th className="px-6 py-3 font-semibold">{flagLabel}</th>
                <th className="px-6 py-3 font-semibold text-right">Toggle</th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr
                  key={m.id}
                  className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors"
                  data-testid={`team-row-${m.email}`}
                >
                  <td className="px-6 py-3 font-medium text-slate-800">{m.name}</td>
                  <td className="px-6 py-3 text-slate-600">{m.email}</td>
                  <td className="px-6 py-3 text-slate-700">{m.role_label_display || m.role_label || m.role}</td>
                  <td className="px-6 py-3">
                    {m[flagKey] ? (
                      <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">ON</span>
                    ) : (
                      <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-500">OFF</span>
                    )}
                  </td>
                  <td className="px-6 py-3 text-right">
                    <button
                      onClick={() => toggle(m)}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                        m[flagKey]
                          ? "bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100"
                          : "bg-slate-50 text-slate-600 border border-slate-200 hover:bg-slate-100"
                      }`}
                      data-testid={`btn-toggle-${flagKey}-${m.email}`}
                    >
                      {m[flagKey] ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
                      {m[flagKey] ? "Turn Off" : "Turn On"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}