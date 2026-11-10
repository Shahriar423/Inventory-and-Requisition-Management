import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import ResultPopupHost from "@/components/ResultPopup";
import Shell from "@/components/layout/Shell";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import lazyWithRetry from "@/lib/lazyWithRetry";

// Login, the app shell and the landing Dashboard ship in the main bundle. Every other page is its own
// chunk, downloaded the first time it is opened (the <Suspense> boundary lives in components/layout/Shell.jsx).
const NewRequisition = lazyWithRetry(() => import(/* webpackChunkName: "new-requisition" */ "@/pages/NewRequisition"));
const RequisitionList = lazyWithRetry(() => import(/* webpackChunkName: "requisition-list" */ "@/pages/RequisitionList"));
const PurchaseRequisitionForm = lazyWithRetry(() => import(/* webpackChunkName: "purchase-requisition-form" */ "@/pages/PurchaseRequisitionForm"));
const PurchaseOrderForm = lazyWithRetry(() => import(/* webpackChunkName: "purchase-order-form" */ "@/pages/PurchaseOrderForm"));
const POApprovals = lazyWithRetry(() => import(/* webpackChunkName: "p-o-approvals" */ "@/pages/POApprovals"));
const StockGRN = lazyWithRetry(() => import(/* webpackChunkName: "stock-g-r-n" */ "@/pages/StockGRN"));
const StockList = lazyWithRetry(() => import(/* webpackChunkName: "stock-list" */ "@/pages/StockList"));
const AssignedAssets = lazyWithRetry(() => import(/* webpackChunkName: "assigned-assets" */ "@/pages/AssignedAssets"));
const HandoverModule = lazyWithRetry(() => import(/* webpackChunkName: "handover-module" */ "@/pages/HandoverModule"));
const HandoverRecords = lazyWithRetry(() => import(/* webpackChunkName: "handover-records" */ "@/pages/HandoverRecords"));
const PaperRecords = lazyWithRetry(() => import(/* webpackChunkName: "paper-records" */ "@/pages/PaperRecords"));
const ReportCenter = lazyWithRetry(() => import(/* webpackChunkName: "report-center" */ "@/pages/ReportCenter"));
const MyReports = lazyWithRetry(() => import(/* webpackChunkName: "my-reports" */ "@/pages/MyReports"));
const AuditSearch = lazyWithRetry(() => import(/* webpackChunkName: "audit-search" */ "@/pages/AuditSearch"));
const Corrections = lazyWithRetry(() => import(/* webpackChunkName: "corrections" */ "@/pages/Corrections"));
const ITServiceQueue = lazyWithRetry(() => import(/* webpackChunkName: "i-t-service-queue" */ "@/pages/ITServiceQueue"));
const BulkImport = lazyWithRetry(() => import(/* webpackChunkName: "bulk-import" */ "@/pages/BulkImport"));
const Users = lazyWithRetry(() => import(/* webpackChunkName: "users" */ "@/pages/Users"));
const Departments = lazyWithRetry(() => import(/* webpackChunkName: "departments" */ "@/pages/Departments"));
const Categories = lazyWithRetry(() => import(/* webpackChunkName: "categories" */ "@/pages/Categories"));
const ProductCatalog = lazyWithRetry(() => import(/* webpackChunkName: "product-catalog" */ "@/pages/ProductCatalog"));
const Approvals = lazyWithRetry(() => import(/* webpackChunkName: "approvals" */ "@/pages/Approvals"));
const MyTeam = lazyWithRetry(() => import(/* webpackChunkName: "my-team" */ "@/pages/MyTeam"));

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
              <Route path="/requisitions/:id/revise" element={<NewRequisition />} />
              <Route path="/requisitions/:id/edit" element={<NewRequisition />} />
              <Route path="/requisitions/pending" element={<RequisitionList scope="pending" />} />
              <Route path="/requisitions/purchase" element={<RequisitionList scope="purchase" />} />
              <Route path="/requisitions/handover" element={<RequisitionList scope="handover" />} />
              <Route path="/requisitions/:id/file-pr" element={<PurchaseRequisitionForm />} />
              <Route path="/requisitions/approve" element={<RequisitionList scope="approve" />} />
              <Route path="/requisitions/history" element={<RequisitionList scope="history" />} />

              <Route path="/purchase/orders/new" element={<PurchaseOrderForm />} />
              <Route path="/purchase/orders/:id" element={<PurchaseOrderForm />} />
              <Route path="/organization/my-team" element={<MyTeam />} />
              <Route path="/requisitions/mine" element={<RequisitionList scope="mine" />} />
              <Route path="/stock" element={<StockList />} />
              <Route path="/purchase/grn" element={<StockGRN />} />
              <Route path="/handover" element={<HandoverModule />} />
              <Route path="/handover/records" element={<HandoverRecords />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/organization/departments" element={<Departments />} />
              <Route path="/organization/categories" element={<Categories />} />
              <Route path="/organization/products" element={<ProductCatalog />} />
              <Route path="/organization/users" element={<Users />} />
              <Route path="/requisitions/purchase-order" element={<RequisitionList scope="purchase-order" />} />
              <Route path="/purchase/po-approvals" element={<POApprovals />} />
              <Route path="/requisitions/filed-prs" element={<RequisitionList scope="filed-prs" />} />
              <Route path="/it-service/queue" element={<ITServiceQueue />} />
              <Route path="/audit/search" element={<AuditSearch />} />
              <Route path="/corrections" element={<Corrections />} />
              <Route path="/corrections/mine" element={<Corrections />} />
              <Route path="/corrections/:id" element={<Corrections />} />
              <Route path="/reports" element={<ReportCenter />} />
              <Route path="/reports/mine" element={<MyReports />} />
              <Route path="/reports/mine/:id" element={<MyReports />} />
              <Route path="/organization/import" element={<BulkImport />} />
              <Route path="/handover/paper-records" element={<PaperRecords />} />
            </Route>
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster position="top-right" richColors />
        <ResultPopupHost />
      </AuthProvider>
    </div>
  );
}

export default App;