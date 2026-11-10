import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Search, PackageCheck, ShoppingCart } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/**
 * PR Handler decision modals (only rendered for users with can_handle_pr):
 *   <StockSelectionModal>  "Fulfill from Stock"  -> POST /requisitions/:id/fulfill-from-stock
 *   <BypassStockModal>     "Bypass Stock & Raise PR" -> POST /requisitions/:id/bypass-stock
 */

export function StockSelectionModal({ req, onClose, onDone }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [matchOnly, setMatchOnly] = useState(false);
  const [selected, setSelected] = useState([]);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!req) return;
    setLoading(true); setSelected([]); setNotes(""); setQ(""); setCategory(""); setMatchOnly(false);
    api.get(`/requisitions/${req.id}/stock-options`)
      .then(({ data }) => setData(data))
      .catch((e) => { toast.error(formatApiErrorDetail(e.response?.data?.detail)); onClose(); })
      .finally(() => setLoading(false));
    // eslint-disable-next-line
  }, [req?.id]);

  const categories = useMemo(
    () => [...new Set((data?.assets || []).map((a) => a.category_name).filter(Boolean))].sort(),
    [data]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data?.assets || []).filter((a) => {
      if (category && a.category_name !== category) return false;
      if (matchOnly && !a.matches_request) return false;
      if (!needle) return true;
      return [a.name, a.brand, a.specification, a.tag_id, a.serial_no, a.category_name]
        .some((v) => (v || "").toLowerCase().includes(needle));
    });
  }, [data, q, category, matchOnly]);

  const need = data?.total_quantity || 0;
  const toggle = (id) => setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  const chosen = (data?.assets || []).filter((a) => selected.includes(a.id));
  const hasSubstitute = chosen.some((a) => !a.matches_request);

  const confirm = async () => {
    if (selected.length < 1) return toast.error("Select at least one stock unit");
    setSaving(true);
    try {
      await api.post(`/requisitions/${req.id}/fulfill-from-stock`, { asset_ids: selected, notes: notes.trim() || null });
      toast.success("Stock selected — sent to IT Head for approval");
      onDone();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={!!req} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl" data-testid="stock-selection-modal">
        <DialogHeader>
          <DialogTitle>Fulfill from Stock — {req?.requisition_no}</DialogTitle>
        </DialogHeader>
        {loading || !data ? (
          <div className="py-10 text-center text-slate-400">Loading live inventory…</div>
        ) : (
          <div className="space-y-3">
            <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-900">
              Requested: {data.requested_items.map((it) => `${it.quantity} × ${it.product_name}${it.detailed_specs ? ` (${it.detailed_specs})` : ""}`).join(", ")}
              {" "}— you may select any available item and any quantity (fewer, more, or a different model or brand).
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="relative flex-1 min-w-[200px]">
                <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
                <input
                  value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, brand, specification, tag, serial…"
                  className="w-full border border-slate-300 rounded-lg pl-8 pr-3 py-2 text-sm" data-testid="stock-search"
                />
              </div>
              <select value={category} onChange={(e) => setCategory(e.target.value)}
                className="border border-slate-300 rounded-lg px-2.5 py-2 text-sm">
                <option value="">All categories</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <label className="flex items-center gap-1.5 text-sm text-slate-600">
                <input type="checkbox" checked={matchOnly} onChange={(e) => setMatchOnly(e.target.checked)} />
                Matching requested item only
              </label>
            </div>

            <div className="border border-slate-200 rounded-lg max-h-[320px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500 sticky top-0">
                  <tr>
                    <th className="px-3 py-2 w-8"></th>
                    <th className="px-3 py-2 text-left">Item</th>
                    <th className="px-3 py-2 text-left">Brand</th>
                    <th className="px-3 py-2 text-left">Category</th>
                    <th className="px-3 py-2 text-left">Specification</th>
                    <th className="px-3 py-2 text-left">Tag / Serial</th>
                    <th className="px-3 py-2 text-left"></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && (
                    <tr><td colSpan={7} className="px-3 py-8 text-center text-slate-400">No available stock matches.</td></tr>
                  )}
                  {rows.map((a) => (
                    <tr key={a.id} onClick={() => toggle(a.id)}
                      className={`border-t border-slate-100 cursor-pointer hover:bg-slate-50 ${selected.includes(a.id) ? "bg-emerald-50" : ""}`}
                      data-testid={`stock-row-${a.id}`}>
                      <td className="px-3 py-2"><input type="checkbox" readOnly checked={selected.includes(a.id)} /></td>
                      <td className="px-3 py-2 font-medium">{a.name}</td>
                      <td className="px-3 py-2">{a.brand || "—"}</td>
                      <td className="px-3 py-2 text-slate-600">{a.category_name || "—"}</td>
                      <td className="px-3 py-2 text-slate-700 text-xs max-w-[220px] whitespace-normal break-words" data-testid={`stock-spec-${a.id}`}>{a.specification || "—"}</td>
                      <td className="px-3 py-2 font-mono text-xs">{a.tag_id || a.serial_no || "—"}</td>
                      <td className="px-3 py-2 text-right">
                        {a.matches_request
                          ? <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">Matches request</span>
                          : <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">Substitute</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div>
              <label className="block text-sm text-slate-600 mb-1">
                Substitution / Allocation Notes (optional){hasSubstitute ? " — recommended: you selected a substitute item" : ""}
              </label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
                className="w-full border border-slate-300 rounded-lg p-2.5 text-sm" data-testid="stock-notes"
                placeholder="e.g. Core i5 not in stock — allocating Core i3 Gen 10 as agreed with requester" />
            </div>

            <div className="flex items-center justify-between pt-1">
              <span className="text-sm text-slate-500">{selected.length} selected · requested {need}</span>
              <div className="flex gap-2">
                <button onClick={onClose} className="px-4 py-2 rounded-lg text-slate-500 text-sm hover:text-slate-700">Cancel</button>
                <button onClick={confirm} disabled={saving || selected.length < 1} data-testid="btn-confirm-stock"
                  className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-2">
                  <PackageCheck size={16} /> {saving ? "Sending…" : "Confirm & Send to IT Head"}
                </button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function BypassStockModal({ req, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { setReason(""); }, [req?.id]);

  const confirm = async () => {
    if (!reason.trim()) return toast.error("Reason for bypassing stock is required");
    setSaving(true);
    try {
      await api.post(`/requisitions/${req.id}/bypass-stock`, { reason: reason.trim() });
      onDone();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={!!req} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="bypass-stock-modal">
        <DialogHeader>
          <DialogTitle>Bypass Stock & Raise PR — {req?.requisition_no}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-slate-600">
          Stock will not be used for this requisition, even if matching or substitute items are available.
          You will continue to the Purchase Requisition form.
        </p>
        <div>
          <label className="block text-sm text-slate-600 mb-1">Reason for Bypassing Stock <span className="text-red-500">*</span></label>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
            className="w-full border border-slate-300 rounded-lg p-2.5 text-sm" data-testid="bypass-reason"
            placeholder="e.g. Available stock does not meet the required specification" />
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-slate-500 text-sm hover:text-slate-700">Cancel</button>
          <button onClick={confirm} disabled={saving || !reason.trim()} data-testid="btn-confirm-bypass"
            className="px-4 py-2 rounded-lg bg-amber-600 text-white text-sm font-semibold hover:bg-amber-700 disabled:opacity-50 flex items-center gap-2">
            <ShoppingCart size={16} /> {saving ? "Saving…" : "Confirm & Raise PR"}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}