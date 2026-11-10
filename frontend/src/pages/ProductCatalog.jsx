import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, Search, Package, ListPlus } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";

const TYPES = {
  asset: "IT Asset",
  it_accessories: "IT Accessories",
  network: "Network",
  consumable: "Consumable",
  furniture: "Furniture",
};

// Master list of product names. Requisition, GRN (stock), PR and PO all use these exact
// names, which is what stops "Laptop" / "laptop" from being treated as different items.
export default function ProductCatalog() {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", product_type: "asset", brand: "" });
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulk, setBulk] = useState({ product_type: "asset", text: "" });

  const saveBulk = async () => {
    const names = bulk.text.split("\n").map((n) => n.trim()).filter(Boolean);
    if (!names.length) return toast.error("Paste at least one product name");
    try {
      const { data } = await api.post("/products/bulk", { product_type: bulk.product_type, names });
      toast.success(`${data.added} added${data.skipped ? `, ${data.skipped} already existed` : ""}`);
      setBulkOpen(false); setBulk({ ...bulk, text: "" }); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  const load = useCallback(async () => {
    const { data } = await api.get("/products");
    setRows(data);
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const openNew = () => { setEditing(null); setForm({ name: "", product_type: typeFilter || "asset", brand: "" }); setOpen(true); };
  const openEdit = (p) => { setEditing(p); setForm({ name: p.name, product_type: p.product_type, brand: p.brand || "" }); setOpen(true); };

  const save = async () => {
    if (!form.name.trim()) return toast.error("Enter a product name");
    try {
      if (editing) { await api.put(`/products/${editing.id}`, form); toast.success("Product updated"); }
      else { await api.post("/products", form); toast.success("Product added"); }
      setOpen(false); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const del = async (p) => {
    if (!window.confirm(`Remove "${p.name}" from the catalog? Existing requisitions and stock are not affected.`)) return;
    try { await api.delete(`/products/${p.id}`); toast.success("Removed"); load(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  const shown = useMemo(() => rows.filter((r) =>
    (!typeFilter || r.product_type === typeFilter) &&
    (!q.trim() || r.name.toLowerCase().includes(q.trim().toLowerCase()))), [rows, q, typeFilter]);

  return (
    <div className="space-y-6" data-testid="products-page">
      <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">Products</h2>
          <p className="text-slate-500 text-sm mt-1">
            Master list of product names. Requisitions, stock (GRN), PR and PO all use these exact names.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search products…" data-testid="product-search"
              className="pl-9 pr-4 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm w-56" />
          </div>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} data-testid="product-type-filter"
            className="py-2.5 px-3 rounded-lg border border-slate-300 focus:border-amber-500 outline-none text-sm">
            <option value="">All types</option>
            {Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <button onClick={() => { setBulk({ product_type: typeFilter || "asset", text: "" }); setBulkOpen(true); }} data-testid="btn-bulk-product"
            className="px-4 py-2.5 rounded-lg border border-amber-600 text-amber-700 hover:bg-amber-50 font-semibold text-sm flex items-center gap-2 transition-colors">
            <ListPlus size={16} /> Bulk Add
          </button>
          <button onClick={openNew} data-testid="btn-new-product"
            className="px-4 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm flex items-center gap-2 transition-colors">
            <Plus size={16} /> New Product
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
              <th className="px-6 py-3 font-semibold">Product name</th>
              <th className="px-6 py-3 font-semibold">Type</th>
              <th className="px-6 py-3 font-semibold">Brand</th>
              <th className="px-6 py-3 font-semibold">In stock</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan={5} className="py-10 text-center text-slate-400">No products found.</td></tr>
            )}
            {shown.map((p) => (
              <tr key={p.id} className="border-b border-slate-50 hover:bg-slate-50/60 transition-colors" data-testid={`product-row-${p.name}`}>
                <td className="px-6 py-3 font-medium text-slate-800"><span className="inline-flex items-center gap-2"><Package size={15} className="text-amber-600" /> {p.name}</span></td>
                <td className="px-6 py-3"><span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 text-xs font-medium">{TYPES[p.product_type] || p.product_type}</span></td>
                <td className="px-6 py-3 text-slate-600">{p.brand || "—"}</td>
                <td className="px-6 py-3 font-mono text-slate-700">{p.in_stock}</td>
                <td className="px-6 py-3">
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={() => openEdit(p)} className="px-3 py-1.5 rounded-lg border border-amber-300 text-amber-700 text-xs font-semibold hover:bg-amber-50 flex items-center gap-1.5 transition-colors"><Pencil size={13} /> Edit</button>
                    <button onClick={() => del(p)} className="px-3 py-1.5 rounded-lg border border-red-300 text-red-600 text-xs font-semibold hover:bg-red-50 flex items-center gap-1.5 transition-colors"><Trash2 size={13} /> Delete</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="product-dialog">
          <DialogHeader><DialogTitle>{editing ? "Edit Product" : "New Product"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <input placeholder="Product name (e.g. Dell Monitor)" data-testid="product-name-input" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp3" />
            <select data-testid="product-type-select" value={form.product_type}
              onChange={(e) => setForm({ ...form, product_type: e.target.value })} className="inp3">
              {Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <input placeholder="Default brand (optional, e.g. Logitech)" data-testid="product-brand-input" value={form.brand}
              onChange={(e) => setForm({ ...form, brand: e.target.value })} className="inp3" />
            <p className="text-xs text-slate-400">Names are unique regardless of capital letters or extra spaces.</p>
          </div>
          <DialogFooter>
            <button onClick={() => setOpen(false)} className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 font-semibold text-sm">Cancel</button>
            <button onClick={save} data-testid="btn-save-product" className="px-4 py-2 rounded-lg bg-amber-600 text-white font-semibold text-sm hover:bg-amber-700">Save</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={bulkOpen} onOpenChange={setBulkOpen}>
        <DialogContent data-testid="bulk-dialog">
          <DialogHeader><DialogTitle>Bulk add products</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <select value={bulk.product_type} onChange={(e) => setBulk({ ...bulk, product_type: e.target.value })} className="inp3" data-testid="bulk-type-select">
              {Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <textarea rows={10} value={bulk.text} onChange={(e) => setBulk({ ...bulk, text: e.target.value })}
              placeholder={"One product per line, e.g.\nLaptop\nDesktop Computer\nMonitor"} className="inp3 font-mono" data-testid="bulk-text" />
            <p className="text-xs text-slate-400">All lines are added under the type selected above. Names that already exist are skipped.</p>
          </div>
          <DialogFooter>
            <button onClick={() => setBulkOpen(false)} className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 font-semibold text-sm">Cancel</button>
            <button onClick={saveBulk} data-testid="btn-save-bulk" className="px-4 py-2 rounded-lg bg-amber-600 text-white font-semibold text-sm hover:bg-amber-700">Add all</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <style>{`.inp3{width:100%;padding:0.55rem 0.75rem;border:1px solid #cbd5e1;border-radius:0.5rem;font-size:0.875rem;outline:none}.inp3:focus{border-color:#d97706}`}</style>
    </div>
  );
}