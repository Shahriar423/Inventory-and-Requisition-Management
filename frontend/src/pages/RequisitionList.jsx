import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Search, Eye, Check, X, ShieldCheck, FileText, FastForward, DollarSign, CheckCircle2, RotateCcw, Package, XCircle, Paperclip, Pencil, MessageSquarePlus, ThumbsUp, ThumbsDown, Undo2 } from "lucide-react";
import api, { API, formatApiErrorDetail, withAuthParam, onDataRefresh, requestDataRefresh } from "@/lib/apiClient";
import { StatusBadge, bdt, timeAgo, revisionFeedback, prRevisionFeedback } from "@/lib/status";
import { useAuth } from "@/context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { showResult } from "@/components/ResultPopup";
import { StockSelectionModal, BypassStockModal } from "@/components/PRHandlingModals";
import { useNavigate, useSearchParams } from "react-router-dom";

// Once the PR raiser has filed the Purchase Requisition, the line items show THEIR form (specs / brand);
// before that (Department Head, PR raiser) they show what the requester typed on the New Requisition form.
const prFiledOf = (r) => !!(r?.purchase_pr_no || (r?.history || []).some((h) => h.action === "pr_filed"));

const PRODUCT_TYPE_LABELS = { asset: "IT Asset", it_accessories: "IT Accessories", network: "Network", consumable: "Consumable", furniture: "Furniture" };

const HEADINGS = {
  pending: { title: "Pending Requisition", subtitle: "Your requisitions still moving through approval." },
  approve: { title: "Approve Requisition", subtitle: "Requisitions awaiting your approval." },
  history: { title: "Requisition History", subtitle: "Approved and rejected requisitions." },
  purchase: { title: "File Purchase Requisition", subtitle: "Approved requisitions awaiting your decision: fulfill from stock, or bypass stock and raise a Purchase Requisition." },
  "purchase-order": { title: "File Purchase Order", subtitle: "Purchase Order creation for out-of-stock items pending PO entry." },
  handover: { title: "Handover Queue", subtitle: "Issue stock for requisitions received via GRN, then print and confirm physical handover." },
  mine: { title: "My Requisitions", subtitle: "Every requisition you have raised." },
  "filed-prs": { title: "PRs Filed by Me", subtitle: "Purchase Requisitions you filed (voided/revised PRs are excluded)." },
};

export default function RequisitionList({ scope }) {
  const { user, menu } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reviseTarget, setReviseTarget] = useState(null);
  const [reviseNote, setReviseNote] = useState("");
  const [cancelTarget, setCancelTarget] = useState(null);   // requester withdrawing their own requisition
  const [cancelNote, setCancelNote] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [reviseMode, setReviseMode] = useState("revise");   // "revise" (to requester) | "pr_revise" (to PR Raiser)
  // IT Head's PR-review step gets two ways to send a requisition back.
  const isPrReviewStep = (r) => !!(r.approval_chain || []).find((st) => st.status === "pending" && st.stage === "pr_review");
  const [noteOpen, setNoteOpen] = useState(false);          // optional note (approve / reject) is collapsed by default
  const openRevise = (id, mode = "revise") => { setReviseMode(mode); setNoteOpen(false); setReviseTarget(id); };
  const [stockTarget, setStockTarget] = useState(null);    // PR handler: "Fulfill from Stock"
  const [bypassTarget, setBypassTarget] = useState(null);  // PR handler: "Bypass Stock & Raise PR"
  const [searchParams] = useSearchParams();
  const statusFilter = searchParams.get("status");
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Pass the dashboard card's ?status= to the API too (the server maps "approved" to
      // approved + handover_done, exactly like the dashboard count).
      const qs = `scope=${scope}${statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : ""}`;
      const { data } = await api.get(`/requisitions?${qs}`);
      setRows(data);
    } catch (e) {
      console.error("Failed to load requisitions", e);
    } finally {
      setLoading(false);
    }
  }, [scope, statusFilter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => onDataRefresh(load), [load]);

  const act = async (id, action, note) => {
    try {
      await api.post(`/requisitions/${id}/action`, { action, note });
      if (action === "approve" || action === "reject") {
        showResult(action === "approve"
          ? { title: "Done!", message: "The requisition has been approved successfully." }
          : { kind: "reject", title: "Rejected", message: "The requisition has been rejected." });
      } else if (action === "pr_revise") {
        showResult({ title: "Sent Back", message: "The requisition was sent back to the PR Raiser for PR revision." });
      } else {
        showResult({ title: "Sent Back", message: "The requisition was sent back to the requester for revision." });
      }
      setDetail(null);
      setReviseTarget(null);
      setReviseNote("");
      setRows((prev) => prev.filter((r) => r.id !== id));
      requestDataRefresh();
    } catch (e) {
      if (e.response && e.response.data) {
        toast.error(formatApiErrorDetail(e.response.data.detail));
      } else {
        console.error("Action handler caught non-API error:", e);
      }
    }
  };

  const submitRevise = () => {
    // Revision requests need a reason; an approve / reject note is optional.
    if ((reviseMode === "revise" || reviseMode === "pr_revise") && !reviseNote.trim()) {
      return toast.error("A note explaining the requested revision is required");
    }
    act(reviseTarget, reviseMode, reviseNote.trim());
  };

  const serviceAdvance = async (id) => {
    try {
      const { data } = await api.post(`/requisitions/${id}/service-transition`, {});
      toast.success(`Moved to: ${data.status.replaceAll("_", " ")}`);
      setDetail(null);
      setRows((prev) => prev.map((r) => (r.id === id ? { ...r, status: data.status } : r)));
      requestDataRefresh();
    } catch (e) {
      if (e.response && e.response.data) {
        toast.error(formatApiErrorDetail(e.response.data.detail));
      }
    }
  };

  const canSeePdf = user?.role !== "executive";   // employees don't get the PDF button
  const openPdf = (id) => window.open(withAuthParam(`${API}/requisitions/${id}/pdf`), "_blank");
  const openHandoverPdf = (handoverId) => window.open(withAuthParam(`${API}/handovers/${handoverId}/pdf`), "_blank");

  const markDelivered = async (handoverId) => {
    try {
      await api.post(`/handovers/${handoverId}/deliver`);
      toast.success("Marked delivered — requester will now see a receipt confirmation on their bell notification.");
      setRows((prev) => prev.filter((r) => r.handover_id !== handoverId));
      requestDataRefresh();
    } catch (e) {
      if (e.response && e.response.data) {
        toast.error(formatApiErrorDetail(e.response.data.detail));
      }
    }
  };

  const issueStock = async (id) => {
    try {
      await api.post(`/requisitions/${id}/issue-stock`);
      toast.success("Stock issued — handover generated and requester notified.");
      setRows((prev) => prev.filter((r) => r.id !== id));
      requestDataRefresh();
    } catch (e) {
      if (e.response && e.response.data) {
        toast.error(formatApiErrorDetail(e.response.data.detail));
      }
    }
  };

  const cancelPR = async (id) => {
    if (!window.confirm("Cancel this Purchase Requisition? The requester will see status PR Cancelled.")) return;
    try {
      await api.post(`/requisitions/${id}/cancel-pr`, { note: "PR cancelled — item no longer required." });
      toast.success("PR cancelled — requester will see status PR Cancelled.");
      setRows((prev) => prev.filter((r) => r.id !== id));
      setDetail(null);
      requestDataRefresh();
    } catch (e) {
      if (e.response && e.response.data) {
        toast.error(formatApiErrorDetail(e.response.data.detail));
      }
    }
  };

  const cancelRequisition = async () => {
    if (!cancelTarget) return;
    setCancelling(true);
    try {
      await api.post(`/requisitions/${cancelTarget.id}/cancel`, { note: cancelNote.trim() || null });
      toast.success(`${cancelTarget.requisition_no} cancelled`);
      setRows((prev) => prev.filter((r) => r.id !== cancelTarget.id));
      setDetail(null);
      setCancelTarget(null); setCancelNote("");
      requestDataRefresh();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not cancel the requisition");
      load();                       // the approver may have just acted - refresh the row
      setCancelTarget(null);
    } finally {
      setCancelling(false);
    }
  };

  const resubmit = async (id) => {
    try {
      const { data } = await api.post(`/requisitions/${id}/resubmit`, { action: "revise" });
      toast.success("Resubmitted for approval");
      setRows((prev) => prev.map((r) => (r.id === id ? { ...r, status: data.status } : r)));
      requestDataRefresh();
    } catch (e) {
      if (e.response && e.response.data) {
        toast.error(formatApiErrorDetail(e.response.data.detail));
      }
    }
  };

  const h = HEADINGS[scope] || HEADINGS.pending;
  // Someone approving only as a leave delegate sees "Delegated Approvals" (see the sidebar label).
  const approveLabel = (menu || []).flatMap((g) => g.items || []).find((i) => i.path === "/requisitions/approve")?.label;
  const isDelegateView = scope === "approve" && approveLabel === "Delegated Approvals";
  const pageTitle = isDelegateView ? "Delegated Approvals" : h.title;
  const pageSubtitle = isDelegateView ? "Requisitions awaiting approval on behalf of a colleague who is on leave." : h.subtitle;
  const canApproveHere = scope === "approve";
  const needle = q.trim().toLowerCase();
  // "approved" on the dashboard also counts completed handovers, so match both here.
  const matchesStatus = (r) => statusFilter === "approved"
    ? ["approved", "handover_done"].includes(r.status)
    : r.status === statusFilter;
  const visible = (statusFilter ? rows.filter(matchesStatus) : rows).filter((r) =>
    !needle || `${r.requisition_no} ${r.requisitioner_name} ${r.requisition_type}`.toLowerCase().includes(needle));

  return (
    <div className="space-y-6" data-testid={`req-list-${scope}`}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">{pageTitle}</h2>
          <p className="text-slate-500 text-sm mt-1">{pageSubtitle}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500" data-testid="req-count">
            {loading ? "Loading…" : `${visible.length} record${visible.length === 1 ? "" : "s"}`}
          </span>
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search Req No. or requester"
              data-testid="req-search"
              className="h-9 w-64 pl-9 pr-3 rounded-md border border-slate-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-amber-500" />
          </div>
        </div>
      </div>

      <div className="table-card">
        <div className="table-scroll">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
              <th className="px-4 py-3 font-semibold">Req No.</th>
              <th className="px-4 py-3 font-semibold">Requisitioner</th>
              <th className="px-4 py-3 font-semibold">Type</th>
              <th className="px-4 py-3 font-semibold">Items</th>
              <th className="px-4 py-3 font-semibold">Amount</th>
              <th className="px-4 py-3 font-semibold">Status</th>
              <th className="px-4 py-3 font-semibold">Time</th>
              <th className="px-4 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={8} className="px-4 py-14 text-center text-slate-400">{needle ? "No records match your search." : "No requisitions found."}</td></tr>}
            {visible.map((r) => {
              // PR Handler decision row: two primary choices + compact icon-only utilities.
              const isHandlerRow = (scope === "purchase" || scope === "purchase-order")
                && r.status === "pending_pr" && r.requisition_type === "product";
              return (
              <tr key={r.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`req-row-${r.requisition_no}`}>
                <td className="px-4 py-3 font-mono text-slate-800 whitespace-nowrap">{r.requisition_no}</td>
                <td className="px-4 py-3 text-slate-700 whitespace-nowrap">{r.requisitioner_name}</td>
                <td className="px-4 py-3 capitalize text-slate-600">{r.requisition_type}</td>
                <td className="px-4 py-3 text-slate-600">{r.items.length}</td>
                <td className="px-4 py-3 font-mono text-slate-800 whitespace-nowrap">{bdt(r.total_amount)}</td>
                <td className="px-4 py-3 whitespace-nowrap"><StatusBadge status={r.status} /></td>
                <td className="px-4 py-3 text-slate-500 whitespace-nowrap" title={r.updated_at ? new Date(r.updated_at).toLocaleString() : ""}>{timeAgo(r.updated_at || r.created_at)}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                    <button
                      onClick={() => setDetail(r)}
                      data-testid={`btn-view-${r.requisition_no}`}
                      title="View details"
                      className={`h-8 ${isHandlerRow ? "w-8 justify-center" : "px-3"} rounded-md border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors`}
                    >
                      <Eye size={14} />{!isHandlerRow && " View"}
                    </button>

                    {r.can_requester_modify && (
                      <>
                        <button
                          onClick={() => navigate(`/requisitions/${r.id}/edit`)}
                          data-testid={`btn-edit-${r.requisition_no}`}
                          title="Edit until your approver acts on it"
                          className="h-8 px-3 rounded-md border border-sky-300 text-sky-700 text-xs font-semibold hover:bg-sky-50 flex items-center gap-1.5 transition-colors"
                        >
                          <Pencil size={14} /> Edit
                        </button>
                        <button
                          onClick={() => { setCancelTarget(r); setCancelNote(""); }}
                          data-testid={`btn-cancel-${r.requisition_no}`}
                          title="Withdraw this requisition"
                          className="h-8 px-3 rounded-md border border-red-300 text-red-600 text-xs font-semibold hover:bg-red-50 flex items-center gap-1.5 transition-colors"
                        >
                          <XCircle size={14} /> Cancel
                        </button>
                      </>
                    )}

                    {scope === "pending" && r.status === "revision_requested" && (
                      <button
                        onClick={() => navigate(`/requisitions/${r.id}/revise`)}
                        data-testid={`btn-resubmit-${r.requisition_no}`}
                        className="h-8 px-3 rounded-md bg-orange-500 text-white text-xs font-semibold hover:bg-orange-600 flex items-center gap-1.5 transition-colors"
                      >
                        <RotateCcw size={14} /> Edit & Resubmit
                      </button>
                    )}

                    {(scope === "purchase") && r.status === "pending_pr_revision" && user?.can_handle_pr && (
                      <button
                        onClick={() => navigate(`/requisitions/${r.id}/file-pr`)}
                        data-testid={`btn-revise-pr-${r.requisition_no}`}
                        className="h-8 px-3 rounded-md bg-orange-500 text-white text-xs font-semibold hover:bg-orange-600 flex items-center gap-1.5 transition-colors"
                      >
                        <FileText size={14} /> Revise PR
                      </button>
                    )}

                    {isHandlerRow && (
                      <>
                        {user?.can_handle_pr && (
                          <>
                            <button
                              onClick={() => setStockTarget(r)}
                              data-testid={`btn-fulfill-stock-${r.requisition_no}`}
                              className="h-8 px-3 rounded-md bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 shadow-sm flex items-center gap-1.5 transition-colors"
                            >
                              <Package size={14} /> Fulfill from Stock
                            </button>
                            <button
                              onClick={() => setBypassTarget(r)}
                              data-testid={`btn-bypass-stock-${r.requisition_no}`}
                              className="h-8 px-3 rounded-md border border-amber-300 bg-amber-50 text-amber-800 text-xs font-semibold hover:bg-amber-100 flex items-center gap-1.5 transition-colors"
                            >
                              <FastForward size={14} /> Bypass Stock & Raise PR
                            </button>
                          </>
                        )}
                        <button
                          onClick={() => cancelPR(r.id)}
                          data-testid={`btn-cancel-pr-${r.requisition_no}`}
                          title="Cancel PR"
                          className="h-8 w-8 justify-center rounded-md border border-red-200 text-red-600 hover:bg-red-50 flex items-center transition-colors"
                        >
                          <XCircle size={15} />
                        </button>
                      </>
                    )}

                    {(scope === "purchase" || scope === "purchase-order" || user?.can_create_po) && r.status === "pending_po_entry" && (
                      <button
                        onClick={() => navigate(`/purchase/orders/new?pr=${r.id}`)}
                        data-testid={`btn-create-po-${r.requisition_no}`}
                        className="h-8 px-3 rounded-md bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 flex items-center gap-1.5 transition-colors"
                      >
                        <DollarSign size={14} /> Create Purchase Order
                      </button>
                    )}

                    {(scope === "purchase" || scope === "purchase-order" || user?.can_create_po) && r.status === "po_draft" && r.po_id && (
                      <button
                        onClick={() => navigate(`/purchase/orders/${r.po_id}`)}
                        data-testid={`btn-continue-po-draft-${r.requisition_no}`}
                        className="h-8 px-3 rounded-md border border-blue-300 bg-blue-50 text-blue-700 text-xs font-semibold hover:bg-blue-100 flex items-center gap-1.5 transition-colors"
                      >
                        <FileText size={14} /> Continue Draft PO
                      </button>
                    )}

                    {scope === "handover" && r.status === "stock_received_in_it" && (
                      <button
                        onClick={() => issueStock(r.id)}
                        data-testid={`btn-issue-stock-${r.requisition_no}`}
                        className="h-8 px-3 rounded-md bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 flex items-center gap-1.5 transition-colors"
                      >
                        <Package size={14} /> Issue Stock for Requisition
                      </button>
                    )}

                    {scope === "handover" && r.status === "pending_handover" && r.handover_id && (
                      <>
                        <button
                          onClick={() => openHandoverPdf(r.handover_id)}
                          data-testid={`btn-print-handover-${r.requisition_no}`}
                          className="h-8 px-3 rounded-md border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"
                        >
                          <FileText size={14} /> Print Handover
                        </button>
                        <button
                          onClick={() => markDelivered(r.handover_id)}
                          data-testid={`btn-handover-done-${r.requisition_no}`}
                          className="h-8 px-3 rounded-md bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 flex items-center gap-1.5 transition-colors"
                        >
                          <CheckCircle2 size={14} /> Handover Done
                        </button>
                      </>
                    )}

                    {canSeePdf && r.requisition_type === "product" && (
                      <button
                        onClick={() => openPdf(r.id)}
                        data-testid={`btn-pdf-${r.requisition_no}`}
                        title="Open PDF"
                        className={`h-8 ${isHandlerRow ? "w-8 justify-center" : "px-3"} rounded-md border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors`}
                      >
                        <FileText size={14} />{!isHandlerRow && " PDF"}
                      </button>
                    )}

                    {canApproveHere && r.requisition_type === "service" && (
                      <button
                        onClick={() => serviceAdvance(r.id)}
                        data-testid={`btn-service-advance-${r.requisition_no}`}
                        className="h-8 px-3 rounded-md bg-sky-600 text-white text-xs font-semibold hover:bg-sky-700 flex items-center gap-1.5 transition-colors"
                      >
                        <FastForward size={14} /> Advance
                      </button>
                    )}

                    {canApproveHere && r.requisition_type !== "service" && (
                      <>
                        <button
                          onClick={() => openRevise(r.id, "approve")}
                          data-testid={`btn-approve-${r.requisition_no}`}
                          className="h-8 px-3 rounded-md bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 flex items-center gap-1.5 transition-colors"
                        >
                          <Check size={14} /> Approve
                        </button>
                        <button
                          onClick={() => openRevise(r.id, "revise")}
                          data-testid={`btn-revise-${r.requisition_no}`}
                          title={isPrReviewStep(r) ? "Send back to the requester (employee)" : undefined}
                          className="h-8 px-3 rounded-md bg-orange-500 text-white text-xs font-semibold hover:bg-orange-600 flex items-center gap-1.5 transition-colors"
                        >
                          <RotateCcw size={14} /> {isPrReviewStep(r) ? "Revise Request" : "Revise"}
                        </button>
                        {isPrReviewStep(r) && (
                          <button
                            onClick={() => openRevise(r.id, "pr_revise")}
                            data-testid={`btn-pr-revise-${r.requisition_no}`}
                            title="Send back to the PR Raiser to fix specs, brand, quantity or PR details"
                            className="h-8 px-3 rounded-md border border-orange-300 bg-orange-50 text-orange-800 text-xs font-semibold hover:bg-orange-100 flex items-center gap-1.5 transition-colors"
                          >
                            <FileText size={14} /> PR Revise
                          </button>
                        )}
                        <button
                          onClick={() => openRevise(r.id, "reject")}
                          data-testid={`btn-reject-${r.requisition_no}`}
                          className="h-8 px-3 rounded-md bg-red-600 text-white text-xs font-semibold hover:bg-red-700 flex items-center gap-1.5 transition-colors"
                        >
                          <X size={14} /> Reject
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            );})}
          </tbody>
        </table>
        </div>
      </div>

      {user?.can_handle_pr && (
        <>
          <StockSelectionModal
            req={stockTarget}
            onClose={() => setStockTarget(null)}
            onDone={() => {
              const rid = stockTarget?.id;
              setStockTarget(null);
              setRows((prev) => prev.filter((x) => x.id !== rid));
              showResult({ title: "Sent for approval", message: "Stock selected and reserved. The requisition is now with the IT Head for stock approval; handover starts after approval." });
              requestDataRefresh();
            }}
          />
          <BypassStockModal
            req={bypassTarget}
            onClose={() => setBypassTarget(null)}
            onDone={() => {
              const rid = bypassTarget?.id;
              setBypassTarget(null);
              navigate(`/requisitions/${rid}/file-pr`);
            }}
          />
        </>
      )}

      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-w-4xl" data-testid="req-detail-dialog">
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle className="font-mono flex items-center gap-3">
                  {detail.requisition_no}
                  <StatusBadge status={detail.status} />
                </DialogTitle>
              </DialogHeader>

              <div className="space-y-5 max-h-[70vh] overflow-y-auto pr-1">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <div className="text-xs uppercase text-slate-400">Requisitioner</div>
                    <div className="font-medium">{detail.requisitioner_name}</div>
                  </div>
                  <div>
                    <div className="text-xs uppercase text-slate-400">Department</div>
                    <div className="font-medium">{detail.requisitioner_department_name || "—"}</div>
                  </div>
                  <div>
                    <div className="text-xs uppercase text-slate-400">Type</div>
                    <div className="font-medium capitalize">{detail.requisition_type}</div>
                  </div>
                  {detail.requisition_type !== "service" && (
                    <>
                      <div>
                        <div className="text-xs uppercase text-slate-400">Required By</div>
                        <div className="font-medium">{detail.required_by_date || "—"}</div>
                      </div>
                      <div>
                        <div className="text-xs uppercase text-slate-400">Urgency</div>
                        <div className="font-medium">{detail.urgency_level || "—"}</div>
                      </div>
                      <div>
                        <div className="text-xs uppercase text-slate-400">Delivery Location</div>
                        <div className="font-medium">{detail.delivery_location || "—"}</div>
                      </div>
                    </>
                  )}
                </div>

                {/* Service requests: the request details sit up here with the other header info */}
                {detail.requisition_type === "service" && detail.items.map((it, i) => (
                  <div key={i} className="space-y-2" data-testid={`service-request-${i}`}>
                    {detail.items.length > 1 && <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Request {i + 1}</div>}
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <div className="text-xs uppercase text-slate-400">Priority Level</div>
                        <div className="font-medium">
                          {it.priority
                            ? <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold capitalize ${{ low: "bg-slate-100 text-slate-600", medium: "bg-sky-100 text-sky-700", high: "bg-amber-100 text-amber-700", critical: "bg-red-100 text-red-700" }[it.priority] || ""}`}>{it.priority}</span>
                            : "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs uppercase text-slate-400">Request Type</div>
                        <div className="font-medium capitalize">{it.request_type || it.product_name || "—"}</div>
                      </div>
                      {it.request_detail && (
                        <div>
                          <div className="text-xs uppercase text-slate-400">{it.request_type === "software" ? "Action" : "Device"}</div>
                          <div className="font-medium">{it.request_detail}</div>
                        </div>
                      )}
                      <div className="col-span-2">
                        <div className="text-xs uppercase text-slate-400">Description</div>
                        <div className="font-medium">{it.remarks || it.justification_remarks || "—"}</div>
                      </div>
                    </div>
                  </div>
                ))}

                {(detail.requester_note || "").trim() && (
                  <div className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3" data-testid="detail-requester-note">
                    <div className="text-sm font-semibold text-sky-800">Requester note — from {detail.requisitioner_name}</div>
                    <div className="text-sm text-sky-900 mt-1 whitespace-pre-wrap">{detail.requester_note}</div>
                  </div>
                )}

                {detail.overall_business_justification && (
                  <div>
                    <div className="text-xs uppercase text-slate-400 mb-1">Overall Business Justification</div>
                    <div className="text-sm bg-slate-50 border border-slate-200 rounded-lg p-3">
                      {detail.overall_business_justification}
                    </div>
                  </div>
                )}

                {(detail.attachments || []).length > 0 && (
                  <div>
                    <div className="text-xs uppercase text-slate-400 mb-2">Attachments</div>
                    <ul className="space-y-1">
                      {detail.attachments.map((a) => (
                        <li key={a.id}>
                          <a href={withAuthParam(`${API}/files/${a.id}/download`)} target="_blank" rel="noreferrer"
                             className="text-sm text-blue-600 hover:underline inline-flex items-center gap-2" data-testid={`req-attachment-${a.id}`}>
                            <Paperclip size={14} /> {a.name} <span className="text-xs text-slate-400">· {a.kind}</span>
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {detail.requisition_type !== "service" && (
                <div>
                  <div className="text-xs uppercase text-slate-400 mb-2">Line Items</div>
                  <div className="border border-slate-200 rounded-lg overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-50 text-xs text-slate-500">
                        <tr>
                          <th className="px-3 py-2 text-left">#</th>
                          <th className="px-3 py-2 text-left">Category</th>
                          <th className="px-3 py-2 text-left">Product</th>
                          <th className="px-3 py-2 text-left">Preferred Specification</th>
                          <th className="px-3 py-2 text-left">Brand Name</th>
                          <th className="px-3 py-2 text-left">Model</th>
                          <th className="px-3 py-2 text-right">Qty</th>
                          <th className="px-3 py-2 text-left">UoM</th>
                          <th className="px-3 py-2 text-left">Justification</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.items.map((it, i) => (
                          <tr key={i} className="border-t border-slate-100">
                            <td className="px-3 py-2">{i + 1}</td>
                            <td className="px-3 py-2">{it.category || PRODUCT_TYPE_LABELS[it.product_type] || it.product_type || "—"}</td>
                            <td className="px-3 py-2 font-medium">{it.product_name || "—"}</td>
                            <td className="px-3 py-2 text-slate-600">{(prFiledOf(detail) ? it.detailed_specs : it.preferred_specification) || "—"}</td>
                            <td className="px-3 py-2">{(prFiledOf(detail) ? it.preferred_brand : it.brand_name) || "—"}</td>
                            <td className="px-3 py-2">{it.model || "—"}</td>
                            <td className="px-3 py-2 text-right font-mono">{it.quantity}</td>
                            <td className="px-3 py-2">{it.uom || "Pcs"}</td>
                            <td className="px-3 py-2 text-slate-600">{it.justification_remarks || it.remarks || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                )}

                {detail.fulfillment_type === "STOCK_ALLOCATION" && (detail.allocated_item_details || []).length > 0 && (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3" data-testid="detail-stock-allocation">
                    <div className="text-sm font-semibold text-emerald-800">
                      Stock allocation{detail.allocated_by ? ` selected by ${detail.allocated_by}` : ""}
                    </div>
                    <ul className="mt-1.5 space-y-1 text-sm text-emerald-900">
                      {detail.allocated_item_details.map((a) => (
                        <li key={a.asset_id}>
                          {a.name}{a.brand ? ` · ${a.brand}` : ""}{(a.tag_id || a.serial_no) ? ` · ${a.tag_id || a.serial_no}` : ""}
                          {a.is_substitute && <span className="ml-2 text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">Substitute for {a.requested_item}</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {detail.status === "pending_dept" && detail.last_edit && (
                  <div className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3" data-testid="detail-edit-note">
                    <div className="text-sm font-semibold text-sky-800">
                      Updated by {detail.last_edit.by} · {timeAgo(detail.last_edit.at)}
                      {detail.last_edit.count > 1 ? ` (edit #${detail.last_edit.count})` : ""}
                    </div>
                    <ul className="mt-1 list-disc pl-5 text-sm text-sky-700">
                      {(detail.last_edit.changes || []).map((c, i) => <li key={i}>{c}</li>)}
                    </ul>
                  </div>
                )}

                <div>
                  <div className="text-xs uppercase text-slate-400 mb-2 flex items-center gap-1.5">
                    <ShieldCheck size={14} /> Approval Chain
                  </div>
                  {(() => {
                    // Every note / reason / remark lives here, under the person who wrote it and the time they acted.
                    const hist = detail.history || [];
                    const lastOf = (a) => [...hist].reverse().find((h) => h.action === a);
                    const fmtTime = (v) => {
                      const d = v ? new Date(v) : null;
                      return d && !Number.isNaN(d.getTime())
                        ? d.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Dhaka" })
                        : null;
                    };
                    const inChain = (note) => !!note && (detail.approval_chain || []).some((st) => (st.note || "").trim() === String(note).trim());
                    const rows = [];

                    const bypassReason = detail.fulfillment_type === "PURCHASE_REQUISITION" ? (detail.procurement_notes || "").trim() : "";
                    if (bypassReason) {
                      const h = lastOf("stock_bypassed");
                      const who = detail.stock_bypassed_by || h?.by;
                      rows.push({ key: "bypass", testid: "detail-stock-bypass-reason", at: h?.at, note: bypassReason,
                        title: <><span className="font-medium">Stock bypassed</span>{who ? <> by <span className="font-medium">{who}</span></> : null}</> });
                    }

                    const allocNote = detail.fulfillment_type === "STOCK_ALLOCATION" ? (detail.procurement_notes || "").trim() : "";
                    if (allocNote) {
                      const h = lastOf("stock_allocated");
                      const who = detail.allocated_by || h?.by;
                      rows.push({ key: "alloc", testid: "detail-stock-allocation-note", at: h?.at, note: allocNote,
                        title: <><span className="font-medium">Stock allocated</span>{who ? <> by <span className="font-medium">{who}</span></> : null}</> });
                    }

                    const filed = lastOf("pr_filed");
                    if (filed && fmtTime(filed.at)) {
                      rows.push({ key: "filed", testid: "pr-raised-info", at: filed.at, note: null,
                        title: <><span className="font-medium">Purchase Requisition raised</span>{filed.by ? <> by <span className="font-medium">{filed.by}</span></> : null}</> });
                    }

                    // Revision notes normally sit on the approver's own step already; only fall back to a row here
                    // when the note comes from somewhere else (e.g. a PR void reason), so it is never duplicated.
                    if (detail.status === "revision_requested") {
                      const fb = revisionFeedback(detail);
                      if (fb && fb.note && !inChain(fb.note)) {
                        const h = lastOf("revise");
                        rows.push({ key: "revise", testid: "detail-revision-note", at: h?.at, note: fb.note,
                          title: <>Sent back for revision by <span className="font-medium">{fb.by || "the approver"}</span>{fb.label ? ` (${fb.label})` : ""}</> });
                      }
                    }
                    if (detail.status === "pending_pr_revision") {
                      const fb = prRevisionFeedback(detail);
                      if (fb && fb.note && !inChain(fb.note)) {
                        const h = lastOf("pr_revise");
                        rows.push({ key: "pr-revise", testid: "detail-pr-revision-note", at: h?.at, note: fb.note,
                          title: <>PR revision requested by <span className="font-medium">{fb.by || "the IT Head"}</span></> });
                      }
                    }

                    return rows.map((r) => (
                      <div key={r.key} className="mb-2 px-4 py-2 rounded-lg bg-slate-50 text-sm" data-testid={r.testid}>
                        <div>{r.title}</div>
                        {fmtTime(r.at) && <div className="mt-0.5 text-[11px] text-slate-400">{fmtTime(r.at)}</div>}
                        {r.note && <div className="mt-1.5 text-xs text-slate-500 italic whitespace-pre-wrap">"{r.note}"</div>}
                      </div>
                    ));
                  })()}
                  <div className="space-y-2">
                    {detail.approval_chain.filter((s) => !/^auto-approved/i.test(s.note || "")).map((s, i) => (
                      <div key={i} className="px-4 py-2 rounded-lg bg-slate-50 text-sm">
                        <div className="flex items-center justify-between">
                          <span>
                            <span className="font-mono text-xs text-slate-400 mr-2">L{s.level}</span>
                            {s.label} — <span className="font-medium">{s.approver_name || "—"}</span>
                            {s.acted_as === "delegate" && s.acted_by_name && (
                              <span className="ml-2 text-xs text-slate-500">(approved by {s.acted_by_name} as delegate)</span>
                            )}
                            {s.status === "pending" && s.reminded_at && (
                              <span className="ml-2 text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-100">
                                Reminder sent
                              </span>
                            )}
                          </span>
                          <StatusBadge
                            status={
                              s.status === "pending"
                                ? detail.status
                                : s.status === "approved"
                                ? "approved"
                                : s.status === "revision_requested"
                                ? "revision_requested"
                                : s.status === "pr_revision_requested"
                                ? "pending_pr_revision"
                                : s.status === "cancelled"
                                ? "cancelled"
                                : "rejected"
                            }
                          />
                        </div>
                        {s.status !== "pending" && s.acted_at && !Number.isNaN(new Date(s.acted_at).getTime()) && (
                          <div className="mt-0.5 ml-7 text-[11px] text-slate-400" data-testid={`chain-time-${i}`}>
                            {new Date(s.acted_at).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Dhaka" })}
                          </div>
                        )}
                        {s.note && !/^auto-approved/i.test(s.note) && <div className="mt-1.5 text-xs text-slate-500 italic">"{s.note}"</div>}
                      </div>
                    ))}
                  </div>

                  {(detail.po_approvals || []).map((po) => (
                    <div key={po.po_number} className="mt-4" data-testid={`po-approvals-${po.po_number}`}>
                      <div className="text-xs uppercase text-slate-400 mb-2">
                        Purchase Order Approval <span className="font-mono normal-case text-slate-500">· {po.po_number}</span>
                      </div>
                      <div className="space-y-2">
                        {po.stages.map((st) => (
                          <div key={st.role} className="px-4 py-2 rounded-lg bg-slate-50 text-sm">
                            <div className="flex items-center justify-between">
                              <span>
                                {st.label}
                                {st.by && <> — <span className="font-medium">{st.by}</span></>}
                                {st.at && <span className="ml-2 text-xs text-slate-400">{timeAgo(st.at)}</span>}
                              </span>
                              {st.status === "waiting" ? (
                                <span className="text-xs px-2.5 py-1 rounded-full bg-slate-100 text-slate-500">Waiting</span>
                              ) : st.status === "pending" ? (
                                <span className="text-xs px-2.5 py-1 rounded-full bg-amber-100 text-amber-700">Pending</span>
                              ) : (
                                <StatusBadge status={st.status === "approved" ? "approved" : "rejected"} />
                              )}
                            </div>
                            {st.comment && <div className="mt-1.5 text-xs text-slate-500 italic">"{st.comment}"</div>}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                {(canApproveHere || (canSeePdf && detail.requisition_type === "product")) && (
                  <div className="flex gap-3 pt-2">
                    {canSeePdf && detail.requisition_type === "product" && (
                      <button
                        onClick={() => openPdf(detail.id)}
                        className="px-4 py-2.5 rounded-lg border border-slate-300 text-slate-600 font-semibold hover:bg-slate-50 transition-colors flex items-center gap-2"
                      >
                        <FileText size={16} /> Purchase PDF
                      </button>
                    )}
                    {canApproveHere && detail.requisition_type === "service" && (
                      <button
                        onClick={() => serviceAdvance(detail.id)}
                        className="flex-1 py-2.5 rounded-lg bg-sky-600 text-white font-semibold hover:bg-sky-700 transition-colors"
                      >
                        Advance Service Stage
                      </button>
                    )}
                    {canApproveHere && detail.requisition_type !== "service" && (
                      <>
                        <button
                          onClick={() => openRevise(detail.id, "approve")}
                          className="flex-1 py-2.5 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700 transition-colors"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => openRevise(detail.id, "revise")}
                          className="flex-1 py-2.5 rounded-lg bg-orange-500 text-white font-semibold hover:bg-orange-600 transition-colors"
                        >
                          {isPrReviewStep(detail) ? "Revise Request" : "Revise"}
                        </button>
                        {isPrReviewStep(detail) && (
                          <button
                            onClick={() => openRevise(detail.id, "pr_revise")}
                            className="flex-1 py-2.5 rounded-lg border border-orange-300 bg-orange-50 text-orange-800 font-semibold hover:bg-orange-100 transition-colors"
                          >
                            PR Revise
                          </button>
                        )}
                        <button
                          onClick={() => openRevise(detail.id, "reject")}
                          className="flex-1 py-2.5 rounded-lg bg-red-600 text-white font-semibold hover:bg-red-700 transition-colors"
                        >
                          Reject
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!cancelTarget} onOpenChange={(o) => { if (!o) { setCancelTarget(null); setCancelNote(""); } }}>
        <DialogContent data-testid="cancel-req-dialog">
          <DialogHeader><DialogTitle>Cancel {cancelTarget?.requisition_no}?</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              This withdraws the requisition. It can't be undone — you would need to submit a new one.
            </p>
            <textarea value={cancelNote} onChange={(e) => setCancelNote(e.target.value)} rows={3}
              placeholder="Reason (optional)" data-testid="cancel-req-note"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:border-amber-500" />
            <div className="flex justify-end gap-2">
              <button onClick={() => { setCancelTarget(null); setCancelNote(""); }}
                className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 text-sm font-semibold hover:bg-slate-50">Keep it</button>
              <button onClick={cancelRequisition} disabled={cancelling} data-testid="cancel-req-confirm"
                className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-semibold hover:bg-red-700 disabled:opacity-50">
                {cancelling ? "Cancelling…" : "Yes, cancel requisition"}
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!reviseTarget} onOpenChange={(o) => { if (!o) { setReviseTarget(null); setReviseNote(""); setReviseMode("revise"); setNoteOpen(false); } }}>
        <DialogContent data-testid="revise-note-dialog" className="max-w-md p-0 overflow-hidden gap-0">
          {(() => {
            const m = reviseMode;
            const noteRequired = m === "revise" || m === "pr_revise";
            const showBox = noteRequired || noteOpen;
            const cfg = {
              approve:   { title: "Approve requisition", Icon: ThumbsUp,   tone: "bg-emerald-50 text-emerald-600", btn: "bg-emerald-600 hover:bg-emerald-700", cta: "Approve",
                           sub: "The requester and the next approver will be notified.", ph: "Add a note for the next approver" },
              reject:    { title: "Reject requisition",  Icon: ThumbsDown, tone: "bg-red-50 text-red-600",         btn: "bg-red-600 hover:bg-red-700",         cta: "Reject",
                           sub: "The requester will be notified and the process ends here.", ph: "Reason for rejecting (the requester will see it)" },
              revise:    { title: "Request revision",    Icon: Undo2,      tone: "bg-orange-50 text-orange-600",   btn: "bg-orange-500 hover:bg-orange-600",   cta: "Send for revision",
                           sub: "The requisition goes back to the requester to fix and resubmit.", ph: "What does the requester need to fix?" },
              pr_revise: { title: "Send back to PR Raiser", Icon: Undo2,   tone: "bg-orange-50 text-orange-600",   btn: "bg-orange-500 hover:bg-orange-600",   cta: "Send to PR Raiser",
                           sub: "The PR is kept and returns to you after they resubmit it.", ph: "What must the PR Raiser correct (specs, brand, quantity)?" },
            }[m] || {};
            const reqNo = (rows.find((r) => r.id === reviseTarget) || detail || {}).requisition_no;
            return (
              <>
                <div className="px-6 pt-6 pb-4 flex items-start gap-3">
                  <div className={`h-10 w-10 rounded-full flex items-center justify-center shrink-0 ${cfg.tone}`}>
                    {cfg.Icon && <cfg.Icon size={18} />}
                  </div>
                  <div className="min-w-0">
                    <DialogHeader className="space-y-0.5 text-left">
                      <DialogTitle className="text-base font-semibold text-slate-900">
                        {cfg.title}{reqNo && <span className="ml-2 font-mono text-xs font-normal text-slate-400">{reqNo}</span>}
                      </DialogTitle>
                    </DialogHeader>
                    <p className="text-sm text-slate-500 mt-0.5">{cfg.sub}</p>
                  </div>
                </div>

                <div className="px-6 pb-5">
                  {showBox ? (
                    <div>
                      <label className="text-xs font-medium text-slate-500 flex justify-between mb-1.5">
                        <span>{noteRequired ? "Note" : "Note (optional)"}</span>
                        {noteRequired && <span className="text-slate-400">Required</span>}
                      </label>
                      <textarea
                        value={reviseNote}
                        onChange={(e) => setReviseNote(e.target.value)}
                        onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submitRevise(); }}
                        rows={2}
                        autoFocus
                        placeholder={cfg.ph}
                        data-testid="revise-note-input"
                        className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50/60 focus:bg-white focus:border-amber-500 focus:ring-2 focus:ring-amber-100 outline-none text-sm resize-none transition"
                      />
                    </div>
                  ) : (
                    <button type="button" onClick={() => setNoteOpen(true)} data-testid="revise-add-note"
                      className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-amber-600 transition-colors">
                      <MessageSquarePlus size={16} /> Add a note
                    </button>
                  )}
                </div>

                <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-100 flex justify-end gap-2">
                  <button
                    onClick={() => { setReviseTarget(null); setReviseNote(""); setNoteOpen(false); }}
                    className="px-4 h-9 rounded-lg text-sm font-medium text-slate-600 hover:bg-slate-200/60 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={submitRevise}
                    data-testid="revise-note-submit"
                    className={`px-5 h-9 rounded-lg text-sm font-semibold text-white shadow-sm transition-colors ${cfg.btn}`}
                  >
                    {cfg.cta}
                  </button>
                </div>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>
    </div>
  );
}