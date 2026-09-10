import { Navigate, Outlet, useLocation } from "react-router-dom";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import { useAuth } from "@/context/AuthContext";

const TITLES = {
  "/dashboard": "Dashboard",
  "/assigned-assets": "Assigned Assets",
  "/requisitions/new": "New Requisition",
  "/requisitions/pending": "Pending Requisition",
  "/requisitions/purchase": "File Purchase Requisition",
  "/requisitions/approve": "Approve Requisition",
  "/requisitions/history": "Requisition History",
  "/stock": "Stock List",
  "/purchase/grn": "Stock GRN (Vendor Challan)",
  "/handover": "Handover Module",
  "/handover/records": "Handover Records",
  "/approvals": "Approver Management",
  "/organization/departments": "Departments",
  "/organization/categories": "Categories",
  "/organization/users": "Users & Roles",
};

export default function Shell() {
  const { user } = useAuth();
  const location = useLocation();

  if (user === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#070E20] text-slate-300">
        <div className="animate-pulse">Loading workspace…</div>
      </div>
    );
  }
  if (user === false) return <Navigate to="/login" replace />;

  const title = TITLES[location.pathname] || "IMS";
  return (
    <div className="flex min-h-screen bg-[#F8FAFC]">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Header title={title} />
        <main className="flex-1 p-6 lg:p-8 overflow-x-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
