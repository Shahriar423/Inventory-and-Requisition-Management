import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard, ClipboardList, Boxes, ShoppingCart, Handshake,
  UserCheck, Building2, ChevronDown, Package,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const ICONS = { LayoutDashboard, ClipboardList, Boxes, ShoppingCart, Handshake, UserCheck, Building2 };

function Group({ group }) {
  const location = useLocation();
  const Icon = ICONS[group.icon] || Package;
  const groupActive = group.items.some((it) => location.pathname === it.path);
  const [open, setOpen] = useState(true);

  return (
    <div className="mb-1">
      <button
        data-testid={`sidebar-group-${group.group.toLowerCase()}`}
        onClick={() => setOpen((o) => !o)}
        className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-semibold transition-colors duration-150 ${
          groupActive ? "text-white" : "text-slate-300 hover:text-white hover:bg-white/5"
        }`}
      >
        <span className="flex items-center gap-3">
          <Icon size={18} className={groupActive ? "text-amber-500" : "text-slate-400"} />
          {group.group}
        </span>
        <span className="flex items-center gap-2">
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-slate-400 border border-white/10">
            {group.badge}
          </span>
          <ChevronDown size={14} className={`transition-transform duration-200 ${open ? "" : "-rotate-90"}`} />
        </span>
      </button>
      {open && (
        <div className="mt-1 ml-3 pl-4 border-l border-white/10 space-y-0.5">
          {group.items.map((it) => (
            <NavLink
              key={it.key}
              to={it.path}
              data-testid={`sidebar-link-${it.key}`}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-lg text-sm transition-colors duration-150 ${
                  isActive
                    ? "bg-amber-600 text-white font-semibold shadow-sm"
                    : "text-slate-400 hover:text-white hover:bg-white/5"
                }`
              }
            >
              {it.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Sidebar() {
  const { menu } = useAuth();
  return (
    <aside className="w-[260px] shrink-0 h-screen sticky top-0 bg-[#070E20] flex flex-col sidebar-scroll" data-testid="sidebar">
      <div className="flex items-center gap-3 px-5 py-5 border-b border-white/10">
        <div className="w-9 h-9 rounded-lg bg-amber-600 flex items-center justify-center text-white">
          <Package size={20} />
        </div>
        <div>
          <div className="text-white font-head font-bold text-lg leading-none">IMS</div>
          <div className="text-slate-400 text-[11px] mt-1">Inventory &amp; Requisition</div>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto px-3 py-4 sidebar-scroll">
        {menu.map((g) => (
          <Group key={g.group} group={g} />
        ))}
      </nav>
      <div className="px-5 py-3 border-t border-white/10 text-[11px] font-mono text-slate-500">
        IMS v1.0 · SUP
      </div>
    </aside>
  );
}
