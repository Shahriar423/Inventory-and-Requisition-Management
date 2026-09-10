import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Truck, Tag, Package } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { bdt } from "@/lib/status";

export default function StockGRN() {
  const [cats, setCats] = useState([]);
  const [grns, setGrns] = useState([]);
  const [head, setHead] = useState({ challan_no: "", vendor_name: "", received_date: new Date().toISOString().slice(0, 10), delivery_location: "Head Office" });
  const [items, setItems] = useState([]);
  const [entry, setEntry] = useState({ product_name: "", category_id: "", uom: "Nos", quantity: 1, rate: "" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const [c, g] = await Promise.all([api.get("/categories"), api.get("/grns")]);
    setCats(c.data); setGrns(g.data);
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const addItem = () => {
    if (!entry.product_name.trim()) return toast.error("Enter product name");
    setItems((p) => [...p, { ...entry, quantity: Number(entry.quantity), rate: Number(entry.rate) || 0, assets: [] }]);
    setEntry({ product_name: "", category_id: "", uom: "Nos", quantity: 1, rate: "" });
  };
  const removeItem = (i) => setItems((p) => p.filter((_, idx) => idx !== i));
  const addTag = (i) => setItems((p) => p.map((it, idx) => idx === i ? { ...it, assets: [...it.assets, { serial_no: "", tag_id: "" }] } : it));
  const setTag = (i, j, field, val) => setItems((p) => p.map((it, idx) => idx === i ? { ...it, assets: it.assets.map((a, aj) => aj === j ? { ...a, [field]: val } : a) } : it));

  const submit = async () => {
    if (!head.challan_no.trim() || !head.vendor_name.trim()) return toast.error("Challan No & Vendor are required");
    if (items.length === 0) return toast.error("Add at least one item");
    setSaving(true);
    try {
      const { data } = await api.post("/grns", { ...head, items });
      toast.success(`${data.grn_no} received · ${data.created_assets} asset(s) tagged`);
      setItems([]); setHead({ challan_no: "", vendor_name: "", received_date: new Date().toISOString().slice(0, 10), delivery_location: "Head Office" });
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-6" data-testid="grn-page">
      <div>
        <h2 className="font-head text-2xl font-bold text-slate-900">Stock GRN (Vendor Challan)</h2>
        <p className="text-slate-500 text-sm mt-1">Record vendor deliveries and tag individual asset serial numbers on receipt.</p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Field label="Challan No *"><input data-testid="grn-challan" value={head.challan_no} onChange={(e) => setHead({ ...head, challan_no: e.target.value })} className="ginp" placeholder="CH-1001" /></Field>
          <Field label="Vendor Name *"><input data-testid="grn-vendor" value={head.vendor_name} onChange={(e) => setHead({ ...head, vendor_name: e.target.value })} className="ginp" placeholder="Star Tech" /></Field>
          <Field label="Received Date"><input type="date" data-testid="grn-date" value={head.received_date} onChange={(e) => setHead({ ...head, received_date: e.target.value })} className="ginp" /></Field>
          <Field label="Delivery Location"><input data-testid="grn-location" value={head.delivery_location} onChange={(e) => setHead({ ...head, delivery_location: e.target.value })} className="ginp" /></Field>
        </div>

        <div className="border-t border-slate-100 pt-4">
          <div className="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
            <Field label="Product"><input data-testid="grn-item-name" value={entry.product_name} onChange={(e) => setEntry({ ...entry, product_name: e.target.value })} className="ginp" placeholder="Laptop" /></Field>
            <Field label="Category">
              <select data-testid="grn-item-cat" value={entry.category_id} onChange={(e) => setEntry({ ...entry, category_id: e.target.value })} className="ginp">
                <option value="">—</option>
                {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="UoM"><input data-testid="grn-item-uom" value={entry.uom} onChange={(e) => setEntry({ ...entry, uom: e.target.value })} className="ginp" /></Field>
            <Field label="Qty"><input type="number" min="1" data-testid="grn-item-qty" value={entry.quantity} onChange={(e) => setEntry({ ...entry, quantity: e.target.value })} className="ginp" /></Field>
            <Field label="Rate"><input type="number" min="0" data-testid="grn-item-rate" value={entry.rate} onChange={(e) => setEntry({ ...entry, rate: e.target.value })} className="ginp" placeholder="0" /></Field>
            <button onClick={addItem} data-testid="grn-add-item" className="py-2.5 px-4 rounded-lg bg-slate-800 hover:bg-slate-900 text-white font-semibold text-sm flex items-center justify-center gap-2 transition-colors"><Plus size={16} /> Add Item</button>
          </div>
        </div>

        {items.length > 0 && (
          <div className="space-y-3">
            {items.map((it, i) => (
              <div key={i} className="rounded-lg border border-slate-200 p-4" data-testid={`grn-item-row-${i}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Package size={16} className="text-amber-600" />
                    <span className="font-medium text-slate-800">{it.product_name}</span>
                    <span className="text-sm text-slate-500 font-mono">{it.quantity} {it.uom} × {bdt(it.rate)}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <button onClick={() => addTag(i)} data-testid={`grn-add-tag-${i}`} className="text-xs font-semibold text-sky-600 hover:text-sky-800 flex items-center gap-1"><Tag size={13} /> Add Serial/Tag</button>
                    <button onClick={() => removeItem(i)} className="text-slate-400 hover:text-red-600"><Trash2 size={15} /></button>
                  </div>
                </div>
                {it.assets.length > 0 && (
                  <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {it.assets.map((a, j) => (
                      <div key={j} className="flex gap-2">
                        <input placeholder="Serial No." data-testid={`grn-serial-${i}-${j}`} value={a.serial_no} onChange={(e) => setTag(i, j, "serial_no", e.target.value)} className="ginp text-xs" />
                        <input placeholder="Tag / Asset ID" data-testid={`grn-tag-${i}-${j}`} value={a.tag_id} onChange={(e) => setTag(i, j, "tag_id", e.target.value)} className="ginp text-xs" />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end">
          <button onClick={submit} disabled={saving} data-testid="grn-submit" className="px-6 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 transition-colors disabled:opacity-60"><Truck size={16} /> Receive Stock</button>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 font-head font-semibold text-slate-900">Recent GRNs</div>
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
            <th className="px-6 py-3 font-semibold">GRN No.</th><th className="px-6 py-3 font-semibold">Challan</th><th className="px-6 py-3 font-semibold">Vendor</th><th className="px-6 py-3 font-semibold">Items</th><th className="px-6 py-3 font-semibold">Received</th>
          </tr></thead>
          <tbody>
            {grns.length === 0 && <tr><td colSpan={5} className="px-6 py-8 text-center text-slate-400">No GRNs yet.</td></tr>}
            {grns.map((g) => (
              <tr key={g.id} className="border-b border-slate-50" data-testid={`grn-list-row-${g.grn_no}`}>
                <td className="px-6 py-3 font-mono text-slate-800">{g.grn_no}</td>
                <td className="px-6 py-3 text-slate-600">{g.challan_no}</td>
                <td className="px-6 py-3 text-slate-600">{g.vendor_name}</td>
                <td className="px-6 py-3 text-slate-600">{g.items.length}</td>
                <td className="px-6 py-3 text-slate-500">{(g.received_date || "").slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <style>{`.ginp{width:100%;padding:0.55rem 0.75rem;border:1px solid #cbd5e1;border-radius:0.5rem;font-size:0.875rem;outline:none}.ginp:focus{border-color:#d97706}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return <div><label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">{label}</label>{children}</div>;
}
