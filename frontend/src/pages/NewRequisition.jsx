import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  ClipboardList, Plus, Trash2, Package, ShieldCheck, User, Calendar,
  Paperclip, CheckCircle2, ArrowRight, Zap,
} from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { bdt } from "@/lib/status";

export default function NewRequisition() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [reqType, setReqType] = useState("product");
  const [productType, setProductType] = useState("asset");
  const [productName, setProductName] = useState("");
  const [qty, setQty] = useState(1);
  const [rate, setRate] = useState("");
  const [remarks, setRemarks] = useState("");

  const [items, setItems] = useState([]);
  const [note, setNote] = useState("");
  const [attachment, setAttachment] = useState("");
  const [reqDate, setReqDate] = useState(new Date().toISOString().slice(0, 10));
  const [reqNo, setReqNo] = useState("REQ-2026-XXXX");
  const [chain, setChain] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  const total = useMemo(
    () => items.reduce((s, it) => s + it.quantity * it.rate, 0),
    [items]
  );

  useEffect(() => {
    // preview req number placeholder based on year
    setReqNo(`REQ-${new Date().getFullYear()}-${String(Math.floor(Math.random() * 9000) + 1000)}`);
  }, []);

  useEffect(() => {
    api.post("/requisitions/preview-chain", { requisition_type: reqType, total_amount: total })
      .then(({ data }) => setChain(data.chain))
      .catch(() => setChain([]));
  }, [reqType, total]);

  const addItem = () => {
    if (!productName.trim()) return toast.error("Enter a product/service name");
    if (qty < 1) return toast.error("Quantity must be at least 1");
    setItems((prev) => [
      ...prev,
      { product_type: productType, product_name: productName.trim(), quantity: Number(qty), rate: Number(rate) || 0, remarks: remarks.trim() || null },
    ]);
    setProductName(""); setQty(1); setRate(""); setRemarks("");
    toast.success("Item added");
  };

  const removeItem = (i) => setItems((prev) => prev.filter((_, idx) => idx !== i));

  const submit = async () => {
    if (items.length === 0) return toast.error("Add at least one item");
    setSubmitting(true);
    try {
      const { data } = await api.post("/requisitions", {
        requisition_type: reqType,
        requisition_for: user?.name,
        items,
        requester_note: note || null,
        attachment_path: attachment || null,
        requisition_date: reqDate,
      });
      toast.success(`Requisition ${data.requisition_no} submitted`);
      navigate("/requisitions/pending");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="new-requisition-page">
      {/* Header card */}
      <div className="rounded-2xl bg-[#0C1733] text-white p-6 flex flex-col lg:flex-row lg:items-center gap-6 justify-between">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-amber-600 flex items-center justify-center">
            <ClipboardList size={24} />
          </div>
          <div>
            <div className="font-head font-bold text-xl tracking-wide">NEW REQUISITION FORM</div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="bg-white/5 rounded-lg px-4 py-2 border border-white/10">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">Requisition No.</div>
            <div className="font-mono font-semibold text-amber-400" data-testid="req-no">{reqNo}</div>
          </div>
          <div className="bg-white/5 rounded-lg px-4 py-2 border border-white/10 flex items-center gap-2">
            <User size={16} className="text-slate-400" />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Requisitioner</div>
              <div className="font-semibold text-sm">{user?.name} · {user?.department_name || "—"}</div>
            </div>
          </div>
          <div className="bg-white/5 rounded-lg px-4 py-2 border border-white/10 flex items-center gap-2">
            <Calendar size={16} className="text-slate-400" />
            <input type="date" value={reqDate} onChange={(e) => setReqDate(e.target.value)}
              className="bg-transparent text-sm outline-none" data-testid="req-date" />
          </div>
        </div>
      </div>

      {/* Item entry */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
        <div className="grid grid-cols-1 md:grid-cols-6 gap-4 items-end">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Requisition Type *</label>
            <select value={reqType} onChange={(e) => setReqType(e.target.value)} data-testid="input-req-type"
              className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm">
              <option value="product">Product Requisition</option>
              <option value="service">Service Requisition</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Product Type *</label>
            <select value={productType} onChange={(e) => setProductType(e.target.value)} data-testid="input-product-type"
              className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm">
              <option value="asset">Asset</option>
              <option value="consumable">Consumable</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Product Name *</label>
            <input value={productName} onChange={(e) => setProductName(e.target.value)} placeholder="e.g. Dell Monitor" data-testid="input-product-name"
              className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm" />
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Quantity *</label>
            <input type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} data-testid="input-qty"
              className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm" />
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Rate (BDT)</label>
            <input type="number" min="0" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="0" data-testid="input-rate"
              className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm" />
          </div>
          <button onClick={addItem} data-testid="btn-add-product"
            className="py-2.5 px-4 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center justify-center gap-2 transition-colors">
            <Plus size={16} /> Add Product
          </button>
        </div>
        <div className="mt-4">
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Remarks</label>
          <input value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Optional note for this item…" data-testid="input-remarks"
            className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm" />
        </div>
      </div>

      {/* Items table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2"><Package size={18} className="text-slate-400" /><h3 className="font-head font-semibold text-slate-900">Requisition Items</h3></div>
          <div className="font-mono text-sm text-slate-700">Total: <span className="font-semibold text-slate-900" data-testid="items-total">{bdt(total)}</span></div>
        </div>
        {items.length === 0 ? (
          <div className="py-12 text-center text-slate-400" data-testid="items-empty">
            <Package size={32} className="mx-auto mb-3 opacity-50" />
            No products added yet. Use the form above to add products to this requisition.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100">
                <th className="px-6 py-3 font-semibold">Product</th>
                <th className="px-6 py-3 font-semibold">Type</th>
                <th className="px-6 py-3 font-semibold">Qty</th>
                <th className="px-6 py-3 font-semibold">Rate</th>
                <th className="px-6 py-3 font-semibold">Line Total</th>
                <th className="px-6 py-3 font-semibold">Remarks</th>
                <th className="px-6 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i} className="border-b border-slate-50" data-testid={`item-row-${i}`}>
                  <td className="px-6 py-3 font-medium text-slate-800">{it.product_name}</td>
                  <td className="px-6 py-3 capitalize text-slate-600">{it.product_type}</td>
                  <td className="px-6 py-3 font-mono">{it.quantity}</td>
                  <td className="px-6 py-3 font-mono">{bdt(it.rate)}</td>
                  <td className="px-6 py-3 font-mono font-semibold">{bdt(it.quantity * it.rate)}</td>
                  <td className="px-6 py-3 text-slate-500">{it.remarks || "—"}</td>
                  <td className="px-6 py-3 text-right">
                    <button onClick={() => removeItem(i)} data-testid={`btn-remove-item-${i}`} className="text-slate-400 hover:text-red-600 transition-colors"><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Bottom grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Approval priority */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm p-6">
          <div className="flex items-center gap-2 mb-1"><ShieldCheck size={18} className="text-amber-600" /><h3 className="font-head font-semibold text-slate-900">Approval Priority</h3></div>
          <p className="text-sm text-slate-500 mb-5">
            {reqType === "service"
              ? "Service requisitions route directly to the IT Department Head (bypassing Dept Head & Accounts)."
              : "Only your Department Head is selected automatically — the rest of the chain (IT Head, Accounts, MD, Purchase Head as needed) is routed once they approve."}
          </p>
          <div className="space-y-3" data-testid="approval-chain">
            {chain.map((s, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="rounded-lg border border-amber-200 bg-amber-50/60 flex-1 px-4 py-3 flex items-center justify-between" data-testid={`chain-step-${i}`}>
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-full bg-amber-600 text-white flex items-center justify-center text-xs font-bold">{s.level}</div>
                    <div>
                      <div className="text-[11px] uppercase tracking-wider text-amber-700 font-semibold">Level {String(s.level).padStart(2, "0")} — {s.label}</div>
                      <div className="font-semibold text-slate-800">{s.approver_name || <span className="text-red-500 italic">No approver configured</span>}</div>
                    </div>
                  </div>
                  {i === 0 && reqType !== "service" && <span className="text-[11px] text-slate-400">Auto-assigned</span>}
                  {reqType === "service" && <Zap size={16} className="text-amber-600" />}
                </div>
                {i < chain.length - 1 && <ArrowRight size={16} className="text-slate-300 shrink-0" />}
              </div>
            ))}
            {total >= 50000 && reqType === "product" && (
              <div className="text-xs text-purple-700 bg-purple-50 border border-purple-200 rounded-lg px-3 py-2" data-testid="md-threshold-note">
                Total is ≥ 50,000 BDT — Managing Director approval has been added to the chain.
              </div>
            )}
          </div>
        </div>

        {/* Attachments & notes */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
          <div className="flex items-center gap-2 mb-4"><Paperclip size={18} className="text-slate-400" /><h3 className="font-head font-semibold text-slate-900">Attachments &amp; Notes</h3></div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Attachment (Optional)</label>
          <input type="file" data-testid="input-attachment" onChange={(e) => setAttachment(e.target.files?.[0]?.name || "")}
            className="w-full text-sm mb-1 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-slate-100 file:text-slate-700 file:font-medium" />
          <p className="text-xs text-slate-400 mb-4">{attachment || "No file selected"}</p>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Requester Note (Optional)</label>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={4} placeholder="Add any additional note…" data-testid="input-requester-note"
            className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm resize-none" />
        </div>
      </div>

      <div className="flex items-center justify-end gap-3">
        <button onClick={() => navigate(-1)} data-testid="btn-cancel"
          className="px-5 py-2.5 rounded-lg border border-slate-300 text-slate-600 font-semibold text-sm hover:bg-slate-50 transition-colors">Cancel</button>
        <button onClick={submit} disabled={submitting} data-testid="btn-submit-requisition"
          className="px-6 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 transition-colors disabled:opacity-60">
          <CheckCircle2 size={18} /> Submit Requisition
        </button>
      </div>
    </div>
  );
}
