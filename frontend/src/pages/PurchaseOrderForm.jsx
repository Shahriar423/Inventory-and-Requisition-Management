import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft, Plus, Trash2, Save, Send, AlertTriangle,
} from "lucide-react";
import api, { API, withAuthParam, formatApiErrorDetail } from "@/lib/apiClient";
import { bdt } from "@/lib/status";
import { showResult } from "@/components/ResultPopup";

const PAYMENT_TERMS = [
  "50% Advance & 50% After Delivery",
  "100% After Delivery",
  "Net 30",
  "100% Advance",
];
const DELIVERY_LOCATIONS = [
  "Head Office",
  "PIL-Chittagong",
  "Zara non-woven-Gazipur",
  "Fardin",
];

/**
 * Online Purchase Order (PO) Form
 * Matches the official light-theme design screenshot exactly.
 * Grand-total-driven routing (MD → Accounts when > 50k BDT).
 */
export default function PurchaseOrderForm() {
  const { id: routePoId } = useParams();
  const [searchParams] = useSearchParams();
  const linkedPrFromQuery = searchParams.get("pr") || "";
  const navigate = useNavigate();

  const [loading, setLoading] = useState(!!routePoId);
  const [submitting, setSubmitting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [poId, setPoId] = useState(routePoId || null);

  const [header, setHeader] = useState({
    po_number: "PO-AUTO",
    linked_pr_id: linkedPrFromQuery,
    po_date: new Date().toISOString().slice(0, 10),
    target_delivery: "",
    payment_terms: "50% Advance & 50% After Delivery",
  });

  const [vendor, setVendor] = useState({
    vendor_name: "",
    contact_person: "",
    vendor_email: "",
    bin_tin: "",
  });
  const [shipment, setShipment] = useState({
    delivery_location: "Main Store (Dhaka Office)",
    attention_to: "",
  });

  const [items, setItems] = useState([
    { product_name: "", item_description: "", brand_model: "", quantity: 1, unit_price: "" },
  ]);

  const [financial, setFinancial] = useState({
    tax_percent: 5,
    discount_amount: 0,
    transport_charge: 0,
  });

  const [notes, setNotes] = useState("");
  const [prNeed, setPrNeed] = useState(null);   // { required_by, urgency } from the linked PR
  const [files, setFiles] = useState([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);

  // Blank form: show the number this PO will get instead of a "PO-AUTO" placeholder.
  useEffect(() => {
    if (routePoId) return;
    api.get("/purchase-orders/next-number")
      .then(({ data }) => setHeader((h) => ({ ...h, po_number: data.po_number })))
      .catch(() => {});
  }, [routePoId]);

  useEffect(() => {
    if (!routePoId) return;
    setLoading(true);
    api.get(`/purchase-orders/${routePoId}`)
      .then(({ data }) => {
        setPoId(data.id);
        setHeader({
          po_number: data.po_number || "PO-AUTO",
          linked_pr_id: data.requisition_id || "",
          po_date: (data.po_date || data.created_at || "").slice(0, 10),
          target_delivery: (data.delivery_date || "").slice(0, 10),
          payment_terms: data.payment_terms || "50% Advance & 50% After Delivery",
        });
        setVendor({
          vendor_name: data.vendor_name || "",
          contact_person: data.contact_person || "",
          vendor_email: data.vendor_email || "",
          bin_tin: data.bin_tin || "",
        });
        setShipment({
          delivery_location: data.delivery_location || "Main Store (Dhaka Office)",
          attention_to: data.attention_to || "",
        });
        setItems((data.items || []).map((it) => ({
          product_name: it.product_name || "",
          locked: !!it.product_name,
          item_description: it.item_description && it.item_description !== it.product_name ? it.item_description : "",
          brand_model: it.brand_model || it.specification || "",
          quantity: it.quantity || 1,
          unit_price: it.unit_price || "",
        })));
        setFinancial({
          tax_percent: data.tax_percent ?? 5,
          discount_amount: data.discount_amount ?? 0,
          transport_charge: data.transport_charge ?? data.transport_fee ?? 0,
        });
        setNotes(data.special_terms_notes || "");
        setPrNeed({ required_by: data.required_by_date || "", urgency: data.urgency_level || "" });
        setFiles((data.cs_attachments || []).map((a) => ({ id: a.id, name: a.name })));
      })
      .catch(() => toast.error("Could not load Purchase Order"))
      .finally(() => setLoading(false));
  }, [routePoId]);

  // Product catalog — used for rows added by hand (rows seeded from the requisition are locked).
  const [catalog, setCatalog] = useState([]);
  useEffect(() => { api.get("/products").then(({ data }) => setCatalog(data)).catch(() => {}); }, []);

  // New PO: pre-fill the lines from the linked requisition. Product name comes across locked
  // (exact catalog spelling); the description is left empty for the PO creator to write.
  useEffect(() => {
    if (routePoId || !linkedPrFromQuery) return;
    api.get(`/requisitions/${linkedPrFromQuery}`)
      .then(({ data }) => {
        const rows = (data.items || []).map((it) => ({
          product_name: it.product_name || "",
          locked: true,
          item_description: "",                // written by the PO creator
          brand_model: it.preferred_brand || "",
          quantity: it.quantity || 1,
          unit_price: "",
        }));
        if (rows.length) setItems(rows);
        const rb = (data.required_by_date || "").slice(0, 10);
        setPrNeed({ required_by: rb, urgency: data.urgency_level || "" });
        // Target Delivery defaults to the date the requester needs it by (still editable).
        if (rb) setHeader((h) => (h.target_delivery ? h : { ...h, target_delivery: rb }));
      })
      .catch(() => {});
    // eslint-disable-next-line
  }, [routePoId, linkedPrFromQuery]);

  const totals = useMemo(() => {
    const sub = items.reduce((s, it) => s + (Number(it.quantity) || 0) * (Number(it.unit_price) || 0), 0);
    const tax = sub * ((Number(financial.tax_percent) || 0) / 100);
    const grand = sub + tax - (Number(financial.discount_amount) || 0) + (Number(financial.transport_charge) || 0);
    return {
      sub_total: Math.round(sub * 100) / 100,
      total_tax: Math.round(tax * 100) / 100,
      grand_total: Math.round(grand * 100) / 100,
    };
  }, [items, financial]);

  const needsMd = totals.grand_total > 50000;

  const buildPayload = () => ({
    requisition_id: header.linked_pr_id,
    vendor_name: vendor.vendor_name,
    contact_person: vendor.contact_person || null,
    vendor_email: vendor.vendor_email || null,
    bin_tin: vendor.bin_tin || null,
    delivery_location: shipment.delivery_location || null,
    attention_to: shipment.attention_to || null,
    delivery_date: header.target_delivery || null,
    payment_terms: header.payment_terms || null,
    po_date: header.po_date || null,
    items: items.map((it) => ({
      product_name: it.product_name || null,
      item_description: it.item_description,
      brand_model: it.brand_model || null,
      quantity: Number(it.quantity) || 1,
      unit_price: Number(it.unit_price) || 0,
    })),
    tax_percent: Number(financial.tax_percent) || 5,
    discount_amount: Number(financial.discount_amount) || 0,
    transport_charge: Number(financial.transport_charge) || 0,
    special_terms_notes: notes || null,
    cs_attachment_file_ids: files.map((f) => f.id),
  });

  const saveDraft = async () => {
    if (uploadingFiles) return toast.error("Please wait — attachment is still uploading");
    if (!header.linked_pr_id) return toast.error("Linked PR ID is required");
    if (!vendor.vendor_name.trim()) return toast.error("Vendor Name is required");
    if (items.some((it) => !(it.product_name || "").trim())) {
      return toast.error("Every line item needs a product");
    }
    if (items.some((it) => !it.item_description.trim())) {
      return toast.error("Every line item needs a description");
    }
    setSaving(true);
    try {
      if (poId) {
        toast.success("Draft changes noted");
      } else {
        const { data } = await api.post("/purchase-orders", buildPayload());
        setPoId(data.id);
        setHeader((h) => ({ ...h, po_number: data.po_number }));
        toast.success(`Draft PO ${data.po_number} created`);
      }
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const submitForApproval = async () => {
    if (uploadingFiles) return toast.error("Please wait — attachment is still uploading");
    if (!header.linked_pr_id) return toast.error("Linked PR ID is required");
    if (!vendor.vendor_name.trim()) return toast.error("Vendor Name is required");
    if (items.some((it) => !(it.product_name || "").trim() || !it.item_description.trim() || !(Number(it.unit_price) > 0))) {
      return toast.error("Every line item needs a product, description and unit price");
    }
    setSubmitting(true);
    try {
      let id = poId;
      if (!id) {
        const { data } = await api.post("/purchase-orders", buildPayload());
        id = data.id;
        setPoId(id);
        setHeader((h) => ({ ...h, po_number: data.po_number }));
      }
      await api.post(`/purchase-orders/${id}/submit`);
      showResult({
        title: "Done!",
        message: needsMd
          ? `Purchase Order submitted. Grand total ${bdt(totals.grand_total)} → pending MD approval.`
          : `Purchase Order submitted. Grand total ${bdt(totals.grand_total)} → bypassed MD, pending Accounts approval.`,
        onClose: () => navigate("/requisitions/purchase-order"),
      });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="py-20 text-center text-slate-400">Loading…</div>;

  return (
    <div className="max-w-5xl mx-auto space-y-4" data-testid="purchase-order-form">
      <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft size={15} /> Back
      </button>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-wider">Purchase Department | Create Purchase Order</p>
          <h1 className="text-xl font-semibold text-slate-900">Online Purchase Order (PO) Form</h1>
        </div>
        <span className={`text-xs px-3 py-1.5 rounded-full font-medium flex items-center gap-1.5 ${
          needsMd ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"
        }`}>
          <AlertTriangle size={13} />
          {needsMd
            ? "Routing: Requires MD Approval → Accounts Approval"
            : "Routing: Direct to Accounts Approval (≤ 50,000 BDT)"}
        </span>
      </div>

      {/* 1. Header Information */}
      <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <h2 className="font-semibold text-slate-800 mb-3">1. Header Information</h2>
        {prNeed && (
          <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-900" data-testid="po-pr-need">
            <span>PR Required By: <b data-testid="po-pr-required-by">{prNeed.required_by || "not specified"}</b></span>
            <span>Urgency: <b>{prNeed.urgency || "—"}</b></span>
          </div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3 text-sm">
          <Field label="PO Number" value={header.po_number} readOnly />
          <Field
            label="Linked PR ID"
            value={header.linked_pr_id}
            onChange={(v) => setHeader({ ...header, linked_pr_id: v })}
            placeholder="PR-10045 (e.g. IT Equipment)"
          />
          <Field
            label="PO Date"
            type="date"
            value={header.po_date}
            onChange={(v) => setHeader({ ...header, po_date: v })}
          />
          <Field
            label="Target Delivery"
            type="date"
            value={header.target_delivery}
            onChange={(v) => setHeader({ ...header, target_delivery: v })}
          />
          <div>
            <label className="block text-xs text-slate-500 mb-0.5">Payment Terms</label>
            <select
              value={header.payment_terms}
              onChange={(e) => setHeader({ ...header, payment_terms: e.target.value })}
              className="w-full border border-slate-300 rounded-lg px-2.5 py-1.5 text-sm"
            >
              {PAYMENT_TERMS.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
        </div>
      </section>

      {/* 2. Vendor & Shipment */}
      <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm grid md:grid-cols-2 gap-6">
        <div>
          <h2 className="font-semibold text-slate-800 mb-3">2. Vendor &amp; Shipment Details</h2>
          <div className="space-y-2.5 text-sm">
            <Field label="Vendor Name" value={vendor.vendor_name} onChange={(v) => setVendor({ ...vendor, vendor_name: v })} placeholder="Search vendor…" />
            <Field label="Contact Person" value={vendor.contact_person} onChange={(v) => setVendor({ ...vendor, contact_person: v })} />
            <Field label="Email" value={vendor.vendor_email} onChange={(v) => setVendor({ ...vendor, vendor_email: v })} />
            <Field label="BIN / TIN" value={vendor.bin_tin} onChange={(v) => setVendor({ ...vendor, bin_tin: v })} />
          </div>
        </div>
        <div>
          <h3 className="font-medium text-slate-600 mb-3">Shipment Details</h3>
          <div className="space-y-2.5 text-sm">
            <div>
              <label className="block text-xs text-slate-500 mb-0.5">Delivery Location</label>
              <select
                value={shipment.delivery_location}
                onChange={(e) => setShipment({ ...shipment, delivery_location: e.target.value })}
                className="w-full border border-slate-300 rounded-lg px-2.5 py-1.5 text-sm"
              >
                {DELIVERY_LOCATIONS.map((l) => <option key={l}>{l}</option>)}
              </select>
            </div>
            <Field label="Attention To" value={shipment.attention_to} onChange={(v) => setShipment({ ...shipment, attention_to: v })} placeholder="Store In-Charge / IT Manager" />
          </div>
        </div>
      </section>

      {/* 3. Line Items */}
      <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <div className="flex justify-between items-center mb-3">
          <h2 className="font-semibold text-slate-800">3. Line Items Table</h2>
          <button
            onClick={() => setItems([...items, { product_name: "", item_description: "", brand_model: "", quantity: 1, unit_price: "" }])}
            className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1 font-medium"
          >
            <Plus size={14} /> Add Item
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[1000px]">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">SI</th>
                <th className="px-3 py-2 text-left font-semibold">Product</th>
                <th className="px-3 py-2 text-left font-semibold">Item Description / Specification</th>
                <th className="px-3 py-2 text-left font-semibold">Brand / Model</th>
                <th className="px-3 py-2 text-left font-semibold">Qty</th>
                <th className="px-3 py-2 text-left font-semibold">Unit Price (BDT)</th>
                <th className="px-3 py-2 text-right font-semibold">Total Price (BDT)</th>
                <th className="px-3 py-2 w-10" />
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i} className="border-t border-slate-100" data-testid={`po-item-row-${i}`}>
                  <td className="px-3 py-2 text-slate-500">{i + 1}</td>
                  <td className="px-3 py-2">
                    {it.locked ? (
                      <input
                        className="w-40 bg-slate-50 border border-slate-200 rounded px-2 py-1.5 text-sm font-medium text-slate-800 cursor-not-allowed"
                        value={it.product_name} readOnly title="From the requisition"
                        data-testid={`po-item-product-${i}`}
                      />
                    ) : (
                      <select
                        className="w-40 border border-slate-300 rounded px-2 py-1.5 text-sm bg-white"
                        value={it.product_name}
                        onChange={(e) => { const n = [...items]; n[i].product_name = e.target.value; setItems(n); }}
                        data-testid={`po-item-product-${i}`}
                      >
                        <option value="">Select product…</option>
                        {catalog.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
                      </select>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <textarea
                      rows={3}
                      className="w-full min-w-[340px] min-h-[76px] border border-slate-300 rounded px-2 py-1.5 text-sm resize focus:outline-none focus:ring-1 focus:ring-amber-500"
                      value={it.item_description}
                      onChange={(e) => {
                        const n = [...items]; n[i].item_description = e.target.value; setItems(n);
                      }}
                      placeholder="e.g. Logitech K380, wireless, Bluetooth"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      className="w-32 border border-slate-300 rounded px-2 py-1.5 text-sm"
                      value={it.brand_model}
                      onChange={(e) => {
                        const n = [...items]; n[i].brand_model = e.target.value; setItems(n);
                      }}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      min={1}
                      className="w-16 border border-slate-300 rounded px-2 py-1.5 text-sm"
                      value={it.quantity}
                      onChange={(e) => {
                        const n = [...items]; n[i].quantity = e.target.value; setItems(n);
                      }}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      className="w-28 border border-slate-300 rounded px-2 py-1.5 text-sm"
                      value={it.unit_price}
                      placeholder="0"
                      onChange={(e) => {
                        const n = [...items]; n[i].unit_price = e.target.value; setItems(n);
                      }}
                    />
                  </td>
                  <td className="px-3 py-2 text-right font-mono font-medium">
                    {((Number(it.quantity) || 0) * (Number(it.unit_price) || 0)).toLocaleString()}
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => setItems(items.filter((_, idx) => idx !== i))} className="text-red-500 hover:text-red-600">
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 4. Financial Summary */}
      <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm flex justify-end">
        <div className="w-80 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-600">Subtotal Amount</span>
            <span className="font-mono font-medium">BDT {totals.sub_total.toLocaleString()}</span>
          </div>
          <div className="flex justify-between items-center gap-2">
            <span className="text-slate-600">Tax / VAT</span>
            <div className="flex items-center gap-1">
              <input
                type="number"
                min={0}
                className="w-14 border border-slate-300 rounded px-1.5 py-0.5 text-right text-sm"
                value={financial.tax_percent}
                onChange={(e) => setFinancial({ ...financial, tax_percent: e.target.value })}
              />
              <span className="text-slate-400">%</span>
            </div>
            <span className="font-mono">BDT {totals.total_tax.toLocaleString()}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-600">Discount Amount (BDT)</span>
            <input
              type="number"
              min={0}
              className="w-28 border border-slate-300 rounded px-2 py-0.5 text-right text-sm"
              value={financial.discount_amount}
              onChange={(e) => setFinancial({ ...financial, discount_amount: e.target.value })}
            />
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-600">Transport Charge</span>
            <input
              type="number"
              min={0}
              className="w-28 border border-slate-300 rounded px-2 py-0.5 text-right text-sm"
              value={financial.transport_charge}
              onChange={(e) => setFinancial({ ...financial, transport_charge: e.target.value })}
            />
          </div>
          <div className="flex justify-between items-center font-bold text-base border-t border-slate-200 pt-2 mt-1 bg-blue-50 -mx-2 px-2 py-1.5 rounded">
            <span>GRAND TOTAL</span>
            <span className="font-mono text-blue-800">BDT {totals.grand_total.toLocaleString()}</span>
          </div>
        </div>
      </section>

      {/* 5. Attachments & Notes */}
      <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <h2 className="font-semibold text-slate-800 mb-3">5. Attachments &amp; Notes</h2>
        <div className="border-2 border-dashed border-slate-300 rounded-lg p-6 text-center text-slate-500 mb-3">
          <p className="text-sm">Upload Vendor Quotation PDF (Drag &amp; Drop or Browse)</p>
          <input type="file" multiple accept=".pdf" className="hidden" id="po-quote-files"
            onChange={async (e) => {
              const picked = Array.from(e.target.files || []);
              e.target.value = "";
              if (picked.length === 0) return;
              setUploadingFiles(true);
              for (const f of picked) {
                try {
                  const fd = new FormData();
                  fd.append("file", f);
                  const { data } = await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
                  setFiles((p) => [...p, { id: data.id, name: data.original_filename || f.name }]);
                } catch (err) {
                  toast.error(`${f.name}: ${formatApiErrorDetail(err.response?.data?.detail) || "Upload failed"}`);
                }
              }
              setUploadingFiles(false);
            }}
          />
          <label htmlFor="po-quote-files" className="inline-block mt-2 text-blue-600 cursor-pointer text-sm font-medium hover:underline">
            {uploadingFiles ? "Uploading…" : "Browse files"}
          </label>
          {files.length > 0 && (
            <ul className="mt-2 text-xs text-left max-w-md mx-auto space-y-1">
              {files.map((f) => (
                <li key={f.id} className="flex justify-between bg-slate-50 px-2 py-1 rounded">
                  <a href={withAuthParam(`${API}/files/${f.id}/download`)} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline truncate">{f.name}</a>
                  <button onClick={() => setFiles((p) => p.filter((x) => x.id !== f.id))} className="text-red-500">×</button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <label className="block text-sm text-slate-600 mb-1">Special Terms &amp; Notes</label>
        <textarea
          className="w-full border border-slate-300 rounded-lg p-2.5 text-sm h-20"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Any special terms, warranty notes, or delivery conditions…"
        />
      </section>

      {/* Actions */}
      <div className="flex flex-wrap justify-end gap-3 pb-8">
        <button
          onClick={saveDraft}
          disabled={saving}
          className="px-4 py-2.5 rounded-lg border border-slate-300 text-slate-700 font-medium text-sm flex items-center gap-2 hover:bg-slate-50 disabled:opacity-50"
        >
          <Save size={16} /> Save Draft
        </button>
        <button
          onClick={submitForApproval}
          disabled={submitting}
          data-testid="btn-submit-po"
          className="px-5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm flex items-center gap-2 disabled:opacity-50"
        >
          <Send size={16} /> Submit PO for Approval
        </button>
        <button onClick={() => navigate(-1)} className="px-4 py-2.5 text-slate-500 text-sm hover:text-slate-700">
          Cancel
        </button>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, type = "text", readOnly, placeholder }) {
  return (
    <div>
      <label className="block text-xs text-slate-500 mb-0.5">{label}</label>
      <input
        type={type}
        value={value || ""}
        readOnly={readOnly}
        placeholder={placeholder}
        onChange={(e) => onChange?.(e.target.value)}
        className={`w-full border border-slate-300 rounded-lg px-2.5 py-1.5 text-sm ${readOnly ? "bg-slate-50 text-slate-600" : ""}`}
      />
    </div>
  );
}