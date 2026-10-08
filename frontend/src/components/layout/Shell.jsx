import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import Sidebar from "@/components/layout/Sidebar";
import ErrorBoundary from "@/components/ErrorBoundary";
import Header from "@/components/layout/Header";
import { useAuth } from "@/context/AuthContext";
import ChangePasswordDialog from "@/components/ChangePasswordDialog";

const TITLES = {
  "/dashboard": "Dashboard",
  "/assigned-assets": "Assigned Assets",
  "/requisitions/new": "New Requisition",
  "/requisitions/approve": "Approve Requisition",
  "/requisitions/history": "Requisition History",
  "/stock": "Stock List",
  "/purchase/grn": "Stock GRN",
  "/handover": "Handover",
  "/handover/records": "Handover Records",
  "/approvals": "Approver Management",
  "/organization/departments": "Departments",
  "/organization/categories": "Categories",
  "/organization/products": "Products",
  "/organization/users": "Users & Roles",
  "/requisitions/purchase": "File Purchase Requisition",
  "/requisitions/purchase-order": "File Purchase Order",
  "/purchase/my-orders": "My Purchase Orders",
};

const SIDEBAR_W = 280;                       // px — keep in sync with Sidebar.jsx
const DESKTOP_Q = "(min-width: 768px)";      // tablet and up: pinned push layout. Below: drawer.
const NAV_KEY = "ims_sidebar_open";

function useIsDesktop() {
  const [match, setMatch] = useState(() => window.matchMedia(DESKTOP_Q).matches);
  useEffect(() => {
    const mq = window.matchMedia(DESKTOP_Q);
    const onChange = (e) => setMatch(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return match;
}

export default function Shell() {
  const { user, menu } = useAuth();
  const location = useLocation();
  const isDesktop = useIsDesktop();

  // Desktop / tablet: the sidebar is PINNED — open by default, stays exactly as the user
  // left it (remembered across reloads) until they click the hamburger or the X.
  // Navigating or clicking the page never closes it.
  const [desktopOpen, setDesktopOpen] = useState(() => {
    try { return localStorage.getItem(NAV_KEY) !== "0"; } catch (e) { return true; }
  });
  useEffect(() => {
    try { localStorage.setItem(NAV_KEY, desktopOpen ? "1" : "0"); } catch (e) { /* ignore */ }
  }, [desktopOpen]);

  // Phones: normal slide-over drawer, closed by default, closes after navigating / Esc.
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") setMobileOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const navOpen = isDesktop ? desktopOpen : mobileOpen;
  const toggleNav = () => (isDesktop ? setDesktopOpen((o) => !o) : setMobileOpen((o) => !o));
  const closeNav = () => (isDesktop ? setDesktopOpen(false) : setMobileOpen(false));

  if (user === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#070E20] text-slate-300">
        <div className="animate-pulse">Loading workspace…</div>
      </div>
    );
  }
  if (user === false) return <Navigate to="/login" replace />;
  // Password was reset by an admin: nothing else is usable until the user sets their own.
  if (user.must_change_password) {
    return (
      <div className="min-h-screen app-canvas">
        <ChangePasswordDialog open forced onOpenChange={() => {}} />
      </div>
    );
  }

  // The sidebar label wins (e.g. "Delegated Approvals" for someone approving on leave cover).
  const menuLabel = (menu || []).flatMap((g) => g.items || []).find((i) => i.path === location.pathname)?.label;
  const title = menuLabel || TITLES[location.pathname] || "Primitek Group";
  return (
    <div className="flex min-h-screen app-canvas">
      <Sidebar open={navOpen} onClose={closeNav} isDesktop={isDesktop} width={SIDEBAR_W} />
      {/* Push layout: the content shifts right by the sidebar width (and back) with a smooth
          transition — it is never dimmed, blurred or covered on desktop / tablet. */}
      <div
        className="flex-1 flex flex-col min-w-0 transition-[margin] duration-300 ease-in-out"
        style={{ marginLeft: isDesktop && navOpen ? SIDEBAR_W : 0 }}
        data-testid="app-content"
      >
        <Header title={title} navOpen={navOpen} onMenuClick={toggleNav} />
        <main className="flex-1 p-4 sm:p-6 lg:px-8 lg:py-7 overflow-x-hidden">
          <div className="mx-auto w-full max-w-[1480px]">
            <ErrorBoundary resetKey={location.pathname}><Outlet /></ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  );
}