import { Bell, LogOut } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

function initials(name) {
  return (name || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export default function Header({ title }) {
  const { user, logout } = useAuth();
  return (
    <header className="h-16 sticky top-0 z-20 bg-white border-b border-slate-200 flex items-center justify-between px-6" data-testid="app-header">
      <h1 className="font-head font-semibold text-slate-900 text-lg" data-testid="page-title">{title}</h1>
      <div className="flex items-center gap-4">
        <button className="relative text-slate-500 hover:text-slate-800 transition-colors" data-testid="notifications-btn">
          <Bell size={20} />
          <span className="absolute -top-1 -right-1 w-2 h-2 bg-amber-500 rounded-full" />
        </button>
        <div className="flex items-center gap-3 pl-4 border-l border-slate-200">
          <div className="w-9 h-9 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center font-semibold text-sm" data-testid="user-avatar">
            {initials(user?.name)}
          </div>
          <div className="text-right leading-tight hidden sm:block">
            <div className="text-sm font-semibold text-slate-900" data-testid="user-name">Signed in as {user?.name}</div>
            <div className="text-xs text-slate-500" data-testid="user-role">{user?.role_label_display}</div>
          </div>
          <button onClick={logout} className="text-slate-400 hover:text-red-600 transition-colors" data-testid="logout-btn">
            <LogOut size={18} />
          </button>
        </div>
      </div>
    </header>
  );
}
