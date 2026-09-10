import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2, Handshake, ArrowLeftRight } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import SignaturePad from "@/components/SignaturePad";

export default function HandoverModule() {
  const navigate = useNavigate();
  const [type, setType] = useState("handover");
  const [emp, setEmp] = useState("");
  const [deptId, setDeptId] = useState("");
  const [depts, setDepts] = useState([]);
  const [stock, setStock] = useState([]);
  const [items, setItems] = useState([]);
  const [entry, setEntry] = useState({ item: "", brand: "", quantity: 1, remarks: "", asset_id: "" });
  const [remarks, setRemarks] = useState("");
  const [note, setNote] = useState("");
  const [prepSign, setPrepSign] = useState(null);
  const [recvSign, setRecvSign] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const [d, s] = await Promise.all([api.get("/departments"), api.get("/assets?status=in_stock")]);
    setDepts(d.data); setStock(s.data);
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const addItem = () => {
    if (!entry.item.trim()) return toast.error("Enter item name");
    setItems((p) => [...p, { ...entry, quantity: Number(entry.quantity) }]);
    setEntry({ item: "", brand: "", quantity: 1, remarks: "", asset_id: "" });
  };
  const removeItem = (i) => setItems((p) => p.filter((_, idx) => idx !== i));

  const onAssetPick = (id) => {
    const a = stock.find((x) => x.id === id);
    setEntry((e) => ({ ...e, asset_id: id, item: a ? a.name : e.item, brand: a?.brand || e.brand }));
  };

  const submit = async () => {
    if (!emp.trim()) return toast.error("Employee name is required");
    if (items.length === 0) return toast.error("Add at least one item");
    setSaving(true);
    try {
      const { data } = await api.post("/handovers", {
        type, employee_name: emp, department_id: deptId || null, items, remarks: remarks || null,
        note: note || null, prepared_by_sign: prepSign, received_by_sign: recvSign,
      });
      toast.success(`${data.slip_no} recorded`);
      navigate("/handover/records");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-6" data-testid="handover-module-page">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">Handover Module</h2>
        <p className="text-slate-500 text-sm mt-1">Create a Hand Over / Take Over slip with digital signatures.</p>
      </div>

      <div className="flex gap-2">
        <button onClick={() => setType("handover")} data-testid="ho-type-handover" className={`px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 transition-colors ${type === "handover" ? "bg-amber-600 text-white" : "bg-white border border-slate-300 text-slate-600"}`}><Handshake size={16} /> Hand Over</button>
        <button onClick={() => setType("takeover")} data-testid="ho-type-takeover" className={`px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 transition-colors ${type === "takeover" ? "bg-amber-600 text-white" : "bg-white border border-slate-300 text-slate-600"}`}><ArrowLeftRight size={16} /> Take Over</button>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Employee Name *"><input data-testid="ho-employee" value={emp} onChange={(e) => setEmp(e.target.value)} className="hinp" placeholder="e.g. Baitulla" /></Field>
          <Field label="Department">
            <select data-testid="ho-dept" value={deptId} onChange={(e) => setDeptId(e.target.value)} className="hinp">
              <option value="">—</option>
              {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </Field>
        </div>

        <div className="border-t border-slate-100 pt-4">
          <div className="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
            <Field label="Link Asset (stock)">
              <select data-testid="ho-asset" value={entry.asset_id} onChange={(e) => onAssetPick(e.target.value)} className="hinp">
                <option value="">— none —</option>
                {stock.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.tag_id || a.serial_no})</option>)}
              </select>
            </Field>
            <Field label="Item *"><input data-testid="ho-item" value={entry.item} onChange={(e) => setEntry({ ...entry, item: e.target.value })} className="hinp" /></Field>
            <Field label="Brand"><input data-testid="ho-brand" value={entry.brand} onChange={(e) => setEntry({ ...entry, brand: e.target.value })} className="hinp" /></Field>
            <Field label="Qty"><input type="number" min="1" data-testid="ho-qty" value={entry.quantity} onChange={(e) => setEntry({ ...entry, quantity: e.target.value })} className="hinp" /></Field>
            <Field label="Remarks"><input data-testid="ho-item-remarks" value={entry.remarks} onChange={(e) => setEntry({ ...entry, remarks: e.target.value })} className="hinp" /></Field>
            <button onClick={addItem} data-testid="ho-add-item" className="py-2.5 px-4 rounded-lg bg-slate-800 hover:bg-slate-900 text-white font-semibold text-sm flex items-center justify-center gap-2 transition-colors"><Plus size={16} /> Add</button>
          </div>
        </div>

        {items.length > 0 && (
          <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
            <thead><tr className="text-left text-xs uppercase tracking-wider text-slate-500 bg-slate-50"><th className="px-4 py-2">Item</th><th className="px-4 py-2">Brand</th><th className="px-4 py-2">Qty</th><th className="px-4 py-2">Remarks</th><th className="px-4 py-2"></th></tr></thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i} className="border-t border-slate-100" data-testid={`ho-item-row-${i}`}>
                  <td className="px-4 py-2 font-medium text-slate-800">{it.item}</td>
                  <td className="px-4 py-2 text-slate-600">{it.brand || "—"}</td>
                  <td className="px-4 py-2 font-mono">{it.quantity}</td>
                  <td className="px-4 py-2 text-slate-500">{it.remarks || "—"}</td>
                  <td className="px-4 py-2 text-right"><button onClick={() => removeItem(i)} className="text-slate-400 hover:text-red-600"><Trash2 size={15} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Remarks"><textarea data-testid="ho-remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} rows={2} className="hinp resize-none" /></Field>
          <Field label="Note"><textarea data-testid="ho-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="hinp resize-none" placeholder="e.g. Previous wireless mouse returned" /></Field>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <SignaturePad label="Prepared By (signature)" testid="ho-sign-prepared" onChange={setPrepSign} />
          <SignaturePad label="Received By (signature)" testid="ho-sign-received" onChange={setRecvSign} />
        </div>

        <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs text-slate-500">
          You are responsible for the proper care, handling, and safekeeping of the assigned IT equipment, and must return it in good condition upon request or when your assignment/employment ends.
        </div>

        <div className="flex justify-end">
          <button onClick={submit} disabled={saving} data-testid="ho-submit" className="px-6 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm transition-colors disabled:opacity-60">Save Slip</button>
        </div>
      </div>
      <style>{`.hinp{width:100%;padding:0.55rem 0.75rem;border:1px solid #cbd5e1;border-radius:0.5rem;font-size:0.875rem;outline:none}.hinp:focus{border-color:#d97706}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return <div><label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">{label}</label>{children}</div>;
}
