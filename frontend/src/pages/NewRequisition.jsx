import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ClipboardList, Plus, Trash2, Package, ShieldCheck, User, Calendar,
  Paperclip, CheckCircle2, ArrowRight, Zap, UserCog, AlertCircle, ListPlus, Pencil,
} from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";
import { showResult } from "@/components/ResultPopup";

// Service requisition dropdowns (same lists are enforced by the backend).
const PRIORITIES = [["low", "Low"], ["medium", "Medium"], ["high", "High"], ["critical", "Critical"]];
// Service categories. The backend routes each one to an IT sub-team (see SERVICE_CATEGORIES in server.py):
//   Application team   -> ERP Software Access, Modify Access, New Entry / Edit Requests
//   Network & Infra    -> everything else
const REQUEST_TYPES = [
  ["erp_software_access", "ERP Software Access"],
  ["modify_access", "Modify Access"],
  ["new_entry_edit_request", "New Entry / Edit Requests"],
  ["software_installation", "Software Installation"],
  ["software_update", "Software Update"],
  ["email_service", "Email Service"],
  ["operating_system", "Operating System (OS)"],
  ["hardware_support", "Hardware & Physical Support"],
  ["network_connectivity", "Network & Connectivity"],
  ["others", "Others"],
];
const APPLICATION_CATEGORIES = ["erp_software_access", "modify_access", "new_entry_edit_request"];
const HARDWARE_DEVICES = ["Printer", "Scanner", "Desktop", "Laptop", "Monitor", "UPS", "Other"];
// Requisitions saved before sub-team routing used these request types.
const LEGACY_REQUEST_TYPE = { hardware: "hardware_support", network: "network_connectivity", others: "others" };
const LEGACY_SOFTWARE_ACTION = { installation: "software_installation", update: "software_update", troubleshooting: "others" };
const categoryOfItem = (it) => {
  if (it.service_category) return it.service_category;
  const t = (it.request_type || "").toLowerCase();
  if (REQUEST_TYPES.some(([k]) => k === t)) return t;
  const byLabel = REQUEST_TYPES.find(([, l]) => l.toLowerCase() === t);
  if (byLabel) return byLabel[0];
  if (t === "software") return LEGACY_SOFTWARE_ACTION[(it.request_detail || "").toLowerCase()] || "";
  return LEGACY_REQUEST_TYPE[t] || "";
};
const PRIORITY_CLS = { low: "bg-slate-100 text-slate-600", medium: "bg-sky-100 text-sky-700", high: "bg-amber-100 text-amber-700", critical: "bg-red-100 text-red-700" };
const labelOf = (list, v) => (list.find(([k]) => k === v) || [])[1] || v;

export default function NewRequisition() {
  const { user } = useAuth();
  // Hide approval priority for employees, dept heads, purchase head, accounts, and MD
  const showApprovalPath = user?.role === "super_admin";
  const navigate = useNavigate();
  const { id: editId } = useParams(); // present only on /requisitions/:id/revise
  const PRODUCT_TYPE_LABELS = {
    asset: "IT Asset",
    consumable: "Consumable",
    it_accessories: "IT Accessories",
    network: "Network",
    furniture: "Furniture",
  };
  const [reqType, setReqType] = useState("product");
  const [productType, setProductType] = useState("asset");
  const [productName, setProductName] = useState("");
  const [catalog, setCatalog] = useState([]);   // master product list (exact names)
  useEffect(() => { api.get("/products").then(({ data }) => setCatalog(data)).catch(() => {}); }, []);
  // Names offered for the chosen product type. A legacy name (editing an old requisition)
  // that isn't in the catalog is kept as an extra option so it doesn't vanish.
  const productOptions = catalog.filter((c) => c.product_type === productType).map((c) => c.name);
  if (productName && !catalog.some((c) => c.name === productName)) productOptions.unshift(productName);
  const [qty, setQty] = useState(1);
  const [remarks, setRemarks] = useState("");
  // Service requisition fields
  const [priority, setPriority] = useState("");
  const [requestType, setRequestType] = useState("");
  const [requestDetail, setRequestDetail] = useState("");   // device (hardware) or action (software)
  const detailOptions = requestType === "hardware_support" ? HARDWARE_DEVICES : null;

  // Who this requisition is actually for — defaults to the logged-in requester, but an
  // employee can raise it on behalf of someone else (e.g. a new joiner, a colleague).
  const [requisitionFor, setRequisitionFor] = useState("");

  const [items, setItems] = useState([]);
  const [note, setNote] = useState("");
  const [attachment, setAttachment] = useState("");
  const [attachmentFileId, setAttachmentFileId] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [reqDate, setReqDate] = useState(new Date().toISOString().slice(0, 10));
  const [reqNo, setReqNo] = useState("REQ-2026-XXXX");
  const [chain, setChain] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  // Edit mode (resubmitting after a revision request)
  const [loadingExisting, setLoadingExisting] = useState(!!editId);
  const [revisionInfo, setRevisionInfo] = useState(null); // { note, approverName, label }
  // When set, the Add Item form is in "edit existing line" mode (revision flow only).
  const [editingIndex, setEditingIndex] = useState(null);

  const itemCount = useMemo(() => items.reduce((s, it) => s + it.quantity, 0), [items]);

  useEffect(() => {
    if (editId) return; // real requisition_no is loaded instead — see the load-existing effect
    setReqNo(`REQ-${new Date().getFullYear()}-${String(Math.floor(Math.random() * 9000) + 1000)}`);
  }, [editId]);

  useEffect(() => {
    if (editId) return; // the actual requisition_for is loaded instead
    if (user?.name && !requisitionFor) setRequisitionFor(user.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, editId]);

  useEffect(() => {
    if (editId) return; // the requisition's real (already-assigned) approval chain is loaded instead
    // Pricing isn't collected at this stage anymore — MD approval is decided later, once
    // the Purchase Requisition is raised with real market rates — so the chain preview
    // never includes MD here regardless of item count.
    // Items are sent so the preview shows the right chain: consumable/furniture-only
    // requisitions go straight to the Admin Head.
    api.post("/requisitions/preview-chain", {
      requisition_type: reqType, total_amount: 0,
      items: items.map((it) => ({ product_name: it.product_name })),
    })
      .then(({ data }) => setChain(data.chain))
      .catch(() => setChain([]));
  }, [reqType, editId, items]);

  useEffect(() => {
    if (!editId) return;
    (async () => {
      try {
        const { data } = await api.get(`/requisitions/${editId}`);
        if (data.status !== "revision_requested") {
          toast.error("This requisition is no longer awaiting revision.");
          navigate("/requisitions/pending");
          return;
        }
        setReqType(data.requisition_type);
        setReqNo(data.requisition_no);
        setRequisitionFor(data.requisition_for || "");
        setItems(data.items.map((it) => ({
          product_type: it.product_type, product_name: it.product_name,
          quantity: it.quantity, rate: it.rate || 0, remarks: it.remarks || null,
          category_id: it.category_id || null,
          priority: it.priority || null, request_type: it.request_type || null, request_detail: it.request_detail || null,
        })));
        setNote(data.requester_note || "");
        setAttachment(data.attachment_name || "");
        setAttachmentFileId(data.attachment_file_id || null);
        setReqDate((data.requisition_date || "").slice(0, 10) || new Date().toISOString().slice(0, 10));
        setChain(data.approval_chain || []);
        const step = (data.approval_chain || []).find((s) => s.status === "revision_requested");
        setRevisionInfo(step ? { note: step.note, approverName: step.approver_name, label: step.label } : null);
      } catch (e) {
        toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not load this requisition");
        navigate("/requisitions/pending");
      } finally {
        setLoadingExisting(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editId]);

  const clearItemForm = () => {
    setProductName("");
    setQty(1);
    setRemarks("");
    setPriority(""); setRequestType(""); setRequestDetail("");
    setEditingIndex(null);
  };

  // A requisition is either all products or all services - don't let the two mix on one form.
  const changeReqType = (v) => {
    if (v !== reqType && items.length > 0) {
      return toast.error("Remove the added items first to change the requisition type");
    }
    setReqType(v);
    setProductName(""); setPriority(""); setRequestType(""); setRequestDetail("");
  };

  const addItem = () => {
    let row;
    if (reqType === "service") {
      if (!priority) return toast.error("Select a priority level");
      if (!requestType) return toast.error("Select a service category");
      if (detailOptions && !requestDetail) return toast.error("Select the device");
      // One requisition = one IT sub-team queue (Application vs Network & Infra).
      const isApp = APPLICATION_CATEGORIES.includes(requestType);
      if (items.some((it, idx) => idx !== editingIndex && it.request_type
          && APPLICATION_CATEGORIES.includes(categoryOfItem(it)) !== isApp)) {
        return toast.error("Application requests (ERP / Access / New Entry-Edit) and Network & Infra requests must be raised as separate requisitions");
      }
      if ((requestType === "others" || requestDetail === "Other") && !remarks.trim()) return toast.error("Describe the request in Remarks");
      const rtLabel = labelOf(REQUEST_TYPES, requestType);
      row = {
        product_type: "asset",   // not used for services; the API just needs a valid value
        product_name: requestDetail ? `${rtLabel} - ${requestDetail}` : rtLabel,
        quantity: 1, rate: 0, remarks: remarks.trim() || null,
        priority, request_type: requestType, service_category: requestType, request_detail: requestDetail || null,
      };
    } else {
      if (!productName.trim()) return toast.error("Select a product");
      if (qty < 1) return toast.error("Quantity must be at least 1");
      row = {
        product_type: productType,
        product_name: productName.trim(),
        quantity: Number(qty),
        rate: 0,
        remarks: remarks.trim() || null,
      };
    }
    if (editingIndex !== null) {
      setItems((prev) => prev.map((it, idx) => (idx === editingIndex ? { ...it, ...row } : it)));
      toast.success("Item updated");
      clearItemForm();
      return;
    }
    setItems((prev) => [...prev, row]);
    setProductName("");
    setQty(1);
    setRemarks("");
    setPriority(""); setRequestType(""); setRequestDetail("");
    toast.success("Item added");
  };

  const startEditItem = (i) => {
    const it = items[i];
    if (!it) return;
    setProductType(it.product_type || "asset");
    setProductName(it.product_name || "");
    setQty(it.quantity || 1);
    setRemarks(it.remarks || "");
    setPriority(it.priority || ""); setRequestType(categoryOfItem(it)); setRequestDetail(it.request_detail || "");
    setEditingIndex(i);
  };

  const removeItem = (i) => {
    setItems((prev) => prev.filter((_, idx) => idx !== i));
    if (editingIndex === i) clearItemForm();
    else if (editingIndex !== null && editingIndex > i) setEditingIndex(editingIndex - 1);
  };

  const handleAttachment = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setAttachmentFileId(data.id);
      setAttachment(data.original_filename);
      toast.success("Attachment uploaded");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    if (items.length === 0) return toast.error("Add at least one item");
    setSubmitting(true);
    let resultMsg = null;
    try {
      if (editId) {
        const { data } = await api.post(`/requisitions/${editId}/resubmit`, {
          items,
          requester_note: note || null,
          attachment_file_id: attachmentFileId,
          attachment_name: attachment || null,
          requisition_for: requisitionFor.trim() || user?.name,
          requisition_date: reqDate,
          note: "Requester edited and resubmitted the requisition.",
        });
        resultMsg = { title: "Done!", message: `Requisition ${data.requisition_no} has been resubmitted for approval.` };
      } else {
        const { data } = await api.post("/requisitions", {
          requisition_type: reqType,
          requisition_for: requisitionFor.trim() || user?.name,
          items,
          requester_note: note || null,
          attachment_file_id: attachmentFileId,
          attachment_name: attachment || null,
          requisition_date: reqDate,
        });
        resultMsg = { title: "Done!", message: `Requisition ${data.requisition_no} has been submitted for approval.` };
      }
      showResult({ ...resultMsg, onClose: () => navigate("/requisitions/pending") });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSubmitting(false);
    }
  };

  if (loadingExisting) {
    return (
      <div className="p-10 text-center text-slate-400 bg-white rounded-xl border border-slate-200" data-testid="new-requisition-loading">
        Loading requisition…
      </div>
    );
  }

  return (
    <div className="max-w-[1360px] mx-auto space-y-4" data-testid="new-requisition-page">
      {/* Header card */}
      <div className="rounded-xl bg-[#0C1733] text-white p-4 flex flex-col lg:flex-row lg:items-center gap-4 justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-600 flex items-center justify-center shrink-0">
            <ClipboardList size={20} />
          </div>
          <div>
            <div className="font-head font-bold text-lg tracking-wide">{editId ? "REVISE & RESUBMIT REQUISITION" : "NEW REQUISITION FORM"}</div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="bg-white/5 rounded-lg px-3.5 py-1.5 border border-white/10">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">Requisition No.</div>
            <div className="font-mono font-semibold text-amber-400" data-testid="req-no">{reqNo}</div>
          </div>
          <div className="bg-white/5 rounded-lg px-3.5 py-1.5 border border-white/10 flex items-center gap-2">
            <User size={16} className="text-slate-400" />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Requisitioner</div>
              <div className="font-semibold text-sm">{user?.name} · {user?.department_name || "—"}</div>
            </div>
          </div>
          <div className="bg-white/5 rounded-lg px-3.5 py-1.5 border border-white/10 flex items-center gap-2">
            <Calendar size={16} className="text-slate-400" />
            <input type="date" value={reqDate} onChange={(e) => setReqDate(e.target.value)}
              className="bg-transparent text-sm outline-none" data-testid="req-date" />
          </div>
        </div>
      </div>

      {/* Revision feedback banner — what the approver who sent this back actually asked for */}
      {revisionInfo && (
        <div className="rounded-xl border border-orange-200 bg-orange-50 p-3 flex items-start gap-3" data-testid="revision-note-banner">
          <AlertCircle className="text-orange-500 shrink-0 mt-0.5" size={18} />
          <div>
            <div className="text-sm font-semibold text-orange-800">
              Sent back for revision by {revisionInfo.approverName || "the approver"}
              {revisionInfo.label ? ` (${revisionInfo.label})` : ""}
            </div>
            {revisionInfo.note && <div className="text-sm text-orange-700 mt-1">"{revisionInfo.note}"</div>}
            <div className="text-xs text-orange-600 mt-1.5">Make the requested changes below, then resubmit — it goes straight back to them.</div>
          </div>
        </div>
      )}

      {/* Item entry */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
        <div className="flex items-center gap-2 mb-3">
          <ListPlus size={18} className="text-slate-400" />
          <h3 className="font-head font-semibold text-slate-900">Add Item</h3>
        </div>
        <div className={`grid grid-cols-1 gap-3 items-end ${reqType === "service"
          ? (detailOptions ? "md:grid-cols-[1.1fr_0.9fr_1fr_1.1fr_1.3fr_auto]" : "md:grid-cols-[1.1fr_0.9fr_1fr_1.3fr_auto]")
          : "md:grid-cols-[1.1fr_1.1fr_1.7fr_0.6fr_1.3fr_auto]"}`}>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Requisition Type *</label>
            <select value={reqType} onChange={(e) => changeReqType(e.target.value)} data-testid="input-req-type"
              className="w-full h-10 px-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm bg-white">
              <option value="product">Product Requisition</option>
              <option value="service">Service Requisition</option>
            </select>
          </div>
          {reqType === "service" ? (
            <>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Priority Level *</label>
                <select value={priority} onChange={(e) => setPriority(e.target.value)} data-testid="input-priority"
                  className="w-full h-10 px-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm bg-white">
                  <option value="">Select priority…</option>
                  {PRIORITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Service Category *</label>
                <select value={requestType} onChange={(e) => { setRequestType(e.target.value); setRequestDetail(""); }} data-testid="input-request-type"
                  className="w-full h-10 px-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm bg-white">
                  <option value="">Select category…</option>
                  {REQUEST_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </div>
              {detailOptions && (
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Device *</label>
                  <select value={requestDetail} onChange={(e) => setRequestDetail(e.target.value)} data-testid="input-request-detail"
                    className="w-full h-10 px-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm bg-white">
                    <option value="">Select device…</option>
                    {detailOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </div>
              )}
            </>
          ) : (
            <>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Product Type *</label>
                <select value={productType} onChange={(e) => { setProductType(e.target.value); setProductName(""); }} data-testid="input-product-type"
                  className="w-full h-10 px-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm bg-white">
                  <option value="asset">IT Asset</option>
                  <option value="consumable">Consumable</option>
                  <option value="it_accessories">IT Accessories</option>
                  <option value="network">Network</option>
                  <option value="furniture">Furniture</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Product Name *</label>
                <select value={productName} onChange={(e) => setProductName(e.target.value)} data-testid="input-product-name"
                  className="w-full h-10 px-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm bg-white">
                  <option value="">{productOptions.length ? "Select product…" : "No products in this type"}</option>
                  {productOptions.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Qty *</label>
                <input type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} data-testid="input-qty"
                  className="w-full h-10 px-2.5 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm text-center" />
              </div>
            </>
          )}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Requisition For *</label>
            <div className="relative">
              <UserCog size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input value={requisitionFor} onChange={(e) => setRequisitionFor(e.target.value)} placeholder="Name this is being raised for"
                data-testid="input-requisition-for"
                className="w-full h-10 pl-8 pr-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm" />
            </div>
          </div>
          <button onClick={addItem} data-testid="btn-add-product"
            className="h-10 px-4 rounded-md bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center justify-center gap-2 transition-colors whitespace-nowrap">
            {editingIndex !== null ? (<><Pencil size={16} /> Update</>) : (<><Plus size={16} /> Add</>)}
          </button>
        </div>
        <div className="mt-3 max-w-lg">
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
            {reqType === "service" ? ((requestType === "others" || requestDetail === "Other") ? "Describe the request *" : "Describe the issue (optional)") : "Remarks"}
          </label>
          <input value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder={reqType === "service" ? "What do you need help with?" : "Optional note for this item…"} data-testid="input-remarks"
            className="w-full h-10 px-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm" />
        </div>
      </div>

      {/* Items table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
          <div className="flex items-center gap-2"><Package size={18} className="text-slate-400" /><h3 className="font-head font-semibold text-slate-900">Requisition Items</h3></div>
          <div className="font-mono text-sm text-slate-700">Items: <span className="font-semibold text-slate-900" data-testid="items-total">{itemCount}</span></div>
        </div>
        {items.length === 0 ? (
          <div className="py-6 text-center text-slate-400 text-sm" data-testid="items-empty">
            <Package size={22} className="mx-auto mb-2 opacity-50" />
            No products added yet. Use the form above to add products to this requisition.
          </div>
        ) : (
          <div className="max-h-56 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100">
                  <th className="px-5 py-2.5 font-semibold">Product</th>
                  <th className="px-5 py-2.5 font-semibold">Type</th>
                  <th className="px-5 py-2.5 font-semibold">Qty</th>
                  <th className="px-5 py-2.5 font-semibold">Remarks</th>
                  <th className="px-5 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {items.map((it, i) => (
                  <tr key={i} className="border-b border-slate-50" data-testid={`item-row-${i}`}>
                    <td className="px-5 py-2 font-medium text-slate-800">
                      {it.product_name}
                      {it.priority && <span className={`ml-2 px-2 py-0.5 rounded-full text-[11px] font-semibold ${PRIORITY_CLS[it.priority] || ""}`} data-testid={`item-priority-${i}`}>{labelOf(PRIORITIES, it.priority)}</span>}
                    </td>
                    <td className="px-5 py-2 text-slate-600">{it.request_type ? "Service" : (PRODUCT_TYPE_LABELS[it.product_type] || it.product_type)}</td>
                    <td className="px-5 py-2 font-mono">{it.quantity}</td>
                    <td className="px-5 py-2 text-slate-500">{it.remarks || "—"}</td>
                    <td className="px-5 py-2 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {editId && (
                          <button
                            onClick={() => startEditItem(i)}
                            data-testid={`btn-edit-item-${i}`}
                            title="Edit item"
                            className="text-slate-400 hover:text-amber-600 transition-colors"
                          >
                            <Pencil size={16} />
                          </button>
                        )}
                        <button
                          onClick={() => removeItem(i)}
                          data-testid={`btn-remove-item-${i}`}
                          title="Remove item"
                          className="text-slate-400 hover:text-red-600 transition-colors"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Attachments & notes */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
        <div className="flex items-center gap-2 mb-3"><Paperclip size={18} className="text-slate-400" /><h3 className="font-head font-semibold text-slate-900">Attachments &amp; Notes</h3></div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Attachment (Optional)</label>
            <input type="file" data-testid="input-attachment" onChange={handleAttachment}
              className="w-full text-sm mb-1 file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:bg-slate-100 file:text-slate-700 file:font-medium" />
            <p className="text-xs text-slate-400">{uploading ? "Uploading…" : (attachment || "No file selected")}</p>
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Requester Note (Optional)</label>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Add any additional note…" data-testid="input-requester-note"
              className="w-full px-3 py-2 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm resize-none" />
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end gap-3 pb-2">
        <button onClick={() => navigate(-1)} data-testid="btn-cancel"
          className="h-10 px-5 rounded-md border border-slate-300 text-slate-600 font-semibold text-sm hover:bg-slate-50 transition-colors">Cancel</button>
        <button onClick={submit} disabled={submitting} data-testid="btn-submit-requisition"
          className="h-10 px-6 rounded-md bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 transition-colors disabled:opacity-60">
          <CheckCircle2 size={18} /> {editId ? "Resubmit for Approval" : "Submit Requisition"}
        </button>
      </div>
    </div>
  );
}