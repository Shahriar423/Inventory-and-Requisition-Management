import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard, ClipboardList, Boxes, ShoppingCart, Handshake,
  UserCheck, Building2, ChevronDown, Package, X,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const ICONS = { LayoutDashboard, ClipboardList, Boxes, ShoppingCart, Handshake, UserCheck, Building2 };

// Primitek Vector Logo Component
function PrimitekSidebarLogo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative flex items-center justify-center p-1 bg-white rounded-lg shadow-sm shrink-0">
        <svg width="26" height="26" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M50 5 L90 28 L90 72 L50 95 L10 72 L10 28 Z" stroke="#000000" strokeWidth="8" fill="none" />
          <path d="M50 12 L83 31 L83 69 L50 88 L17 69 L17 31 Z" stroke="#000000" strokeWidth="4" fill="none" />
          <circle cx="38" cy="38" r="7" fill="#000000" />
          <circle cx="38" cy="53" r="7" fill="#000000" />
          <circle cx="38" cy="68" r="7" fill="#000000" />
          <path d="M48 30 C 65 30, 68 50, 48 55 Z" fill="#E31E24" />
        </svg>
      </div>
      <div>
        <div className="text-white font-head font-extrabold text-base tracking-tight leading-none">
          Primi<span className="text-[#E31E24]">tek</span> Group
        </div>
        <div className="text-slate-400 text-[10px] mt-1 font-medium">Inventory &amp; Requisition</div>
      </div>
    </div>
  );
}

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

export default function Sidebar({ open = false, onClose = () => {}, isDesktop = true, width = 280 }) {
  const { menu } = useAuth();
  return (
    <>
      {/* Backdrop — PHONES ONLY (drawer mode). On desktop / tablet there is no overlay,
          tint or blur: the page stays sharp and fully interactive. */}
      {!isDesktop && (
        <div
          onClick={onClose}
          aria-hidden="true"
          data-testid="sidebar-backdrop"
          className={`fixed inset-0 z-40 bg-slate-900/50 transition-opacity duration-300 ${
            open ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        />
      )}

      {/* Pinned sidebar (desktop / tablet) or slide-over drawer (phones) */}
      <aside
        id="app-sidebar"
        aria-hidden={!open}
        data-testid="sidebar"
        style={{ width }}
        className={`fixed inset-y-0 left-0 max-w-[85vw] bg-[#070E20] flex flex-col sidebar-scroll transition-transform duration-300 ease-in-out ${
          isDesktop ? "z-30 border-r border-white/10" : "z-50 shadow-2xl"
        } ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
          <PrimitekSidebarLogo />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close menu"
            data-testid="sidebar-close"
            className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4 sidebar-scroll">
          {menu.map((g) => (
            <Group key={g.group} group={g} />
          ))}
        </nav>

        <div className="px-5 py-3 border-t border-white/10 text-[11px] font-mono text-slate-500">
          IRM v1.0 · SUP
        </div>
      </aside>
    </>
  );
}