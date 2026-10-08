import { useState } from "react";
import { LogOut, Menu, KeyRound, ChevronDown } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import NotificationBell from "@/components/NotificationBell";
import DelegationDialog from "@/components/DelegationDialog";
import ChangePasswordDialog from "@/components/ChangePasswordDialog";
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

function initials(name) {
  return (name || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export default function Header({ title, onMenuClick, navOpen }) {
  const { user, logout } = useAuth();
  const [pwOpen, setPwOpen] = useState(false);

  return (
    <header className="h-16 sticky top-0 z-20 bg-white border-b border-slate-200 flex items-center justify-between px-6" data-testid="app-header">
      <div className="flex items-center gap-3 min-w-0">
        <button
          type="button"
          onClick={onMenuClick}
          aria-label="Toggle navigation menu"
          aria-expanded={!!navOpen}
          aria-controls="app-sidebar"
          data-testid="menu-toggle"
          className="w-10 h-10 -ml-2 rounded-lg flex items-center justify-center text-slate-600 hover:text-slate-900 hover:bg-slate-100 active:bg-slate-200 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
        >
          <Menu size={22} />
        </button>
        <h1 className="font-head font-semibold text-slate-900 text-lg truncate" data-testid="page-title">{title}</h1>
      </div>

      <div className="flex items-center gap-5">
        <DelegationDialog />
        <NotificationBell />

        {/* Profile menu — name, role, and account actions in one clean place */}
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              data-testid="profile-menu-btn"
              className="flex items-center gap-3 pl-5 border-l border-slate-200 py-1 pr-2 rounded-lg hover:bg-slate-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
            >
              <div className="w-10 h-10 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center font-semibold text-sm" data-testid="user-avatar">
                {initials(user?.name)}
              </div>
              <div className="text-left leading-tight hidden sm:block">
                <div className="text-sm font-semibold text-slate-900" data-testid="user-name">{user?.name}</div>
                <div className="text-xs text-slate-500" data-testid="user-role">{user?.role_label_display}</div>
              </div>
              <ChevronDown size={16} className="text-slate-400 hidden sm:block" />
            </button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" sideOffset={8} className="w-72 p-0 overflow-hidden" data-testid="profile-menu">
            <div className="px-4 py-3.5 bg-slate-50 border-b border-slate-200">
              <div className="text-sm font-semibold text-slate-900 truncate">{user?.name}</div>
              <div className="text-xs text-slate-500 truncate">{user?.email}</div>
              <div className="text-xs text-slate-500 mt-0.5 truncate">
                {[user?.role_label_display, user?.department_name].filter(Boolean).join(" · ")}
              </div>
            </div>
            <div className="p-1.5">
              <DropdownMenuItem
                onSelect={() => setPwOpen(true)}
                data-testid="change-password-btn"
                className="gap-3 px-3 py-2.5 text-sm cursor-pointer rounded-md"
              >
                <KeyRound size={17} className="text-slate-500" />
                <span className="font-medium text-slate-700">Change your password</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={logout}
                data-testid="logout-btn"
                className="gap-3 px-3 py-2.5 text-sm cursor-pointer rounded-md focus:bg-red-50"
              >
                <LogOut size={17} className="text-red-500" />
                <span className="font-medium text-red-600">Sign out</span>
              </DropdownMenuItem>
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <ChangePasswordDialog open={pwOpen} onOpenChange={setPwOpen} />
    </header>
  );
}