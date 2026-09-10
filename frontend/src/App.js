import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import Shell from "@/components/layout/Shell";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import NewRequisition from "@/pages/NewRequisition";
import RequisitionList from "@/pages/RequisitionList";
import Users from "@/pages/Users";
import Departments from "@/pages/Departments";
import Categories from "@/pages/Categories";
import Approvals from "@/pages/Approvals";
import Placeholder from "@/pages/Placeholder";
import StockGRN from "@/pages/StockGRN";
import StockList from "@/pages/StockList";
import AssignedAssets from "@/pages/AssignedAssets";
import HandoverModule from "@/pages/HandoverModule";
import HandoverRecords from "@/pages/HandoverRecords";

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<Shell />}>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/assigned-assets" element={<AssignedAssets />} />
              <Route path="/requisitions/new" element={<NewRequisition />} />
              <Route path="/requisitions/pending" element={<RequisitionList scope="pending" />} />
              <Route path="/requisitions/purchase" element={<RequisitionList scope="purchase" />} />
              <Route path="/requisitions/approve" element={<RequisitionList scope="approve" />} />
              <Route path="/requisitions/history" element={<RequisitionList scope="history" />} />
              <Route path="/stock" element={<StockList />} />
              <Route path="/purchase/grn" element={<StockGRN />} />
              <Route path="/handover" element={<HandoverModule />} />
              <Route path="/handover/records" element={<HandoverRecords />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/organization/departments" element={<Departments />} />
              <Route path="/organization/categories" element={<Categories />} />
              <Route path="/organization/users" element={<Users />} />
            </Route>
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster position="top-right" richColors />
      </AuthProvider>
    </div>
  );
}

export default App;
