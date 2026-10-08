import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Eye, Check, X, Paperclip } from "lucide-react";
import api, { API, withAuthParam, formatApiErrorDetail } from "@/lib/apiClient";
import { bdt, StatusBadge } from "@/lib/status";
import { useAuth } from "@/context/AuthContext";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { showResult } from "@/components/ResultPopup";

export default function POApprovals() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const [comment, setComment] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/purchase-orders");
      // Show only POs that need action from current user
      const pending = (data || []).filter((po) => {
        const isSuper = user.role === "super_admin";
        // Server decides: stage role holders, their on-leave delegates, and escalation targets
        if (po.can_act) return true;
        // Case A high-value: MD queue
        if (po.status === "pending_md_approval" && (user.role === "md" || isSuper)) return true;
        // Final stage: Accounts Head queue
        if (po.status === "pending_accounts_head_approval" && (user.role === "accounts" || isSuper)) return true;
        // Case B low-value: Purchase Head queue
        if (po.status === "pending_purchase_head_approval") {
          const isPurchaseHead =
            user.role === "purchase_head" ||
            (user.role === "dept_head" && (user.department_name === "Purchase" || user.department_code === "PUR"));
          if (isSuper || isPurchaseHead) return true;
        }
        return false;
      });
      setRows(pending);
    } catch (e) {
      console.error(e);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { load(); }, [load]);

  const act = async (poId, action) => {
    try {
      await api.post(`/purchase-orders/${poId}/action`, { action, comment: comment || null });
      showResult(action === "approve"
        ? { title: "Done!", message: "The Purchase Order has been approved successfully." }
        : { kind: "reject", title: "Rejected", message: "The Purchase Order has been rejected." });
      setDetail(null);
      setComment("");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">PO Approvals</h2>
        <p className="text-slate-500 text-sm mt-1">Purchase Orders waiting for your approval</p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
              <th className="px-6 py-3 font-semibold">PO Number</th>
              <th className="px-6 py-3 font-semibold">Vendor</th>
              <th className="px-6 py-3 font-semibold">Grand Total</th>
              <th className="px-6 py-3 font-semibold">Status</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={5} className="px-6 py-8 text-center text-slate-400">Loading…</td></tr>}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={5} className="px-6 py-10 text-center text-slate-400">No Purchase Orders awaiting your approval.</td></tr>
            )}
            {rows.map((po) => (
              <tr key={po.id} className="border-b border-slate-50 hover:bg-slate-50/60">
                <td className="px-6 py-3 font-mono font-medium">{po.po_number}</td>
                <td className="px-6 py-3">{po.vendor_name}</td>
                <td className="px-6 py-3 font-mono">{bdt(po.grand_total)}</td>
                <td className="px-6 py-3">
                  <StatusBadge status={po.status} />
                </td>
                <td className="px-6 py-3 text-right">
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={() => setDetail(po)}
                      className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs font-semibold hover:bg-slate-50 flex items-center gap-1.5"
                    >
                      <Eye size={14} /> View & Decide
                    </button>
                    <button
                      onClick={() => navigate(`/purchase/orders/${po.id}`)}
                      className="px-3 py-1.5 rounded-lg border border-blue-300 text-blue-600 text-xs font-semibold hover:bg-blue-50"
                    >
                      Open Form
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Detail + Approve/Reject Dialog */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-w-3xl">
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle className="font-mono">{detail.po_number} — {detail.vendor_name}</DialogTitle>
              </DialogHeader>

              <div className="space-y-4 max-h-[65vh] overflow-y-auto">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div><span className="text-slate-400">Grand Total:</span> <strong className="font-mono">{bdt(detail.grand_total)}</strong></div>
                  <div><span className="text-slate-400">Status:</span> {detail.status.replace(/_/g, " ")}</div>
                  <div><span className="text-slate-400">Payment Terms:</span> {detail.payment_terms || "—"}</div>
                  <div><span className="text-slate-400">Delivery:</span> {detail.delivery_location || "—"}</div>
                </div>

                <div>
                  <div className="text-xs uppercase text-slate-400 mb-2">Line Items</div>
                  <table className="w-full text-sm border">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="px-3 py-2 text-left">Product</th>
                        <th className="px-3 py-2 text-left">Description</th>
                        <th className="px-3 py-2 text-left">Brand</th>
                        <th className="px-3 py-2 text-right">Qty</th>
                        <th className="px-3 py-2 text-right">Unit Price</th>
                        <th className="px-3 py-2 text-right">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.items || []).map((it, i) => (
                        <tr key={i} className="border-t">
                          <td className="px-3 py-2 font-medium">{it.product_name || "—"}</td>
                          <td className="px-3 py-2 text-slate-600">{it.item_description && it.item_description !== it.product_name ? it.item_description : "—"}</td>
                          <td className="px-3 py-2">{it.brand_model || "—"}</td>
                          <td className="px-3 py-2 text-right">{it.quantity}</td>
                          <td className="px-3 py-2 text-right font-mono">{bdt(it.unit_price)}</td>
                          <td className="px-3 py-2 text-right font-mono">{bdt(it.line_total || it.quantity * it.unit_price)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div>
                  <div className="text-xs uppercase text-slate-400 mb-2">Attachments (Vendor Quotations)</div>
                  {(detail.cs_attachments || []).length === 0 ? (
                    <p className="text-sm text-slate-400">No files attached.</p>
                  ) : (
                    <ul className="space-y-1">
                      {detail.cs_attachments.map((a) => (
                        <li key={a.id}>
                          <a href={withAuthParam(`${API}/files/${a.id}/download`)} target="_blank" rel="noreferrer"
                             className="text-sm text-blue-600 hover:underline flex items-center gap-2" data-testid={`po-attachment-${a.id}`}>
                            <Paperclip size={14} /> {a.name}
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div>
                  <label className="text-sm text-slate-600">Comment (optional)</label>
                  <textarea
                    className="w-full border rounded-lg p-2 mt-1 text-sm"
                    rows={2}
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="Approval / rejection note…"
                  />
                </div>

                <div className="flex gap-3 pt-2">
                  <button
                    onClick={() => act(detail.id, "approve")}
                    className="flex-1 py-2.5 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700 flex items-center justify-center gap-2"
                  >
                    <Check size={16} /> Approve
                  </button>
                  <button
                    onClick={() => act(detail.id, "reject")}
                    className="flex-1 py-2.5 rounded-lg bg-red-600 text-white font-semibold hover:bg-red-700 flex items-center justify-center gap-2"
                  >
                    <X size={16} /> Reject
                  </button>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}