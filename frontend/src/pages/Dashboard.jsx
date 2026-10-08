import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { ClipboardList, Clock, CheckCircle2, Inbox, XCircle, AlertCircle, DollarSign, ShoppingCart, FileText, UserCheck } from "lucide-react";
import api, { onDataRefresh } from "@/lib/apiClient";
import { StatusBadge, bdt } from "@/lib/status";
import { useAuth } from "@/context/AuthContext";
import ITServiceQueueCard, { ITQueueTiles, useITServiceQueue } from "@/components/ITServiceQueueCard";

function StatCard({ icon: Icon, label, value, tone, testid, to }) {
  const body = (
    <>
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-3 ${tone}`}>
        <Icon size={20} />
      </div>
      <div className="text-2xl font-head font-bold text-slate-900">{value}</div>
      <div className="text-xs uppercase tracking-wider text-slate-500 mt-1">{label}</div>
    </>
  );
  if (to) {
    return (
      <Link to={to} data-testid={testid}
        className="block bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:border-amber-300 hover:-translate-y-0.5 transition-all duration-200">
        {body}
      </Link>
    );
  }
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm" data-testid={testid}>
      {body}
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const itQueue = useITServiceQueue();      // IT service-queue counts; tiles sit in the stat grids below
  const hasIt = itQueue.enabled;
  const [stats, setStats] = useState(null);

  const load = useCallback(() => {
    api.get("/dashboard/stats", { params: { _t: Date.now() } }).then(({ data }) => setStats(data)).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => onDataRefresh(load), [load]);

  // Keep the cards live. New PR / PO requests are created by OTHER people while this page is
  // open, and nothing tells this page about them, so the counts (e.g. "PO Raise Requests")
  // stayed at the value from when the page loaded. Refetch every 15s while the tab is visible,
  // and immediately when the user comes back to the tab.
  useEffect(() => {
    const whenVisible = () => { if (document.visibilityState === "visible") load(); };
    const timer = setInterval(whenVisible, 15000);
    document.addEventListener("visibilitychange", whenVisible);
    window.addEventListener("focus", whenVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", whenVisible);
      window.removeEventListener("focus", whenVisible);
    };
  }, [load]);

  if (!stats) return <div className="text-slate-500">Loading…</div>;
  const personal = stats.scope === "personal";
  const department = stats.scope === "department";

  const canSeePoApprovals =
    user?.role === "super_admin" ||
    user?.role === "md" ||
    user?.role === "accounts" ||
    user?.role === "purchase_head" ||
    (user?.role === "dept_head" && (user?.department_name === "Purchase" || user?.department_code === "PUR"));

  // PO creators (Purchase dept, can_create_po) get the same kind of cards PR raisers get.
  const canCreatePo =
    !!user?.can_create_po ||
    user?.role === "super_admin" ||
    user?.role === "purchase_head" ||
    (user?.role === "dept_head" && (user?.department_name === "Purchase" || user?.department_code === "PUR"));

  const poCards = (
    <>
      <StatCard icon={ShoppingCart} label="PO Raise Requests" value={stats.awaiting_po ?? 0}
        tone="bg-amber-100 text-amber-700" testid="stat-awaiting-po" to="/requisitions/purchase-order" />
    </>
  );

  return (
    <div className="space-y-6" data-testid="dashboard">
      <div className="flex flex-wrap items-end justify-between gap-3 pb-1">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">
            {personal ? "My Dashboard" : department ? "Department Overview" : "Overview"}
          </h2>
          <p className="text-slate-500 text-sm mt-1">
            {personal ? "Your own requisitions and assigned assets."
              : department ? "Requisitions and assets within your department."
              : "Snapshot of requisitions across the organization."}
          </p>
        </div>
        <div className="text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-full px-3.5 py-1.5 shadow-sm" data-testid="dashboard-date">
          {new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
        </div>
      </div>

      {/* Shown only while someone on leave has delegated their approvals to this user. */}
      {(stats.delegated_for || []).length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" data-testid="delegated-row">
          <StatCard
            icon={UserCheck}
            label={`Delegated Approvals — ${(stats.delegated_for || []).join(", ")}`}
            value={stats.delegated_queue ?? 0}
            tone="bg-amber-100 text-amber-700"
            testid="stat-delegated-queue"
            to="/requisitions/approve"
          />
          {(stats.delegated_po ?? 0) > 0 && (
            <StatCard
              icon={ShoppingCart}
              label="Delegated PO Approvals"
              value={stats.delegated_po}
              tone="bg-amber-100 text-amber-700"
              testid="stat-delegated-po"
              to="/purchase/po-approvals"
            />
          )}
        </div>
      )}

      {/* IT service orders waiting for the IT team (renders nothing for anyone without queue access). */}
      <ITServiceQueueCard queue={itQueue} />

      {personal ? (
        // Minimal 4-card layout for standard employees — no company-wide or approver-only
        // metrics (My Approvals, ≥50k BDT threshold, etc.) are relevant to them.
        <div className={`grid grid-cols-2 gap-4 ${
          hasIt ? "lg:grid-cols-4"
          : user?.can_raise_pr && canCreatePo ? "lg:grid-cols-4 xl:grid-cols-7"
          : user?.can_raise_pr ? "lg:grid-cols-6"
          : canCreatePo ? "lg:grid-cols-5"
          : "lg:grid-cols-4"}`}>
          <StatCard icon={ClipboardList} label="My Total Requisitions" value={stats.total} tone="bg-slate-100 text-slate-700" testid="stat-total" to="/requisitions/mine" />
          <StatCard icon={Clock} label="In Progress" value={stats.in_progress} tone="bg-amber-100 text-amber-700" testid="stat-in-progress" to="/requisitions/pending" />
          <StatCard icon={CheckCircle2} label="Approved" value={stats.approved} tone="bg-emerald-100 text-emerald-700" testid="stat-approved" to="/requisitions/history?status=approved" />
          <StatCard icon={AlertCircle} label="Action Required" value={stats.action_required} tone="bg-orange-100 text-orange-700" testid="stat-action-required" to="/requisitions/pending?status=revision_requested" />
          {user?.can_raise_pr && (
            <>
              <StatCard
                icon={DollarSign}
                label="PR Raise Requests"
                value={stats.awaiting_pr ?? 0}
                tone="bg-amber-100 text-amber-700"
                testid="stat-awaiting-pr"
                to="/requisitions/purchase"
              />
              <StatCard
                icon={FileText}
                label="PRs Filed by Me"
                value={stats.prs_filed ?? 0}
                tone="bg-indigo-100 text-indigo-700"
                testid="stat-prs-filed"
                to="/requisitions/filed-prs"
              />
            </>
          )}
          {canCreatePo && poCards}
          <ITQueueTiles queue={itQueue} />
        </div>
      ) : department ? (
        // Minimal 3-card layout for department heads — just their approval picture: how
        // much they've approved, how much they've rejected, and what's waiting on them
        // right now. Dept Total / Dept Pending / ≥50k BDT are dropped as not directly
        // relevant to their day-to-day approval work. Each card links straight to the
        // matching filtered list — who approved/rejected what, or what needs action now.
         <div className={`grid gap-4 ${hasIt ? `grid-cols-2 lg:grid-cols-4 ${canSeePoApprovals ? "" : "xl:grid-cols-7"}` : `grid-cols-1 sm:grid-cols-3 ${canSeePoApprovals ? "lg:grid-cols-4" : ""}`}`}>
          <StatCard icon={CheckCircle2} label="Approval Total" value={stats.approved} tone="bg-emerald-100 text-emerald-700" testid="stat-approved" to="/requisitions/history?status=approved" />
          <StatCard icon={XCircle} label="Rejection Total" value={stats.rejected} tone="bg-red-100 text-red-700" testid="stat-rejected" to="/requisitions/history?status=rejected" />
          <StatCard icon={Inbox} label="Current Approval Need" value={stats.my_queue} tone="bg-sky-100 text-sky-700" testid="stat-my-queue" to="/requisitions/approve" />
          {canSeePoApprovals && (
            <StatCard
              icon={ShoppingCart}
              label="PO Approvals"
              value={stats.po_pending ?? 0}
              tone="bg-sky-100 text-sky-700"
              testid="stat-po-pending"
              to="/purchase/po-approvals"
            />
          )}
          <ITQueueTiles queue={itQueue} />
        </div>
      ) : (
        <div className={`grid grid-cols-2 gap-4 ${hasIt ? "lg:grid-cols-4" : canSeePoApprovals ? "lg:grid-cols-6" : "lg:grid-cols-5"}`}>
          <StatCard icon={ClipboardList} label="Total" value={stats.total} tone="bg-slate-100 text-slate-700" testid="stat-total" />
          <StatCard icon={Clock} label="Pending" value={stats.pending} tone="bg-amber-100 text-amber-700" testid="stat-pending" />
          <StatCard icon={Inbox} label="My Approvals" value={stats.my_queue} tone="bg-sky-100 text-sky-700" testid="stat-my-queue" to="/requisitions/approve" />
          <StatCard icon={CheckCircle2} label="Approved" value={stats.approved} tone="bg-emerald-100 text-emerald-700" testid="stat-approved" to="/requisitions/history?status=approved" />
          <StatCard icon={XCircle} label="Rejected" value={stats.rejected} tone="bg-red-100 text-red-700" testid="stat-rejected" to="/requisitions/history?status=rejected" />
          {canSeePoApprovals && (
            <StatCard icon={ShoppingCart} label="PO Approvals" value={stats.po_pending ?? 0} tone="bg-sky-100 text-sky-700" testid="stat-po-pending" to="/purchase/po-approvals" />
          )}
          <ITQueueTiles queue={itQueue} />
        </div>
      )}

      {!personal && canCreatePo && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="po-cards-row">{poCards}</div>
      )}

      {/* can_raise_pr is a permission independent of role — a standard employee, dept
          head, or anyone else can hold it — so this sits outside the three layouts above
          rather than being wedged into any one of their grids. */}


      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-[#FBFCFE] rounded-t-xl">
          <h3 className="font-head font-semibold text-slate-900">
            {personal ? "My Pending Requisitions" : department ? "Department Requisitions" : "Recent Requisitions"}
          </h3>
          <Link to="/requisitions/new" className="text-sm font-semibold text-amber-600 hover:text-amber-700" data-testid="dashboard-new-req">+ New Requisition</Link>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100">
              <th className="px-6 py-3 font-semibold">Req No.</th>
              {!personal && <th className="px-6 py-3 font-semibold">Requisitioner</th>}
              <th className="px-6 py-3 font-semibold">Type</th>
              <th className="px-6 py-3 font-semibold">Amount</th>
              <th className="px-6 py-3 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {(personal ? stats.pending_list : stats.recent).length === 0 && (
              <tr><td colSpan={personal ? 4 : 5} className="px-6 py-8 text-center text-slate-400">
                {personal ? "You have no pending requisitions." : "No requisitions yet."}
              </td></tr>
            )}
            {(personal ? stats.pending_list : stats.recent).map((r) => (
              <tr key={r.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`recent-row-${r.requisition_no}`}>
                <td className="px-6 py-3 font-mono text-slate-800">{r.requisition_no}</td>
                {!personal && <td className="px-6 py-3 text-slate-700">{r.requisitioner_name}</td>}
                <td className="px-6 py-3 capitalize text-slate-600">{r.requisition_type}</td>
                <td className="px-6 py-3 font-mono text-slate-800">{bdt(r.total_amount)}</td>
                <td className="px-6 py-3"><StatusBadge status={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {personal && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-[#FBFCFE] rounded-t-xl">
            <h3 className="font-head font-semibold text-slate-900">My Assets</h3>
            <Link to="/assets" className="text-sm font-semibold text-amber-600 hover:text-amber-700" data-testid="dashboard-view-assets">View all</Link>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100">
                <th className="px-6 py-3 font-semibold">Item</th>
                <th className="px-6 py-3 font-semibold">Category</th>
                <th className="px-6 py-3 font-semibold">Serial / Tag</th>
                <th className="px-6 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {(stats.my_assets || []).length === 0 && (
                <tr><td colSpan={4} className="px-6 py-8 text-center text-slate-400">No assets assigned to you yet.</td></tr>
              )}
              {(stats.my_assets || []).map((a) => (
                <tr key={a.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`my-asset-row-${a.id}`}>
                  <td className="px-6 py-3 font-medium text-slate-800">{a.name}</td>
                  <td className="px-6 py-3 text-slate-600">{a.category_name || "—"}</td>
                  <td className="px-6 py-3 font-mono text-slate-600">{a.serial_no || a.tag_id || "—"}</td>
                  <td className="px-6 py-3 capitalize text-slate-600">{(a.status || "").replace("_", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}