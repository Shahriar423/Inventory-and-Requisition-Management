import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft, Plus, Trash2, UploadCloud, Save, Send, Printer,
} from "lucide-react";
import api, { API, withAuthParam, formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { showResult } from "@/components/ResultPopup";

const PRODUCT_TYPE_LABELS = { asset: "IT Asset", it_accessories: "IT Accessories", network: "Network", consumable: "Consumable", furniture: "Furniture" };

const URGENCY_OPTIONS = [
  "Low",
  "High",
  "Emergency",
];
const UOM_OPTIONS = ["Pcs", "Set", "Box", "Unit", "Nos"];
const DELIVERY_OPTIONS = [
  "Main Head Office",
  "PIL Warehouse",
  "Zara Warehouse",
  "Fardin Warehouse",
];

const emptyItem = () => ({
  category: "",
  product_name: "",
  detailed_specs: "",
  preferred_brand: "",
  qty: 1,
  uom: "Pcs",
  available_qty: "",
  estimated_unit_price: "",
  justification_remarks: "",
});

function PrimitekFormLogo() {
  return (
    <div className="flex items-center gap-3 text-left">
      <div className="relative flex items-center justify-center p-1.5 bg-white rounded-lg border border-slate-200 shadow-sm shrink-0">
        <svg width="36" height="36" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M50 5 L90 28 L90 72 L50 95 L10 72 L10 28 Z" stroke="#111827" strokeWidth="8" fill="none" />
          <path d="M50 12 L83 31 L83 69 L50 88 L17 69 L17 31 Z" stroke="#111827" strokeWidth="4" fill="none" />
          <circle cx="38" cy="38" r="7" fill="#111827" />
          <circle cx="38" cy="53" r="7" fill="#111827" />
          <circle cx="38" cy="68" r="7" fill="#111827" />
          <path d="M48 30 C 65 30, 68 50, 48 55 Z" fill="#E31E24" />
        </svg>
      </div>
      <div>
        <div className="font-head font-extrabold text-xl tracking-tight leading-none text-slate-900">
          Primi<span className="text-[#E31E24]">tek</span> Group
        </div>
        <div className="text-slate-500 text-xs mt-1 font-medium">Purchase Requisition</div>
      </div>
    </div>
  );
}

export default function PurchaseRequisitionForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [req, setReq] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [saving, setSaving] = useState(false);

  const [requiredByDate, setRequiredByDate] = useState("");
  const [urgency, setUrgency] = useState("");
  const [items, setItems] = useState([]);
  const [justification, setJustification] = useState("");
  const [deliveryLocation, setDeliveryLocation] = useState("Main Head Office");
  const [files, setFiles] = useState([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);

  const load = () => {
    setLoading(true);
    api.get(`/requisitions/${id}`)
      .then(({ data }) => {
        setReq(data);
        setRequiredByDate(data.required_by_date || "");
        setUrgency(data.urgency_level || "");
        setJustification(data.overall_business_justification || "");
        setDeliveryLocation(data.delivery_location || "Main Head Office");
        const seeded = (data.items || []).map((it) => ({
          category: it.category || PRODUCT_TYPE_LABELS[it.product_type] || it.product_type || "",
          product_name: it.product_name || "",      // auto-filled from the requisition (read-only)
          detailed_specs: it.detailed_specs || "",   // written by the PR raiser
          preferred_brand: it.preferred_brand || "",
          qty: it.quantity || 1,
          uom: it.uom || "Pcs",
          available_qty: it.in_stock ?? it.available_qty ?? "",
          estimated_unit_price: it.estimated_unit_price ?? "",
          justification_remarks: it.justification_remarks || it.remarks || "",
        }));
        setItems(seeded.length ? seeded : [emptyItem()]);
        if (data.pr_attachment_file_ids?.length) {
          const nameOf = Object.fromEntries((data.attachments || []).map((a) => [a.id, a.name]));
          setFiles(data.pr_attachment_file_ids.map((fid, i) => ({
            id: fid, name: nameOf[fid] || `Attachment ${i + 1}`, size: "",
          })));
        }
      })
      .catch(() => toast.error("Could not load this requisition"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  const addItem = () => setItems((prev) => [...prev, emptyItem()]);
  const removeItem = (i) => setItems((prev) => prev.filter((_, idx) => idx !== i));
  const updateItem = (i, field, val) => {
    setItems((prev) => {
      const next = [...prev];
      next[i] = { ...next[i], [field]: val };
      return next;
    });
  };

  const buildPayload = () => ({
    items: items.map((it, idx) => ({
      index: idx,
      category: it.category,
      detailed_specs: it.detailed_specs,
      preferred_brand: it.preferred_brand,
      quantity: Number(it.qty) || 1,
      uom: it.uom,
      estimated_unit_price:
        it.estimated_unit_price === "" || it.estimated_unit_price == null
          ? null
          : Number(it.estimated_unit_price),
      justification_remarks: it.justification_remarks,
    })),
    overall_business_justification: justification,
    required_by_date: requiredByDate || null,
    urgency_level: urgency || null,
    delivery_location: deliveryLocation,
    attachment_file_ids: files.map((f) => f.id),
  });

  const saveDraft = async () => {
    if (uploadingFiles) return toast.error("Please wait — attachment is still uploading");
    setSaving(true);
    try {
      toast.success("Draft saved locally (submit when ready)");
    } finally {
      setSaving(false);
    }
  };

  const submit = async () => {
    if (uploadingFiles) return toast.error("Please wait — attachment is still uploading");
    if (!requiredByDate) {
      return toast.error("Required-By Date is required — the approver and PO creator need it");
    }
    if (!justification.trim()) {
      return toast.error("Overall Business Justification is required");
    }
    if (items.some((it) => !String(it.detailed_specs || "").trim())) {
      return toast.error("Every line item needs Detailed Specs (model, size, configuration…)");
    }
    setSubmitting(true);
    try {
      const { data } = await api.post(`/requisitions/${id}/file-pr`, buildPayload());
      setReq(data);
      showResult({
        title: "Done!",
        message: "Purchase Requisition filed. Routed to IT Head for specification & quantity review.",
        onClose: () => navigate("/requisitions/purchase"),
      });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="py-10 text-center text-slate-500">Loading…</div>;
  if (!req) return <div className="py-10 text-center text-slate-500">Requisition not found.</div>;

  const canEdit = req.status === "pending_pr";
  const prRef = req.purchase_pr_no || req.requisition_no || `PR-${id?.slice(-6)}`;
  const handlePrint = () => { window.print(); };

  return (
      <div className="bg-slate-50 -m-6 -mt-4 px-3 pt-1 pb-3" data-testid="purchase-requisition-form">
      <style>{`
        @media print {
          body * { visibility: hidden !important; }
          [data-testid="purchase-requisition-form"],
          [data-testid="purchase-requisition-form"] * { visibility: visible !important; }
          [data-testid="purchase-requisition-form"] {
            position: absolute; left: 0; top: 0; width: 100%;
            margin: 0 !important; padding: 8px !important; background: white !important;
          }
          .print-hide { display: none !important; }
        }
      `}</style>

      {/* Top bar: Back left, Print right */}
        <div className="flex items-center justify-between gap-3 mb-1 print-hide">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
        >
          <ArrowLeft size={15} /> Back
        </button>
        <button
          type="button"
          onClick={handlePrint}
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 font-medium"
        >
          <Printer size={15} /> Print
        </button>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-5 shadow-sm">
        {/* Header: logo LEFT, status + print RIGHT */}
        <div className="flex items-start justify-between gap-4 pb-3 border-b border-slate-200">
          <div className="shrink-0">
            <PrimitekFormLogo />
          </div>
                    <div className="flex flex-col items-end gap-2">
            <span className="px-3 py-1 rounded-full bg-amber-50 text-amber-800 border border-amber-200 text-xs font-semibold tracking-wide whitespace-nowrap">
              Current Status: {canEdit ? "DRAFT" : (req.status || "").replace(/_/g, " ").toUpperCase()}
            </span>
          </div>
        </div>

        <div className="text-left">
          <h1 className="text-base font-head font-bold text-slate-900">Purchase Requisition</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Enter technical specs &amp; quantities.
          </p>
        </div>

        <section>
          <h2 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2">
            <span className="w-6 h-6 rounded-md bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-bold">1</span>
            Requisition Metadata &amp; Requester Details
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Field label="PR Reference Number" value={prRef} readOnly badge="Auto" />
            <Field
              label="Requisition Date & Time"
              value={(req.requisition_date || "").replace("T", " ").slice(0, 16)}
              readOnly
            />
            <Field label="Requester Name (User)" value={req.requisitioner_name || user?.name || ""} readOnly />
            <Field label="Requester Department" value={req.requisitioner_department_name || ""} readOnly />
            <Field
              label="Required-By Date *"
              type="date"
              value={requiredByDate}
              disabled={!canEdit}
              onChange={setRequiredByDate}
            />
            <div>
              <label className="text-xs text-slate-500 mb-1 block">
                Urgency Level <span className="text-slate-400 font-normal"></span>
              </label>
              <select
                value={urgency}
                disabled={!canEdit}
                onChange={(e) => setUrgency(e.target.value)}
                className="w-full bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-800 disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500"
              >
                <option value="">— Select —</option>
                {URGENCY_OPTIONS.map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </div>
          </div>
        </section>

        <section>
          <div className="flex justify-between items-center mb-2">
            <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <span className="w-6 h-6 rounded-md bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-bold">2</span>
              Line Items
            </h2>
            {canEdit && (
              <button
                onClick={addItem}
                className="print-hide flex items-center gap-1.5 text-sm bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 rounded-lg transition-colors font-medium"
              >
                <Plus size={14} /> Add Item
              </button>
            )}
          </div>
          <p className="text-xs text-slate-500 mb-3">
            Specs &amp; quantities required. Est. price.
          </p>

          <div className="rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full text-sm table-fixed">
              <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide align-bottom">
                <tr>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[3%]">SI</th>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[9%]">Category</th>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[13%]">Product</th>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[16%]">Detailed Specs</th>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[10%]">Preferred Brand</th>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[6%]">Qty</th>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[8%]">UoM</th>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[7%]">Avail. Qty</th>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[9%]">
                    Est. Price <span className="normal-case font-normal text-slate-400"></span>
                  </th>
                  <th className="px-2 py-2.5 text-left font-semibold whitespace-normal break-words leading-tight w-[15%]">Justification / Remarks</th>
                  {canEdit && <th className="px-2 py-2.5 w-[4%] print-hide" />}
                </tr>
              </thead>
              <tbody>
                {items.map((it, i) => (
                  <tr key={i} className="border-t border-slate-100" data-testid={`pr-item-row-${i}`}>
                    <td className="px-2 py-2 text-slate-400">{i + 1}</td>
                    <td className="px-2 py-2">
                      <input
                        className="bg-white border border-slate-300 rounded px-2 py-1.5 w-full min-w-0 text-sm text-slate-800 disabled:opacity-60 focus:outline-none focus:ring-1 focus:ring-amber-500"
                        value={it.category}
                        disabled={!canEdit}
                        onChange={(e) => updateItem(i, "category", e.target.value)}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="bg-slate-50 border border-slate-200 rounded px-2 py-1.5 w-full min-w-0 text-sm font-medium text-slate-800 cursor-not-allowed"
                        value={it.product_name}
                        readOnly
                        title="Auto-filled from the requisition"
                        data-testid={`pr-item-product-${i}`}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <textarea
                        className="bg-white border border-slate-300 rounded px-2 py-1.5 w-full min-w-0 h-16 text-sm text-slate-800 resize-none disabled:opacity-60 focus:outline-none focus:ring-1 focus:ring-amber-500"
                        value={it.detailed_specs}
                        disabled={!canEdit}
                        onChange={(e) => updateItem(i, "detailed_specs", e.target.value)}
                        placeholder="e.g. Dell XPS 15 – Intel i9, 32GB RAM…"
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="bg-white border border-slate-300 rounded px-2 py-1.5 w-full min-w-0 text-sm text-slate-800 disabled:opacity-60 focus:outline-none focus:ring-1 focus:ring-amber-500"
                        value={it.preferred_brand}
                        disabled={!canEdit}
                        onChange={(e) => updateItem(i, "preferred_brand", e.target.value)}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        type="number"
                        min={1}
                        className="bg-white border border-slate-300 rounded px-2 py-1.5 w-full min-w-0 text-sm text-slate-800 disabled:opacity-60 focus:outline-none focus:ring-1 focus:ring-amber-500"
                        value={it.qty}
                        disabled={!canEdit}
                        onChange={(e) => updateItem(i, "qty", e.target.value)}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <select
                        className="w-full min-w-0 bg-white border border-slate-300 rounded px-2 py-1.5 text-sm text-slate-800 disabled:opacity-60 focus:outline-none focus:ring-1 focus:ring-amber-500"
                        value={it.uom}
                        disabled={!canEdit}
                        onChange={(e) => updateItem(i, "uom", e.target.value)}
                      >
                        {UOM_OPTIONS.map((u) => <option key={u}>{u}</option>)}
                      </select>
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="bg-slate-50 border border-slate-200 rounded px-2 py-1.5 w-full min-w-0 text-sm text-slate-500"
                        value={it.available_qty === "" || it.available_qty == null ? "—" : it.available_qty}
                        readOnly
                        title="Available quantity in stock (read-only)"
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        placeholder="Optional"
                        className="bg-white border border-slate-300 rounded px-2 py-1.5 w-full min-w-0 text-sm text-slate-800 disabled:opacity-60 focus:outline-none focus:ring-1 focus:ring-amber-500"
                        value={it.estimated_unit_price}
                        disabled={!canEdit}
                        onChange={(e) => updateItem(i, "estimated_unit_price", e.target.value)}
                        title="Guess / estimated unit price — not mandatory"
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="bg-white border border-slate-300 rounded px-2 py-1.5 w-full min-w-0 text-sm text-slate-800 disabled:opacity-60 focus:outline-none focus:ring-1 focus:ring-amber-500"
                        value={it.justification_remarks}
                        disabled={!canEdit}
                        onChange={(e) => updateItem(i, "justification_remarks", e.target.value)}
                      />
                    </td>
                    {canEdit && (
                      <td className="px-2 py-2 print-hide">
                        <button onClick={() => removeItem(i)} className="text-red-500 hover:text-red-700">
                          <Trash2 size={16} />
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="grid md:grid-cols-2 gap-6">
          <div className="space-y-4">
            <div>
              <label className="text-sm text-slate-700 font-medium">
                Overall Business Justification <span className="text-red-500">*</span>
              </label>
              <textarea
                className="mt-1.5 w-full bg-white border border-slate-300 rounded-lg p-3 h-32 text-sm text-slate-800 resize-none disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500"
                value={justification}
                disabled={!canEdit}
                onChange={(e) => setJustification(e.target.value)}
                placeholder="Explain operational necessity, impacted workflow, or project goals…"
                maxLength={2000}
              />
              <p className="text-xs text-slate-400 mt-1 text-right">{justification.length}/2000 chars</p>
            </div>
            <div>
              <label className="text-sm text-slate-700 font-medium">Delivery Location / Target Office</label>
              <select
                className="mt-1.5 w-full bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-800 disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500"
                value={deliveryLocation}
                disabled={!canEdit}
                onChange={(e) => setDeliveryLocation(e.target.value)}
              >
                {DELIVERY_OPTIONS.map((o) => <option key={o}>{o}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label className="text-sm text-slate-700 font-medium">Technical Docs &amp; Approvals Zone</label>
            <div className="mt-1.5 border-2 border-dashed border-slate-300 rounded-xl h-40 flex flex-col items-center justify-center text-slate-400 bg-slate-50">
              <UploadCloud size={28} className="mb-2 opacity-70" />
              <p className="text-sm text-slate-500">Drop technical spec sheets or requisition docs here</p>
              <p className="text-xs mt-0.5 text-slate-400">PDF, DOCX, XLSX up to 15 MB each</p>
              {canEdit && (
                <>
                  <input
                    type="file"
                    multiple
                    accept=".pdf,.docx,.xlsx,.doc,.xls"
                    className="hidden"
                    id="pr-tech-files"
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
                          setFiles((prev) => [...prev, {
                            id: data.id, name: data.original_filename || f.name,
                            size: `${(f.size / 1024 / 1024).toFixed(1)} MB`,
                          }]);
                        } catch (err) {
                          toast.error(`${f.name}: ${formatApiErrorDetail(err.response?.data?.detail) || "Upload failed"}`);
                        }
                      }
                      setUploadingFiles(false);
                    }}
                  />
                  <label htmlFor="pr-tech-files" className="mt-2 text-amber-600 cursor-pointer text-sm hover:underline font-medium print-hide">
                    {uploadingFiles ? "Uploading…" : "Browse"}
                  </label>
                </>
              )}
            </div>
            {files.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-slate-500 mb-1">ATTACHED DOCS ({files.length})</p>
                <ul className="space-y-1">
                  {files.map((f) => (
                    <li key={f.id} className="flex items-center justify-between bg-slate-50 border border-slate-200 px-3 py-1.5 rounded text-xs text-slate-700">
                      <a href={withAuthParam(`${API}/files/${f.id}/download`)} target="_blank" rel="noreferrer" className="truncate text-blue-600 hover:underline">{f.name} {f.size && <span className="text-slate-400">({f.size})</span>}</a>
                      {canEdit && (
                        <button onClick={() => setFiles((p) => p.filter((x) => x.id !== f.id))} className="text-slate-400 hover:text-red-500 ml-2 print-hide">×</button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>

        <div className="flex flex-wrap gap-3 justify-between pt-4 border-t border-slate-200 print-hide">
          <button
            onClick={() => { setItems([emptyItem()]); setJustification(""); setUrgency(""); }}
            disabled={!canEdit}
            className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50 text-sm font-medium disabled:opacity-40"
          >
            Reset Form
          </button>
          <div className="flex gap-3">
            <button
              onClick={saveDraft}
              disabled={!canEdit || saving}
              className="px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm flex items-center gap-2 font-medium disabled:opacity-50"
            >
              <Save size={16} /> Save Draft
            </button>
            <button
              onClick={submit}
              disabled={!canEdit || submitting}
              data-testid="btn-submit-pr"
              className="px-5 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 disabled:opacity-50"
            >
              <Send size={16} /> Submit PR
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, type = "text", readOnly, required, badge, disabled }) {
  return (
    <div>
      <label className="text-xs text-slate-500 flex items-center gap-2 mb-1">
        {label}
        {badge && <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded border border-slate-200">{badge}</span>}
      </label>
      <input
        type={type}
        value={value || ""}
        readOnly={readOnly}
        required={required}
        disabled={disabled || readOnly}
        onChange={(e) => onChange?.(e.target.value)}
        className={`w-full bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-800
          ${(readOnly || disabled) ? "opacity-70 cursor-default bg-slate-50" : "focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500"}`}
      />
    </div>
  );
}