import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2, Handshake, ArrowLeftRight, RefreshCw, Wand2, AlertCircle, CheckCircle2 } from "lucide-react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import SignaturePad from "@/components/SignaturePad";

// The slip type is never chosen by the user - it follows from what is on the slip.
const TYPE_META = {
  handover: { label: "New allocation", sub: "Hand Over", cls: "bg-emerald-100 text-emerald-700", Icon: Handshake },
  takeover: { label: "Return", sub: "Take Over", cls: "bg-sky-100 text-sky-700", Icon: ArrowLeftRight },
  swap: { label: "Replacement", sub: "Take Over + Hand Over", cls: "bg-amber-100 text-amber-700", Icon: RefreshCw },
};
const CONDITIONS = [["good", "Good"], ["damaged", "Damaged"], ["missing_parts", "Missing parts"]];
const DESTINATIONS = [["in_stock", "Back to stock"], ["under_repair", "Under repair"], ["scrapped", "Scrap"]];
const ACCESSORIES = ["Charger", "Bag", "Mouse"];
const DEFAULT_RETURN = { condition: "good", next_status: "in_stock", accessories: [], data_wiped: false };

export default function HandoverModule() {
  const navigate = useNavigate();
  const [emp, setEmp] = useState("");            // employee display name
  const [empId, setEmpId] = useState("");          // employee user id (picked from list)
  const [users, setUsers] = useState([]);
  const [deptId, setDeptId] = useState("");
  const [depts, setDepts] = useState([]);
  const [catalog, setCatalog] = useState([]);       // /products with live in_stock
  const [unitsByProduct, setUnitsByProduct] = useState({}); // product_id -> {tracked_by_quantity, units[]}
  const [openReqs, setOpenReqs] = useState([]);
  const [reqId, setReqId] = useState("");
  const [required, setRequired] = useState({});      // product_id -> {name, qty} when filled from a requisition
  const [lines, setLines] = useState([]);            // one row per unit (or one qty row for consumables)
  const [entry, setEntry] = useState({ product_id: "", quantity: 1, remarks: "", picked: [], brand: "" });
  const [remarks, setRemarks] = useState("");
  const [note, setNote] = useState("");
  const [prepSign, setPrepSign] = useState(null);
  const [recvSign, setRecvSign] = useState(null);
  const [saving, setSaving] = useState(false);
  const [held, setHeld] = useState([]);              // assets the chosen employee holds right now
  const [heldLoading, setHeldLoading] = useState(false);
  const [returnSel, setReturnSel] = useState({});    // asset_id -> {condition,next_status,accessories,data_wiped}
  const [receiveNow, setReceiveNow] = useState(true);

  const load = useCallback(async () => {
    const [d, s, r, u] = await Promise.all([
      api.get("/departments"), api.get("/products"),
      api.get("/requisitions", { params: { scope: "handover" } }).catch(() => ({ data: [] })),
      api.get("/users/lookup").catch(() => ({ data: [] })),
    ]);
    setDepts(d.data); setCatalog(s.data); setUsers(u.data);
    setOpenReqs(r.data.filter((x) => x.status === "stock_received_in_it"));
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  // Employee first: whenever the employee changes, load what they currently hold.
  useEffect(() => {
    setReturnSel({});
    if (!empId) { setHeld([]); return undefined; }
    let live = true;
    setHeldLoading(true);
    api.get(`/users/${empId}/held-assets`)
      .then(({ data }) => { if (live) setHeld(data.assets || []); })
      .catch((e) => { if (live) { setHeld([]); toast.error(formatApiErrorDetail(e.response?.data?.detail)); } })
      .finally(() => { if (live) setHeldLoading(false); });
    return () => { live = false; };
  }, [empId]);

  const returnIds = Object.keys(returnSel);
  const type = lines.length > 0 && returnIds.length > 0 ? "swap" : returnIds.length > 0 ? "takeover" : "handover";
  const hasAnything = lines.length > 0 || returnIds.length > 0;
  const meta = TYPE_META[type];

  const toggleReturn = (a) => setReturnSel((m) => {
    const n = { ...m };
    if (n[a.id]) delete n[a.id]; else n[a.id] = { ...DEFAULT_RETURN };
    return n;
  });
  const returnAll = () => setReturnSel(Object.fromEntries(held.filter((a) => !a.return_pending).map((a) => [a.id, { ...DEFAULT_RETURN }])));
  const setRet = (id, patch) => setReturnSel((m) => ({ ...m, [id]: { ...m[id], ...patch } }));
  // Picking a condition suggests where the device should go; IT can still override it.
  const onCondition = (id, c) => setRet(id, { condition: c, next_status: c === "good" ? "in_stock" : "under_repair" });
  const toggleAcc = (id, acc) => setReturnSel((m) => {
    const cur = m[id];
    const has = cur.accessories.includes(acc);
    return { ...m, [id]: { ...cur, accessories: has ? cur.accessories.filter((x) => x !== acc) : [...cur.accessories, acc] } };
  });
  const prod = catalog.find((c) => c.id === entry.product_id) || null;

  const loadUnits = useCallback(async (pid) => {
    const { data } = await api.get(`/products/${pid}/units`);
    setUnitsByProduct((m) => ({ ...m, [pid]: data }));
    return data;
  }, []);

  // Units of the chosen product that are not already on this slip.
  const usedIds = useMemo(() => new Set(lines.map((l) => l.asset_id).filter(Boolean)), [lines]);
  const onSlipQty = (pid) => lines.filter((l) => l.product_id === pid).reduce((n, l) => n + l.quantity, 0);
  const freeUnits = prod ? (unitsByProduct[prod.id]?.units || []).filter((u) => !usedIds.has(u.id)) : [];
  const byQty = !!prod?.tracked_by_quantity;
  const unitsLoaded = !!(prod && unitsByProduct[prod.id]);
  const available = !prod ? 0 : byQty ? prod.in_stock - onSlipQty(prod.id) : unitsLoaded ? freeUnits.length : prod.in_stock;
  const qtyN = Math.max(parseInt(entry.quantity, 10) || 0, 0);
  const shortMsg = prod && qtyN > available ? `Only ${available} ${prod.name} in stock, you asked for ${qtyN}.` : null;
  // Not a real shortage: every available unit is already in the "Items to issue" table (e.g. auto-picked
  // from a linked requisition). Adding is still blocked via shortMsg; only the wording differs.
  const allOnSlip = !!prod && available <= 0 && onSlipQty(prod.id) > 0;

  const onProductPick = async (pid) => {
    const p = catalog.find((c) => c.id === pid);
    setEntry({ product_id: pid, quantity: 1, remarks: "", picked: [], brand: p?.brand || "" });
    if (pid && !p?.tracked_by_quantity) {
      try { await loadUnits(pid); } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    }
  };
  // "Replace": tick the old asset for return and jump to the issue picker with the same product.
  const replaceAsset = async (a) => {
    setReturnSel((m) => ({ ...m, [a.id]: m[a.id] || { ...DEFAULT_RETURN } }));
    const p = catalog.find((c) => c.name.trim().toLowerCase() === (a.name || "").trim().toLowerCase());
    if (!p) toast.info("Return ticked - pick the replacement product below.");
    else if (p.in_stock <= 0) toast.error(`No ${p.name} in stock to issue as a replacement.`);
    else await onProductPick(p.id);
    document.getElementById("ho-issue-section")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const onQty = (v) => setEntry((e) => ({ ...e, quantity: v, picked: e.picked.slice(0, Math.max(parseInt(v, 10) || 0, 0)) }));
  const togglePick = (uid) => setEntry((e) => {
    if (e.picked.includes(uid)) return { ...e, picked: e.picked.filter((x) => x !== uid) };
    if (e.picked.length >= qtyN) { toast.error(`Qty is ${qtyN} — untick a unit first or raise the quantity`); return e; }
    return { ...e, picked: [...e.picked, uid] };
  });
  const autoPick = () => {
    if (qtyN < 1) return toast.error("Enter a quantity first");
    if (freeUnits.length < qtyN) return toast.error(`Only ${freeUnits.length} ${prod.name} in stock, you asked for ${qtyN}.`);
    setEntry((e) => ({ ...e, picked: freeUnits.slice(0, qtyN).map((u) => u.id) }));
  };

  const unitLine = (p, u, remarks) => ({
    product_id: p.id, item: p.name, category_name: p.category_name, brand: u.brand || p.brand || "",
    quantity: 1, asset_id: u.id, tag_id: u.tag_id, serial_no: u.serial_no, tracked_by_quantity: false, remarks: remarks || null,
  });

  const canAdd = !!prod && qtyN >= 1 && !shortMsg && (byQty || entry.picked.length === qtyN);
  const addItem = () => {
    if (!prod) return toast.error("Select a product");
    if (qtyN < 1) return toast.error("Quantity must be at least 1");
    if (shortMsg) return toast.error(shortMsg);
    if (!byQty) {
      if (entry.picked.length !== qtyN) return toast.error(`Select ${qtyN} unit(s) of ${prod.name} — ${entry.picked.length} selected`);
      const picked = freeUnits.filter((u) => entry.picked.includes(u.id));
      setLines((p) => [...p, ...picked.map((u) => unitLine(prod, u, entry.remarks))]);
    } else {
      setLines((p) => [...p, {
        product_id: prod.id, item: prod.name, category_name: prod.category_name, brand: entry.brand || prod.brand || "",
        quantity: qtyN, asset_id: null, tag_id: null, serial_no: null, tracked_by_quantity: byQty, remarks: entry.remarks || null,
      }]);
    }
    setEntry({ product_id: "", quantity: 1, remarks: "", picked: [], brand: "" });
  };
  const removeLine = (i) => setLines((p) => p.filter((_, idx) => idx !== i));

  const onReqPick = async (id) => {
    setReqId(id); setLines([]); setRequired({});
    const r = openReqs.find((x) => x.id === id);
    if (!r) return;
    const forName = (r.requisition_for || r.requisitioner_name || "").trim();
    const dId = r.requisitioner_department_id || "";
    // Same person as the requester -> use their id; requested on behalf of someone else ->
    // find that exact person within the department (never guess across departments).
    const sameAsRequester = !r.requisition_for || r.requisition_for.trim().toLowerCase() === (r.requisitioner_name || "").trim().toLowerCase();
    const match = sameAsRequester
      ? users.find((u) => u.id === r.requisitioner_id)
      : users.find((u) => u.name.trim().toLowerCase() === forName.toLowerCase() && (!dId || u.department_id === dId));
    setEmp(match ? match.name : forName);
    setEmpId(match ? match.id : "");
    if (match?.department_id) setDeptId(match.department_id);
    else if (dId) setDeptId(dId);

    // Auto-pick the units for every requisition line and put them in the table below, where
    // they can be reviewed / removed before saving. Shortages are reported, never hidden.
    const need = {}, built = [], problems = [];
    for (const it of r.items) {
      const p = catalog.find((c) => c.name.trim().toLowerCase() === (it.product_name || "").trim().toLowerCase());
      const n = Number(it.quantity) || 1;
      if (!p) { problems.push(`${it.product_name} is not in the product catalog.`); continue; }
      need[p.id] = { name: p.name, qty: (need[p.id]?.qty || 0) + n };
      if (p.tracked_by_quantity) {
        if (p.in_stock < n) { problems.push(`Only ${p.in_stock} ${p.name} in stock, you asked for ${n}.`); continue; }
        built.push({ product_id: p.id, item: p.name, category_name: p.category_name, brand: p.brand || "", quantity: n,
          asset_id: null, tag_id: null, serial_no: null, tracked_by_quantity: true, remarks: it.remarks || null });
        continue;
      }
      let data;
      try { data = await loadUnits(p.id); } catch { problems.push(`Could not load units for ${p.name}.`); continue; }
      const taken = new Set(built.map((l) => l.asset_id));
      const free = data.units.filter((u) => !taken.has(u.id));
      if (free.length < n) { problems.push(`Only ${free.length} ${p.name} in stock, you asked for ${n}.`); continue; }
      free.slice(0, n).forEach((u) => built.push(unitLine(p, u, it.remarks)));
    }
    setRequired(need); setLines(built);
    if (problems.length) toast.error(problems.join(" "), { duration: 8000 });
  };

  // Requisition-driven slips must cover exactly what was requested.
  const shortages = Object.entries(required).map(([pid, r]) => ({ ...r, have: onSlipQty(pid) })).filter((r) => r.have !== r.qty);

  const submit = async () => {
    if (!empId) return toast.error("Select the employee from the list");
    if (!hasAnything) return toast.error("Tick an asset to take back, or add an item to issue");
    if (shortages.length) return toast.error(shortages.map((r) => `${r.name}: ${r.have} of ${r.qty} selected`).join(" · "));
    setSaving(true);
    try {
      const items = lines.map((l) => ({
        item: l.item, product_id: l.product_id, brand: l.brand || null, quantity: l.quantity,
        remarks: l.remarks, asset_id: l.asset_id || null, tracked_by_quantity: !!l.tracked_by_quantity,
      }));
      const return_items = returnIds.map((id) => ({ asset_id: id, ...returnSel[id] }));
      const { data } = await api.post("/handovers", {
        employee_name: emp, employee_user_id: empId, department_id: deptId || null, items, return_items,
        receive_now: return_items.length > 0 && receiveNow, remarks: remarks || null,
        note: note || null, prepared_by_sign: prepSign, received_by_sign: recvSign,
        requisition_id: reqId || null,
      });
      toast.success(`${data.slip_no} recorded - ${(TYPE_META[data.type] || meta).label}`);
      navigate("/handover/records");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
      load().catch(() => {});
      // the employee's holdings may have changed under us - refresh them
      if (empId) api.get(`/users/${empId}/held-assets`).then(({ data }) => setHeld(data.assets || [])).catch(() => {});
    } finally { setSaving(false); }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-4" data-testid="handover-module-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">Handover</h2>
          <p className="text-slate-500 text-sm mt-0.5">Pick the employee first - the slip becomes a Hand Over, Take Over or Replacement based on what you select.</p>
        </div>
        <div data-testid="ho-type-badge" className={`px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 ${hasAnything ? meta.cls : "bg-slate-100 text-slate-500"}`}>
          {hasAnything ? <><meta.Icon size={16} /> {meta.label} <span className="font-normal opacity-75">· {meta.sub}</span></> : "Type is detected automatically"}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
        {(
          <Field label="Link to Requisition (optional)">
            <select data-testid="ho-requisition" value={reqId} onChange={(e) => onReqPick(e.target.value)} className="hinp">
              <option value="">— none — (not fulfilling a specific requisition)</option>
              {openReqs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.requisition_no} — {r.requisitioner_name} — {r.items.map((it) => `${it.quantity} × ${it.product_name}`).join(", ")}
                </option>
              ))}
            </select>
            <p className="text-xs text-slate-400 mt-1">Link it so the requisition closes once this handover is confirmed.</p>
          </Field>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Employee *">
            <select data-testid="ho-employee" value={empId} className="hinp"
              onChange={(e) => {
                const u = users.find((x) => x.id === e.target.value);
                setEmpId(u ? u.id : ""); setEmp(u ? u.name : "");
                if (u?.department_id) setDeptId(u.department_id);
              }}>
              <option value="">{deptId ? "Select employee…" : "Select employee (or pick department first)…"}</option>
              {users.filter((u) => !deptId || u.department_id === deptId).map((u) => (
                <option key={u.id} value={u.id}>{u.name}{!deptId && u.department_name ? ` — ${u.department_name}` : ""}</option>
              ))}
            </select>
          </Field>
          <Field label="Department">
            <select data-testid="ho-dept" value={deptId} className="hinp"
              onChange={(e) => {
                const v = e.target.value;
                setDeptId(v);
                // a chosen employee who is not in the new department is cleared
                const cur = users.find((x) => x.id === empId);
                if (cur && v && cur.department_id !== v) { setEmpId(""); setEmp(""); }
              }}>
              <option value="">—</option>
              {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </Field>
        </div>

        {empId && (
          <div className="border-t border-slate-100 pt-4 space-y-3" data-testid="ho-held-panel">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-semibold text-slate-700">
                Currently holding {heldLoading ? "…" : <span className="text-slate-400 font-normal">({held.length})</span>}
              </div>
              {held.some((a) => !a.return_pending) && (
                <button type="button" onClick={returnAll} data-testid="ho-return-all"
                  className="px-3 py-1.5 rounded-lg border border-sky-500 text-sky-700 hover:bg-sky-50 text-xs font-semibold flex items-center gap-1.5">
                  <ArrowLeftRight size={14} /> Return all assets
                </button>
              )}
            </div>
            {!heldLoading && held.length === 0 && (
              <p className="text-sm text-slate-400" data-testid="ho-held-empty">{emp} has no assets right now - anything you issue below is a new allocation.</p>
            )}
            {held.length > 0 && (
              <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
                {held.map((a) => {
                  const sel = returnSel[a.id];
                  return (
                    <div key={a.id} data-testid={`ho-held-${a.id}`} className={sel ? "bg-sky-50/60" : ""}>
                      <div className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                        <input type="checkbox" checked={!!sel} disabled={a.return_pending} onChange={() => toggleReturn(a)} data-testid={`ho-return-${a.id}`} />
                        <span className="font-medium text-slate-800 min-w-[7rem]">{a.name}</span>
                        <span className="font-mono text-slate-700 w-28">{a.tag_id || "—"}</span>
                        <span className="font-mono text-slate-500 flex-1">S/N {a.serial_no || "—"}</span>
                        <span className="text-xs text-slate-400">{a.assigned_at ? `since ${a.assigned_at.slice(0, 10)}` : ""}</span>
                        {a.return_pending ? (
                          <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 text-xs font-semibold">Return pending · {a.pending_return_slip_no || "—"}</span>
                        ) : (
                          <button type="button" onClick={() => replaceAsset(a)} data-testid={`ho-replace-${a.id}`}
                            className="px-2.5 py-1 rounded-lg border border-amber-500 text-amber-700 hover:bg-amber-50 text-xs font-semibold flex items-center gap-1.5">
                            <RefreshCw size={13} /> Replace
                          </button>
                        )}
                      </div>
                      {sel && (
                        <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_2fr] gap-3 px-3 pb-3 pl-9 text-sm" data-testid={`ho-return-detail-${a.id}`}>
                          <Field label="Condition">
                            <select value={sel.condition} onChange={(e) => onCondition(a.id, e.target.value)} className="hinp">
                              {CONDITIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                            </select>
                          </Field>
                          <Field label="Then">
                            <select value={sel.next_status} onChange={(e) => setRet(a.id, { next_status: e.target.value })} className="hinp">
                              {DESTINATIONS.filter(([v]) => v !== "in_stock" || sel.condition === "good").map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                            </select>
                          </Field>
                          <Field label="Accessories returned">
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
                              {ACCESSORIES.map((acc) => (
                                <label key={acc} className="flex items-center gap-1.5 text-sm text-slate-600 cursor-pointer">
                                  <input type="checkbox" checked={sel.accessories.includes(acc)} onChange={() => toggleAcc(a.id, acc)} /> {acc}
                                </label>
                              ))}
                              <label className="flex items-center gap-1.5 text-sm text-slate-600 cursor-pointer">
                                <input type="checkbox" checked={sel.data_wiped} onChange={(e) => setRet(a.id, { data_wiped: e.target.checked })} /> Data wiped
                              </label>
                            </div>
                          </Field>
                          {sel.next_status === "in_stock" && !sel.data_wiped && (
                            <p className="md:col-span-3 text-xs text-amber-600">Tip: wipe the device before it goes back to stock.</p>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        <div id="ho-issue-section" className={`border-t border-slate-100 pt-4 space-y-3 ${empId ? "" : "opacity-50 pointer-events-none"}`} data-testid="ho-issue-section">
          <div className="text-sm font-semibold text-slate-700">
            Issue to employee <span className="text-slate-400 font-normal">{empId ? "- leave empty for a plain return" : "- select the employee first"}</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-[2fr_1fr_1fr_0.7fr_auto] gap-3 items-end">
            <Field label="Product *">
              <select data-testid="ho-product" value={entry.product_id} onChange={(e) => onProductPick(e.target.value)} className="hinp">
                <option value="">Select product…</option>
                {Object.entries(catalog.reduce((g, c) => { (g[c.category_name] = g[c.category_name] || []).push(c); return g; }, {})).map(([cat, ps]) => (
                  <optgroup key={cat} label={cat}>
                    {ps.map((c) => {
                      const out = c.in_stock <= 0;
                      return (
                        <option key={c.id} value={c.id} disabled={out} style={out ? { color: "#94a3b8" } : undefined}>
                          {c.name} — {out ? "out of stock" : `${c.in_stock} in stock`}
                        </option>
                      );
                    })}
                  </optgroup>
                ))}
              </select>
            </Field>
            <Field label="Category"><input data-testid="ho-category" value={prod?.category_name || ""} readOnly placeholder="Auto" className="hinp bg-slate-50 text-slate-600" /></Field>
            <Field label="Brand">
              <input data-testid="ho-brand" value={prod?.brand || (prod && !byQty ? "Per unit (below)" : "")} readOnly placeholder="Auto" className="hinp bg-slate-50 text-slate-600" />
            </Field>
            <Field label="Qty *"><input type="number" min="1" data-testid="ho-qty" value={entry.quantity} onChange={(e) => onQty(e.target.value)} className="hinp" /></Field>
            <button onClick={addItem} disabled={!canAdd} data-testid="ho-add-item" className="py-2.5 px-4 rounded-lg bg-slate-800 hover:bg-slate-900 text-white font-semibold text-sm flex items-center justify-center gap-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"><Plus size={16} /> Add</button>
          </div>

          {shortMsg && !allOnSlip && (
            <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2" data-testid="ho-short-msg">
              <AlertCircle size={16} /> {shortMsg}
            </div>
          )}
          {allOnSlip && (
            <div className="flex items-center gap-2 text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2" data-testid="ho-all-on-slip">
              <CheckCircle2 size={16} className="text-emerald-600" /> All available {prod.name} ({onSlipQty(prod.id)}) are already on this slip below.
            </div>
          )}

          {prod && byQty && !shortMsg && (
            <p className="text-xs text-slate-500" data-testid="ho-qty-note">
              {prod.name} is a consumable with no serial numbers — it is tracked by quantity ({available} available), so no unit needs to be picked.
            </p>
          )}

          {prod && !byQty && (
            <div className="rounded-lg border border-slate-200 p-3" data-testid="ho-unit-picker">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <div className="text-sm font-semibold text-slate-700">
                  Pick the exact units — <span className={entry.picked.length === qtyN && qtyN > 0 ? "text-emerald-600" : "text-amber-600"} data-testid="ho-picked-count">{entry.picked.length} of {qtyN} selected</span>
                </div>
                <button type="button" onClick={autoPick} disabled={qtyN < 1 || freeUnits.length < qtyN} data-testid="ho-autopick"
                  className="px-3 py-1.5 rounded-lg border border-amber-500 text-amber-700 hover:bg-amber-50 text-xs font-semibold flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed">
                  <Wand2 size={14} /> Auto-pick {qtyN || ""}
                </button>
              </div>
              {freeUnits.length === 0 ? (
                <p className="text-sm text-slate-400">{allOnSlip ? `All available ${prod.name} units are already on this slip.` : `No free units of ${prod.name} left.`}</p>
              ) : (
                <div className="max-h-48 overflow-y-auto divide-y divide-slate-100 border border-slate-100 rounded-md">
                  {freeUnits.map((u) => {
                    const on = entry.picked.includes(u.id);
                    return (
                      <label key={u.id} data-testid={`ho-unit-${u.id}`} className={`flex items-center gap-3 px-3 py-2 text-sm cursor-pointer ${on ? "bg-emerald-50" : "hover:bg-slate-50"}`}>
                        <input type="checkbox" checked={on} onChange={() => togglePick(u.id)} />
                        <span className="font-mono text-slate-800 w-32">{u.tag_id || "—"}</span>
                        <span className="font-mono text-slate-500 flex-1">S/N {u.serial_no || "—"}</span>
                        <span className="text-slate-600">{u.brand || "No brand"}</span>
                        {on && <CheckCircle2 size={15} className="text-emerald-600" />}
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {lines.length > 0 && (
          <div data-testid="ho-selected-lines">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
              Items to issue (reserved when you save)
            </div>
            <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
              <thead><tr className="text-left text-xs uppercase tracking-wider text-slate-500 bg-slate-50"><th className="px-4 py-2">Item</th><th className="px-4 py-2">Brand</th><th className="px-4 py-2">Tag</th><th className="px-4 py-2">Serial</th><th className="px-4 py-2">Qty</th><th className="px-4 py-2"></th></tr></thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={`${l.asset_id || l.product_id}-${i}`} className="border-t border-slate-100" data-testid={`ho-item-row-${i}`}>
                    <td className="px-4 py-2 font-medium text-slate-800">{l.item}</td>
                    <td className="px-4 py-2 text-slate-600">{l.brand || "—"}</td>
                    <td className="px-4 py-2 font-mono text-slate-700">{l.tag_id || (l.tracked_by_quantity ? "by qty" : "—")}</td>
                    <td className="px-4 py-2 font-mono text-slate-500">{l.serial_no || "—"}</td>
                    <td className="px-4 py-2 font-mono">{l.quantity}</td>
                    <td className="px-4 py-2 text-right"><button onClick={() => removeLine(i)} className="text-slate-400 hover:text-red-600"><Trash2 size={15} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {shortages.length > 0 && (
              <div className="mt-2 flex items-start gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2" data-testid="ho-req-shortage">
                <AlertCircle size={16} className="mt-0.5 shrink-0" />
                <span>The linked requisition needs {shortages.map((r) => `${r.qty} ${r.name} (${r.have} selected)`).join(", ")}. Add the missing units, or unlink the requisition.</span>
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Remarks"><textarea data-testid="ho-remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} rows={2} className="hinp resize-none" /></Field>
          <Field label="Note"><textarea data-testid="ho-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="hinp resize-none" placeholder="Optional note for the slip" /></Field>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
          <SignaturePad label="IT Staff Signature (Prepared By)" testid="ho-sign-prepared" onChange={setPrepSign} />
          {/* <SignaturePad label="Employee Signature (Received By)" testid="ho-sign-received" onChange={setRecvSign} /> */}
          <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs leading-relaxed text-slate-500 md:mt-6">
            You are responsible for the proper care, handling, and safekeeping of the assigned IT equipment, and must return it in good condition upon request or when your assignment/employment ends.
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
          {returnIds.length > 0 ? (
            <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer" data-testid="ho-receive-now">
              <input type="checkbox" checked={receiveNow} onChange={(e) => setReceiveNow(e.target.checked)} />
              The returned device(s) are with IT now - mark as received
            </label>
          ) : <span />}
          <button onClick={submit} disabled={saving || !hasAnything} data-testid="ho-submit" className="px-6 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm transition-colors disabled:opacity-60">
            {saving ? "Saving…" : hasAnything ? `Save ${meta.sub} Slip` : "Save Slip"}
          </button>
        </div>
      </div>
      <style>{`.hinp{width:100%;padding:0.55rem 0.75rem;border:1px solid #cbd5e1;border-radius:0.5rem;font-size:0.875rem;outline:none}.hinp:focus{border-color:#d97706}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return <div><label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">{label}</label>{children}</div>;
}