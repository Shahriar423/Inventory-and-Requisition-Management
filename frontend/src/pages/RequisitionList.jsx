import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Search, Eye, Check, X, ShieldCheck, FileText, FastForward, DollarSign, CheckCircle2, RotateCcw, Package, XCircle, Paperclip } from "lucide-react";
import api, { API, formatApiErrorDetail, withAuthParam, onDataRefresh, requestDataRefresh } from "@/lib/apiClient";
import { StatusBadge, bdt } from "@/lib/status";
import { useAuth } from "@/context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { showResult } from "@/components/ResultPopup";
import { useNavigate, useSearchParams } from "react-router-dom";

const PRODUCT_TYPE_LABELS = { asset: "IT Asset", it_accessories: "IT Accessories", network: "Network", consumable: "Consumable", furniture: "Furniture" };

const HEADINGS = {
  pending: { title: "Pending Requisition", subtitle: "Your requisitions still moving through approval." },
  approve: { title: "Approve Requisition", subtitle: "Requisitions awaiting your approval." },
  history: { title: "Requisition History", subtitle: "Approved and rejected requisitions." },
  purchase: { title: "File Purchase Requisition", subtitle: "Non-financial PR filing (Tech Gatekeeper) for out-of-stock items." },
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
  const [searchParams] = useSearchParams();
  const statusFilter = searchParams.get("status");
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/requisitions?scope=${scope}`);
      setRows(data);
    } catch (e) {
      console.error("Failed to load requisitions", e);
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => onDataRefresh(load), [load]);

  const act = async (id, action, note) => {
    try {
      await api.post(`/requisitions/${id}/action`, { action, note });
      if (action === "approve" || action === "reject") {
        showResult(action === "approve"
          ? { title: "Done!", message: "The requisition has been approved successfully." }
          : { kind: "reject", title: "Rejected", message: "The requisition has been rejected." });
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
    if (!reviseNote.trim()) return toast.error("A note explaining the requested revision is required");
    act(reviseTarget, "revise", reviseNote.trim());
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
  const visible = (statusFilter ? rows.filter((r) => r.status === statusFilter) : rows).filter((r) =>
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
              <th className="px-6 py-3 font-semibold">Req No.</th>
              <th className="px-6 py-3 font-semibold">Requisitioner</th>
              <th className="px-6 py-3 font-semibold">Type</th>
              <th className="px-6 py-3 font-semibold">Items</th>
              <th className="px-6 py-3 font-semibold">Amount</th>
              <th className="px-6 py-3 font-semibold">Status</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="px-6 py-8 text-center text-slate-400">Loading…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={7} className="px-6 py-14 text-center text-slate-400">{needle ? "No records match your search." : "No requisitions found."}</td></tr>}
            {visible.map((r) => (
              <tr key={r.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`req-row-${r.requisition_no}`}>
                <td className="px-6 py-3 font-mono text-slate-800">{r.requisition_no}</td>
                <td className="px-6 py-3 text-slate-700">{r.requisitioner_name}</td>
                <td className="px-6 py-3 capitalize text-slate-600">{r.requisition_type}</td>
                <td className="px-6 py-3 text-slate-600">{r.items.length}</td>
                <td className="px-6 py-3 font-mono text-slate-800">{bdt(r.total_amount)}</td>
                <td className="px-6 py-3"><StatusBadge status={r.status} /></td>
                <td className="px-6 py-3">
                  <div className="flex items-center justify-end gap-2">
                    <button
                      onClick={() => setDetail(r)}
                      data-testid={`btn-view-${r.requisition_no}`}
                      className="h-8 px-3 rounded-md border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"
                    >
                      <Eye size={14} /> View
                    </button>

                    {scope === "pending" && r.status === "revision_requested" && (
                      <button
                        onClick={() => navigate(`/requisitions/${r.id}/revise`)}
                        data-testid={`btn-resubmit-${r.requisition_no}`}
                        className="h-8 px-3 rounded-md bg-orange-500 text-white text-xs font-semibold hover:bg-orange-600 flex items-center gap-1.5 transition-colors"
                      >
                        <RotateCcw size={14} /> Edit & Resubmit
                      </button>
                    )}

                    {(scope === "purchase" || scope === "purchase-order") && r.status === "pending_pr" && r.requisition_type === "product" && (
                      <>
                        <button
                          onClick={() => navigate(`/requisitions/${r.id}/file-pr`)}
                          data-testid={`btn-file-pr-${r.requisition_no}`}
                          className="h-8 px-3 rounded-md bg-amber-600 text-white text-xs font-semibold hover:bg-amber-700 flex items-center gap-1.5 transition-colors"
                        >
                          <FileText size={20} /> PR Raise
                        </button>
                        <button
                          onClick={() => cancelPR(r.id)}
                          data-testid={`btn-cancel-pr-${r.requisition_no}`}
                          className="h-8 px-3 rounded-md bg-red-600 text-white text-xs font-semibold hover:bg-red-700 flex items-center gap-1.5 transition-colors"
                        >
                          <XCircle size={14} /> Cancel PR
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

                    {r.requisition_type === "product" && (
                      <button
                        onClick={() => openPdf(r.id)}
                        data-testid={`btn-pdf-${r.requisition_no}`}
                        className="h-8 px-3 rounded-md border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5 transition-colors"
                      >
                        <FileText size={14} /> PDF
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
                          onClick={() => act(r.id, "approve")}
                          data-testid={`btn-approve-${r.requisition_no}`}
                          className="h-8 px-3 rounded-md bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 flex items-center gap-1.5 transition-colors"
                        >
                          <Check size={14} /> Approve
                        </button>
                        <button
                          onClick={() => setReviseTarget(r.id)}
                          data-testid={`btn-revise-${r.requisition_no}`}
                          className="h-8 px-3 rounded-md bg-orange-500 text-white text-xs font-semibold hover:bg-orange-600 flex items-center gap-1.5 transition-colors"
                        >
                          <RotateCcw size={14} /> Revise
                        </button>
                        <button
                          onClick={() => act(r.id, "reject")}
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
            ))}
          </tbody>
        </table>
        </div>
      </div>

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
                          <th className="px-3 py-2 text-left">Detailed Specs</th>
                          <th className="px-3 py-2 text-left">Brand</th>
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
                            <td className="px-3 py-2 text-slate-600">{it.detailed_specs || "—"}</td>
                            <td className="px-3 py-2">{it.preferred_brand || "—"}</td>
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

                <div>
                  <div className="text-xs uppercase text-slate-400 mb-2 flex items-center gap-1.5">
                    <ShieldCheck size={14} /> Approval Chain
                  </div>
                  <div className="space-y-2">
                    {detail.approval_chain.map((s, i) => (
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
                                : "rejected"
                            }
                          />
                        </div>
                        {s.note && <div className="mt-1.5 text-xs text-slate-500 italic">"{s.note}"</div>}
                      </div>
                    ))}
                  </div>
                </div>

                {(canApproveHere || detail.requisition_type === "product") && (
                  <div className="flex gap-3 pt-2">
                    {detail.requisition_type === "product" && (
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
                          onClick={() => act(detail.id, "approve")}
                          className="flex-1 py-2.5 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700 transition-colors"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => setReviseTarget(detail.id)}
                          className="flex-1 py-2.5 rounded-lg bg-orange-500 text-white font-semibold hover:bg-orange-600 transition-colors"
                        >
                          Revise
                        </button>
                        <button
                          onClick={() => act(detail.id, "reject")}
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

      <Dialog open={!!reviseTarget} onOpenChange={(o) => { if (!o) { setReviseTarget(null); setReviseNote(""); } }}>
        <DialogContent data-testid="revise-note-dialog">
          <DialogHeader><DialogTitle>Request Revision</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-600">Explain what the requester needs to fix. This note is sent back with the requisition.</p>
            <textarea
              value={reviseNote}
              onChange={(e) => setReviseNote(e.target.value)}
              rows={4}
              autoFocus
              placeholder="e.g. Please attach a vendor quote for this item…"
              data-testid="revise-note-input"
              className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm resize-none"
            />
            <div className="flex gap-3">
              <button
                onClick={submitRevise}
                data-testid="revise-note-submit"
                className="flex-1 py-2.5 rounded-lg bg-orange-500 text-white font-semibold hover:bg-orange-600 transition-colors"
              >
                Send for Revision
              </button>
              <button
                onClick={() => { setReviseTarget(null); setReviseNote(""); }}
                className="px-4 py-2.5 rounded-lg border border-slate-300 text-slate-600 font-semibold hover:bg-slate-50 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}