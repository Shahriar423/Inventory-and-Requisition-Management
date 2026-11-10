import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Navigate, useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowLeft, CheckCircle2, ClipboardList, ImageIcon, Loader2, MessageSquare, PackageSearch, PackageX,
  Send, Settings, ShieldCheck, Truck, Undo2,
} from "lucide-react";
import api, { API, formatApiErrorDetail, requestDataRefresh, withAuthParam } from "@/lib/apiClient";
import { useAuth } from "@/context/AuthContext";

const btn = "h-9 px-3 rounded-md border border-slate-300 bg-white text-sm text-slate-700 hover:bg-slate-50 inline-flex items-center gap-2 disabled:opacity-50";
const btnPrimary = "h-9 px-4 rounded-md bg-amber-600 text-white text-sm font-semibold hover:bg-amber-700 inline-flex items-center gap-2 disabled:opacity-50";
const inp = "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:border-amber-500";
const lbl = "block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1";

const STATUS_TONE = {
  reported_to_it: "bg-red-50 text-red-700 ring-red-200", under_review: "bg-amber-50 text-amber-700 ring-amber-200",
  returned_to_it: "bg-sky-50 text-sky-700 ring-sky-200", waiting_clarification: "bg-violet-50 text-violet-700 ring-violet-200",
  waiting_for_stock: "bg-orange-50 text-orange-700 ring-orange-200", redelivery_in_progress: "bg-blue-50 text-blue-700 ring-blue-200",
  delivered_again: "bg-blue-50 text-blue-700 ring-blue-200", confirmed: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  closed: "bg-slate-100 text-slate-600 ring-slate-200",
};
const REASONS = {
  wrong_spec: "Wrong size or specification", wrong_model: "Wrong model or brand", damaged: "Damaged or not working",
  missing_accessory: "Missing accessory", quantity_short: "Quantity short", nothing_delivered: "Nothing delivered", other: "Other",
};
const CLOSE_REASONS = {
  resolved: "Resolved — employee confirmed the correct item", requirement_cancelled: "Requirement cancelled",
  employee_withdrew: "Employee withdrew the report", duplicate: "Duplicate / raised in error", other: "Other (explain below)",
};
const fmt = (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const errText = (e, f = "Something went wrong") => {
  const d = e?.response?.data?.detail;
  return (d && (typeof d === "object" && d.message ? d.message : formatApiErrorDetail(d))) || f;
};

function StatusChip({ status, label }) {
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap ${STATUS_TONE[status] || "bg-slate-100 text-slate-600 ring-slate-200"}`}>{label}</span>;
}
const Section = ({ title, icon: Icon, children, right }) => (
  <section className="rounded-lg border border-slate-200 bg-white">
    <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-slate-100">
      <h3 className="text-sm font-semibold text-slate-800 inline-flex items-center gap-2">{Icon && <Icon size={15} className="text-slate-400" />}{title}</h3>{right}
    </div>
    <div className="p-4">{children}</div>
  </section>
);

/* ============================= case detail ============================= */
function CaseDetail({ id, back }) {
  const [c, setC] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [panel, setPanel] = useState("");           // which IT form is open
  const [form, setForm] = useState({});
  const [stock, setStock] = useState(null);
  const [mismatch, setMismatch] = useState(null);
  const [noteText, setNoteText] = useState("");
  const [answer, setAnswer] = useState("");

  const load = useCallback(async () => {
    try { const { data } = await api.get(`/corrections/${id}`); setC(data); setError(""); }
    catch (e) { setError(errText(e, "This case is not available.")); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const call = async (key, fn, ok) => {
    setBusy(key);
    try { const { data } = await fn(); setC(data); if (ok) toast.success(ok); setPanel(""); setForm({}); setMismatch(null); requestDataRefresh(); return data; }
    catch (e) {
      const d = e?.response?.data?.detail;
      if (d && typeof d === "object" && d.code === "spec_mismatch") { setMismatch(d); return null; }
      toast.error(errText(e)); return null;
    } finally { setBusy(""); }
  };
  const post = (path, body) => api.post(`/corrections/${id}/${path}`, body || {});
  const can = (a) => c?.allowed_actions?.includes(a);
  const open = (p) => { setPanel(panel === p ? "" : p); setForm({}); setMismatch(null); };

  const [stockQ, setStockQ] = useState("");
  const [stockOpen, setStockOpen] = useState(null);     // asset_id of the unit whose details are expanded
  const stockShown = useMemo(() => {
    const q = stockQ.trim().toLowerCase();
    const all = stock?.options || [];
    if (!q) return all;
    return all.filter((o) => [o.name, o.brand, o.model, o.specification, o.serial_no, o.tag_id].filter(Boolean).join(" ").toLowerCase().includes(q));
  }, [stock, stockQ]);

  const loadStock = async () => {
    setStockQ(""); setStockOpen(null);
    open("replace");
    try { const { data } = await api.get(`/corrections/${id}/stock-options`); setStock(data); } catch (e) { toast.error(errText(e)); }
  };

  if (error) return <div className="space-y-4"><button className={btn} onClick={back}><ArrowLeft size={15} /> Back</button><div className="rounded-lg border bg-white p-10 text-center text-sm text-slate-600">{error}</div></div>;
  if (!c) return <div className="flex items-center gap-2 p-6 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" /> Loading…</div>;

  const it = c.viewer_role === "it";
  const req = c.item.requested || {};
  const dlv = c.item.delivered || {};
  const att = c.current_attempt;
  const photo = c.attachment_file_id ? withAuthParam(`${API}/files/${c.attachment_file_id}/download`) : null;

  return (
    <div className="space-y-5" data-testid="case-detail">
      <div>
        <button className="text-sm text-slate-500 hover:text-slate-800 inline-flex items-center gap-1 mb-1" onClick={back}><ArrowLeft size={14} /> Back</button>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-head text-2xl font-bold text-slate-900 font-mono">{c.case_no}</h2>
          <StatusChip status={c.status} label={c.status_label} />
          {c.overdue && <span className="inline-flex items-center gap-1 text-xs font-medium text-red-600"><AlertTriangle size={13} /> Overdue</span>}
          {c.escalated_at && <span className="text-xs text-red-600">Escalated to IT Head</span>}
          <span className="text-xs text-slate-500">Attempt {att.attempt_no}{c.failed_attempts > 0 && ` · ${c.failed_attempts} failed`}</span>
        </div>
        <div className="text-sm text-slate-500 mt-1">
          {c.item.product_name} · {c.employee_name} · {c.requisition_no || "—"} · slip {c.original_slip_no || "—"} · IT: {c.responsible_it_name || "—"}
        </div>
      </div>

      {c.status === "reported_to_it" && c.viewer_role === "employee" && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">Reported to IT — Waiting for Correction. IT has been notified and will update you here.</div>
      )}
      {c.status === "delivered_again" && c.viewer_role === "employee" && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">A replacement was delivered. Please confirm it from your 🔔 notifications.</div>
      )}

      {/* IT actions */}
      {it && (c.allowed_actions || []).filter((a) => a !== "note").length > 0 && (
        <Section title="IT actions" icon={ShieldCheck}>
          <div className="flex flex-wrap gap-2">
            {can("acknowledge") && <button className={btnPrimary} disabled={!!busy} onClick={() => call("ack", () => post("acknowledge"), "Acknowledged")} data-testid="act-ack"><CheckCircle2 size={15} /> Acknowledge</button>}
            {can("record_return") && <button className={btn} onClick={() => open("return")} data-testid="act-return"><Undo2 size={15} /> Record Return</button>}
            {can("replace") && <button className={btn} onClick={loadStock} data-testid="act-replace"><PackageSearch size={15} /> Arrange Replacement</button>}
            {can("request_stock") && <button className={btn} onClick={() => open("stock")} data-testid="act-stock"><PackageX size={15} /> Correct item not in stock</button>}
            {can("clarify") && <button className={btn} onClick={() => open("clarify")} data-testid="act-clarify"><Send size={15} /> Send for Clarification</button>}
            {can("deliver") && <button className={btnPrimary} disabled={!!busy} onClick={() => call("deliver", () => post("deliver"), "Marked delivered — the employee was asked to confirm")} data-testid="act-deliver"><Truck size={15} /> Handover Done (delivered)</button>}
            {can("cancel_replacement") && <button className={btn} disabled={!!busy} data-testid="act-cancel-replacement"
              onClick={() => { if (window.confirm("Cancel the selected product? It goes back to stock and its handover slip is removed, so you can select another one.")) call("cancel-replacement", () => post("cancel-replacement"), "Selection cancelled — the unit is back in stock"); }}><Undo2 size={15} /> Cancel Selected Product</button>}
            {can("close") && <button className={btn} onClick={() => open("close")} data-testid="act-close">Close Case</button>}
            {can("reopen") && <button className={btn} onClick={() => open("reopen")}>Reopen</button>}
          </div>

          {!can("replace") && c.requires_return && (
            <p className="text-xs text-slate-500 mt-3">The rejected unit must be physically returned and verified before a replacement can be arranged.</p>
          )}

          {panel === "return" && (
            <div className="mt-4 grid gap-3 sm:grid-cols-3 rounded-md border border-slate-200 p-3" data-testid="form-return">
              <label className="sm:col-span-3 text-xs text-slate-500">Rejected unit: <b>{att.asset_summary}</b>. Verify it is the right device, then record where it goes. Only now is the reservation released.</label>
              <label><span className={lbl}>Asset tag or serial number *</span><input className={inp} value={form.verify || ""} onChange={(e) => setForm({ ...form, verify: e.target.value })} data-testid="ret-verify" /></label>
              <label><span className={lbl}>Condition</span>
                <select className={inp} value={form.condition || "good"} onChange={(e) => setForm({ ...form, condition: e.target.value })}>
                  <option value="good">Good</option><option value="damaged">Damaged</option><option value="missing_parts">Missing parts</option></select></label>
              <label><span className={lbl}>Goes to</span>
                <select className={inp} value={form.destination || "in_stock"} onChange={(e) => setForm({ ...form, destination: e.target.value })}>
                  <option value="in_stock">Back to stock</option><option value="under_repair">Under repair (quarantine)</option><option value="scrapped">Scrapped</option></select></label>
              <label className="sm:col-span-3"><span className={lbl}>Remarks</span><input className={inp} value={form.remarks || ""} onChange={(e) => setForm({ ...form, remarks: e.target.value })} /></label>
              <div className="sm:col-span-3 flex justify-end"><button className={btnPrimary} disabled={!!busy} data-testid="ret-submit"
                onClick={() => call("return", () => post("return", { verify_code: form.verify || "", condition: form.condition || "good", destination: form.destination || "in_stock", remarks: form.remarks || null }), "Return recorded")}>Record return</button></div>
            </div>
          )}

          {panel === "replace" && (
            <div className="mt-4 rounded-md border border-slate-200 p-3 space-y-3" data-testid="form-replace">
              <div className="text-xs text-slate-500">Requested: <b>{req.detailed_specs || "—"}</b>{req.preferred_brand ? ` · brand ${req.preferred_brand}` : ""}. Choose an in-stock unit — it is reserved and a new handover slip (Attempt {c.attempts.length + 1}) is created.</div>
              {!stock ? <div className="text-sm text-slate-500"><Loader2 size={14} className="inline animate-spin" /> Loading stock…</div> : stock.options.length === 0 ? (
                <div className="text-sm text-slate-600">No matching unit is in stock. Use “Correct item not in stock” to start procurement.</div>
              ) : (
                <div className="space-y-2">
                  <input className={inp} value={stockQ} onChange={(e) => setStockQ(e.target.value)} data-testid="stock-search"
                    placeholder="Search by product name, specification, serial no. or tag…" />
                  <div className="text-xs text-slate-500">{stockShown.length} of {stock.options.length} unit(s) in stock — click a unit to see its details.</div>
                  {stockShown.length === 0 && <div className="text-sm text-slate-500 py-3 text-center">No unit matches your search.</div>}
                  <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
                    {stockShown.map((o) => {
                      const isOpen = stockOpen === o.asset_id;
                      return (
                        <li key={o.asset_id} className="text-sm" data-testid={`stock-opt-${o.serial_no || o.asset_id}`}>
                          <div className="px-3 py-2 flex flex-wrap items-center gap-3 cursor-pointer hover:bg-slate-50" onClick={() => setStockOpen(isOpen ? null : o.asset_id)}>
                            <div className="flex-1 min-w-0">
                              <div className="font-medium text-slate-800">{[o.name, o.brand, o.model, o.specification].filter(Boolean).join(" · ") || "Unit"}</div>
                              <div className="font-mono text-xs text-slate-500">{o.serial_no || "—"} · {o.tag_id || "—"}</div>
                              {o.warnings.map((w) => <div key={w} className="text-xs text-amber-700">⚠ {w}</div>)}
                            </div>
                            <button className={btn} disabled={!!busy} data-testid={`pick-${o.serial_no}`}
                              onClick={(e) => { e.stopPropagation(); setForm({ asset_id: o.asset_id }); call("replace", () => post("replace", { asset_id: o.asset_id, confirm_mismatch: false }), "Replacement reserved — slip created"); }}>Select</button>
                          </div>
                          {isOpen && (
                            <dl className="px-3 pb-3 pt-1 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 bg-slate-50/60" data-testid="stock-opt-details">
                              {[["Product", o.name], ["Category", o.category_name], ["Brand", o.brand], ["Model", o.model],
                                ["Specification", o.specification], ["Serial no.", o.serial_no], ["Tag / Asset ID", o.tag_id],
                                ["Received", o.received_at ? new Date(o.received_at).toLocaleDateString() : null]].map(([k, v]) => (
                                <div key={k}><dt className={lbl}>{k}</dt><dd className="text-slate-800 break-words">{v || "—"}</dd></div>
                              ))}
                            </dl>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
              {mismatch && (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" data-testid="mismatch-warning">
                  <b>{mismatch.message}</b>
                  <ul className="list-disc pl-5 mt-1">{mismatch.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
                  <div className="mt-2 flex gap-2">
                    <button className={btn} onClick={() => setMismatch(null)}>Choose another</button>
                    <button className={btnPrimary} disabled={!!busy} data-testid="assign-anyway"
                      onClick={() => call("replace", () => post("replace", { asset_id: form.asset_id, confirm_mismatch: true }), "Replacement reserved — mismatch accepted")}>Assign anyway</button>
                  </div>
                </div>
              )}
            </div>
          )}

          {panel === "stock" && (
            <div className="mt-4 rounded-md border border-slate-200 p-3 space-y-3" data-testid="form-stock">
              <p className="text-xs text-slate-500">A linked requisition is created in the PR Handler's queue using the original approved details — nothing needs to be re-entered, and the normal PR/PO approvals still apply.</p>
              <input className={inp} placeholder="Note (optional)" value={form.note || ""} onChange={(e) => setForm({ note: e.target.value })} />
              <div className="flex justify-end"><button className={btnPrimary} disabled={!!busy} onClick={() => call("stock", () => post("request-stock", { note: form.note || null }), "Waiting for Stock — procurement started")}>Start procurement</button></div>
            </div>
          )}

          {panel === "clarify" && (
            <div className="mt-4 rounded-md border border-slate-200 p-3 space-y-3" data-testid="form-clarify">
              <div className="grid gap-3 sm:grid-cols-[1fr_200px]">
                <label><span className={lbl}>Question *</span><input className={inp} value={form.question || ""} onChange={(e) => setForm({ ...form, question: e.target.value })} data-testid="clar-q" /></label>
                <label><span className={lbl}>Ask</span><select className={inp} value={form.to || "requester"} onChange={(e) => setForm({ ...form, to: e.target.value })}>
                  <option value="requester">The requester</option><option value="approver">The original approver</option></select></label>
              </div>
              <div className="flex justify-end"><button className={btnPrimary} disabled={!!busy || !(form.question || "").trim()} data-testid="clar-submit"
                onClick={() => call("clarify", () => post("clarify", { question: form.question, to: form.to || "requester" }), "Question sent")}>Send question</button></div>
            </div>
          )}

          {panel === "close" && (
            <div className="mt-4 rounded-md border border-slate-200 p-3 space-y-3" data-testid="form-close">
              <div className="grid gap-3 sm:grid-cols-2">
                <label><span className={lbl}>Reason *</span><select className={inp} value={form.reason || ""} onChange={(e) => setForm({ ...form, reason: e.target.value })}>
                  <option value="">Select…</option>{Object.entries(CLOSE_REASONS).filter(([k]) => k !== "resolved" || c.status === "confirmed").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                <label><span className={lbl}>Explanation {form.reason && form.reason !== "resolved" ? "*" : ""}</span><input className={inp} value={form.note || ""} onChange={(e) => setForm({ ...form, note: e.target.value })} /></label>
              </div>
              <div className="flex justify-end"><button className={btnPrimary} disabled={!!busy || !form.reason} data-testid="close-submit"
                onClick={() => call("close", () => post("close", { reason: form.reason, note: form.note || null }), "Case closed")}>Close case</button></div>
            </div>
          )}

          {panel === "reopen" && (
            <div className="mt-4 rounded-md border border-slate-200 p-3 space-y-3">
              <input className={inp} placeholder="Why is it being reopened? *" value={form.note || ""} onChange={(e) => setForm({ note: e.target.value })} />
              <div className="flex justify-end"><button className={btnPrimary} disabled={!!busy || !(form.note || "").trim()} onClick={() => call("reopen", () => post("reopen", { note: form.note }), "Case reopened")}>Reopen</button></div>
            </div>
          )}
        </Section>
      )}

      {can("answer_clarification") && (
        <Section title="IT is asking you" icon={MessageSquare}>
          <p className="text-sm text-slate-700 mb-2">“{[...c.clarifications].reverse().find((x) => !x.answer)?.question}”</p>
          <textarea className={inp} rows={2} value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Your answer" data-testid="clar-answer" />
          <div className="flex justify-end mt-2"><button className={btnPrimary} disabled={!!busy || !answer.trim()} data-testid="clar-answer-submit"
            onClick={async () => { if (await call("answer", () => post("clarification", { answer }), "Answer sent")) setAnswer(""); }}>Send answer</button></div>
        </Section>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="Requested vs delivered" icon={ClipboardList}>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-[11px] uppercase tracking-wide text-slate-400"><th className="pb-1 pr-3"> </th><th className="pb-1 pr-3">Approved requirement</th><th className="pb-1">First delivery</th></tr></thead>
            <tbody>
              {[["Product", req.product_name, dlv.name], ["Specification", req.detailed_specs, dlv.specification], ["Brand", req.preferred_brand, dlv.brand],
                ["Model", "", dlv.model], ["Serial", "", dlv.serial_no], ["Asset tag", "", dlv.tag_id]].map(([k, a, b]) => (
                <tr key={k} className="border-t border-slate-100"><td className="py-1.5 pr-3 text-xs text-slate-500">{k}</td><td className="py-1.5 pr-3">{a || "—"}</td><td className="py-1.5 font-medium">{b || "—"}</td></tr>))}
            </tbody>
          </table>
        </Section>

        <Section title={`Employee report — ${REASONS[c.reason] || c.reason_label}`} icon={AlertTriangle}>
          {(c.rejections || []).map((x, i) => (
            <div key={i} className={`text-sm ${i ? "mt-3 pt-3 border-t border-slate-100" : ""}`}>
              <div className="text-xs text-slate-400">Attempt {x.attempt_no} · {REASONS[x.reason] || x.reason} · {fmt(x.at)}</div>
              <div className="text-slate-800 mt-0.5">{x.note}</div>
              {x.attachment_file_id && <a className="mt-1 inline-flex items-center gap-1 text-xs text-sky-700 hover:underline" target="_blank" rel="noreferrer" href={withAuthParam(`${API}/files/${x.attachment_file_id}/download`)}><ImageIcon size={12} /> View photo</a>}
            </div>
          ))}
          {photo && <a href={photo} target="_blank" rel="noreferrer"><img src={photo} alt="Evidence" className="mt-3 h-28 rounded-md border border-slate-200 object-cover" onError={(e) => { e.currentTarget.style.display = "none"; }} /></a>}
        </Section>
      </div>

      <Section title="Delivery attempts" icon={Truck}>
        <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-200">
            <th className="py-2 pr-3">Attempt</th><th className="pr-3">Slip</th><th className="pr-3">Unit</th><th className="pr-3">Delivered</th><th className="pr-3">Result</th><th>Returned to IT</th></tr></thead>
          <tbody>{c.attempts.map((a) => (
            <tr key={a.attempt_no} className="border-b border-slate-100 align-top">
              <td className="py-2 pr-3 font-medium">{a.attempt_no === 1 ? "Original" : `Attempt ${a.attempt_no}`}</td>
              <td className="pr-3 font-mono text-xs">{a.slip_no}</td><td className="pr-3">{a.asset_summary}</td>
              <td className="pr-3 text-xs">{fmt(a.delivered_at)}<div className="text-slate-400">{a.delivered_by}</div></td>
              <td className="pr-3 capitalize">{(a.status || "").replace("_", " ")}</td>
              <td className="text-xs">{a.return ? <>{fmt(a.return.at)} · {a.return.by}<div className="text-slate-400">{a.return.condition} → {a.return.destination.replace("_", " ")}</div></> : "—"}</td>
            </tr>))}</tbody>
        </table></div>
        {c.procurement_progress && (
          <div className="mt-4 rounded-md bg-orange-50 border border-orange-200 px-3 py-2 text-sm text-orange-900" data-testid="procurement">
            <b>Procurement:</b> requisition {c.procurement_progress.requisition_no} ({(c.procurement_progress.requisition_status || "").replace(/_/g, " ")})
            {c.procurement_progress.pr_no && <> · PR {c.procurement_progress.pr_no}</>}
            {c.procurement_progress.po_number && <> · PO {c.procurement_progress.po_number} ({c.procurement_progress.po_status})</>}
            {it && c.matching_stock > 0 && c.status === "waiting_for_stock" && <div className="mt-1 text-emerald-700">✔ {c.matching_stock} matching unit(s) now in stock — use Arrange Replacement.</div>}
          </div>
        )}
      </Section>

      {c.clarifications.length > 0 && (
        <Section title="Clarifications" icon={MessageSquare}>
          {c.clarifications.map((q, i) => (
            <div key={i} className="text-sm mb-3 last:mb-0">
              <div><span className="text-xs text-slate-400">{fmt(q.asked_at)} · {q.asked_by} → {q.to_name}</span><div className="text-slate-800">Q: {q.question}</div></div>
              {q.answer ? <div className="mt-1 pl-3 border-l-2 border-emerald-300"><span className="text-xs text-slate-400">{fmt(q.answered_at)} · {q.answered_by}</span><div>A: {q.answer}</div></div> : <div className="text-xs text-amber-700 mt-1">Waiting for an answer</div>}
            </div>
          ))}
        </Section>
      )}

      <Section title="Updates & notes" icon={MessageSquare}>
        {c.notes.length === 0 && <div className="text-sm text-slate-400 mb-3">No updates yet.</div>}
        <ul className="space-y-2 mb-3">
          {c.notes.map((n, i) => (
            <li key={i} className={`rounded-md px-3 py-2 text-sm ${n.role === "IT" ? "bg-sky-50" : "bg-slate-50"}`}>
              <div className="text-xs text-slate-500">{n.by} <span className="text-slate-400">({n.role})</span> · {fmt(n.at)}</div><div className="text-slate-800">{n.text}</div>
            </li>))}
        </ul>
        {can("note") && (
          <div className="flex gap-2">
            <input className={inp} value={noteText} onChange={(e) => setNoteText(e.target.value)} placeholder={it ? "e.g. The correct 21 inch monitor is expected Thursday" : "Write a message to IT"} data-testid="note-input"
              onKeyDown={(e) => { if (e.key === "Enter" && noteText.trim()) call("note", () => post("notes", { text: noteText })).then((r) => r && setNoteText("")); }} />
            <button className={btnPrimary} disabled={!!busy || !noteText.trim()} data-testid="note-send"
              onClick={async () => { if (await call("note", () => post("notes", { text: noteText }))) setNoteText(""); }}><Send size={15} /></button>
          </div>
        )}
        <p className="text-[11px] text-slate-400 mt-2">Messages are kept permanently and cannot be edited or deleted.</p>
      </Section>

      <Section title="Audit trail" icon={ShieldCheck}>
        <ol className="space-y-2">
          {[...c.events].reverse().map((e, i) => (
            <li key={i} className="text-sm flex gap-3">
              <span className="text-xs text-slate-400 w-36 shrink-0">{fmt(e.at)}</span>
              <span><b className="font-medium text-slate-700">{(e.action || "").replace(/_/g, " ")}</b> <span className="text-slate-400">by {e.by}</span>
                {e.to_status && e.from_status !== e.to_status && <span className="text-xs text-slate-500"> · {e.from_status ? e.from_status.replace(/_/g, " ") + " → " : ""}{e.to_status.replace(/_/g, " ")}</span>}
                {e.note && <div className="text-slate-600">{e.note}</div>}</span>
            </li>))}
        </ol>
        {c.closure && <div className="mt-3 text-sm text-slate-600"><b>Closed:</b> {c.closure.reason_label}{c.closure.note ? ` — ${c.closure.note}` : ""} ({c.closure.by}, {fmt(c.closure.at)})</div>}
      </Section>
    </div>
  );
}

/* ============================= list + dashboard ============================= */
const FILTERS = [
  ["open", "All open", (c) => !["confirmed", "closed"].includes(c.status)],
  ["new", "New", (c) => c.status === "reported_to_it"],
  ["return", "Awaiting return", (c) => c.requires_return && ["reported_to_it", "under_review"].includes(c.status)],
  ["stock", "Waiting for stock", (c) => c.status === "waiting_for_stock"],
  ["clar", "Waiting for clarification", (c) => c.status === "waiting_clarification"],
  ["redeliv", "Re-delivery", (c) => ["redelivery_in_progress", "delivered_again"].includes(c.status)],
  ["failed", "Failed attempts", (c) => c.failed_attempts >= 2 && !["confirmed", "closed"].includes(c.status)],
  ["overdue", "Overdue", (c) => c.overdue],
  ["done", "Completed", (c) => ["confirmed", "closed"].includes(c.status)],
  ["all", "Everything", () => true],
];

function CaseTable({ rows, it }) {
  const navigate = useNavigate();
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead><tr className="bg-slate-50 border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
          <th className="px-3 py-2.5">Case</th><th className="px-3">Item</th>{it && <th className="px-3">Employee</th>}<th className="px-3">Reason</th>
          <th className="px-3">Status</th><th className="px-3">Attempt</th>{it && <th className="px-3">IT employee</th>}<th className="px-3">Age</th><th className="px-3 text-right">Open</th></tr></thead>
        <tbody>{rows.map((c) => (
          <tr key={c.id} className="border-b border-slate-100 hover:bg-amber-50/40 cursor-pointer" onClick={() => navigate(`/corrections/${c.id}`)} data-testid={`case-row-${c.case_no}`}>
            <td className="px-3 py-2.5"><div className="font-mono text-xs font-semibold">{c.case_no}</div><div className="text-xs text-slate-400">{c.requisition_no}</div></td>
            <td className="px-3">{c.item.product_name}</td>{it && <td className="px-3">{c.employee_name}</td>}
            <td className="px-3 text-slate-600">{REASONS[c.reason] || c.reason_label}</td>
            <td className="px-3"><StatusChip status={c.status} label={c.status_label} />{c.overdue && <AlertTriangle size={13} className="inline ml-1.5 text-red-500" />}</td>
            <td className="px-3">{c.attempts.length}</td>{it && <td className="px-3">{c.responsible_it_name || "—"}</td>}
            <td className="px-3 text-slate-500">{c.age_hours < 48 ? `${Math.round(c.age_hours)}h` : `${Math.round(c.age_hours / 24)}d`}</td>
            <td className="px-3 text-right"><Link to={`/corrections/${c.id}`} className="text-amber-700 hover:underline" onClick={(e) => e.stopPropagation()}>View</Link></td>
          </tr>))}</tbody>
      </table>
      {rows.length === 0 && <div className="py-14 text-center text-sm text-slate-500">No cases here.</div>}
    </div>
  );
}

function Analytics({ data }) {
  const T = ({ title, rows, label }) => (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="px-4 py-2.5 border-b border-slate-100 text-sm font-semibold text-slate-800">{title}</div>
      <table className="w-full text-sm"><thead><tr className="text-left text-xs uppercase tracking-wide text-slate-400"><th className="px-4 py-1.5">{label}</th><th className="px-2 text-right">Cases</th><th className="px-2 text-right">Open</th><th className="px-4 text-right">Attempts</th></tr></thead>
        <tbody>{rows.slice(0, 8).map((r) => (<tr key={r.key} className="border-t border-slate-100"><td className="px-4 py-1.5">{r.label || r.key}</td><td className="px-2 text-right">{r.total}</td><td className="px-2 text-right">{r.open}</td><td className="px-4 text-right">{r.attempts}</td></tr>))}
          {rows.length === 0 && <tr><td colSpan={4} className="px-4 py-4 text-slate-400">No data yet</td></tr>}</tbody></table>
    </section>
  );
  return (
    <div className="space-y-4" data-testid="analytics">
      <p className="text-sm text-slate-500">{data.total} case(s), {data.open} open · average resolution {data.avg_resolution_hours != null ? `${data.avg_resolution_hours} h` : "—"} across {data.resolved_count} finished case(s).</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <T title="By rejection reason" rows={data.by_reason} label="Reason" />
        <T title="By product" rows={data.by_product} label="Product" />
        <T title="By model / specification delivered" rows={data.by_model} label="Model" />
        <T title="By responsible IT employee" rows={data.by_it_employee} label="IT employee" />
        <T title="By status" rows={data.by_status} label="Status" />
        <T title="By delivery attempts" rows={data.by_attempts} label="Attempts" />
      </div>
    </div>
  );
}

function SettingsPanel() {
  const [s, setS] = useState(null);
  useEffect(() => { api.get("/settings/correction").then(({ data }) => setS(data)); }, []);
  if (!s) return null;
  const save = async () => {
    try { const { data } = await api.put("/settings/correction", { reminder_hours: Number(s.reminder_hours), escalation_hours: Number(s.escalation_hours), max_failed_attempts: Number(s.max_failed_attempts), max_reminders: Number(s.max_reminders) }); setS(data); toast.success("Saved"); }
    catch (e) { toast.error(errText(e)); }
  };
  const F = ({ k, label, hint }) => (<label className="block"><span className={lbl}>{label}</span><input type="number" className={inp} value={s[k]} onChange={(e) => setS({ ...s, [k]: e.target.value })} /><span className="text-[11px] text-slate-400">{hint}</span></label>);
  return (
    <div className="max-w-xl rounded-lg border border-slate-200 bg-white p-4 space-y-4" data-testid="settings">
      <div className="grid gap-4 sm:grid-cols-2">
        <F k="reminder_hours" label="Remind IT after (hours idle)" hint="One reminder per interval to the responsible IT employee" />
        <F k="escalation_hours" label="Escalate to IT Head after (hours)" hint="Case unresolved since it was reported" />
        <F k="max_failed_attempts" label="Escalate after failed deliveries" hint="Rejected deliveries before the IT Head is told" />
        <F k="max_reminders" label="Maximum reminders per case" hint="Avoids repeated notifications" />
      </div>
      <div className="flex justify-end"><button className={btnPrimary} onClick={save}>Save limits</button></div>
    </div>
  );
}

function CaseList({ mineOnly }) {
  const { user } = useAuth();
  const [rows, setRows] = useState(null);
  const [filter, setFilter] = useState(mineOnly ? "all" : "open");
  const [tab, setTab] = useState("cases");
  const [analytics, setAnalytics] = useState(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const it = !mineOnly;
  const head = user?.role === "super_admin" || user?.role === "dept_head";

  useEffect(() => {
    api.get("/corrections", { params: mineOnly ? { scope: "mine" } : {} }).then(({ data }) => setRows(data)).catch((e) => setError(errText(e)));
  }, [mineOnly]);
  useEffect(() => { if (tab === "analytics" && !analytics) api.get("/corrections-analytics").then(({ data }) => setAnalytics(data)).catch((e) => toast.error(errText(e))); }, [tab, analytics]);

  const counts = useMemo(() => Object.fromEntries(FILTERS.map(([k, , fn]) => [k, (rows || []).filter(fn).length])), [rows]);
  const shown = useMemo(() => {
    const fn = FILTERS.find(([k]) => k === filter)?.[2] || (() => true);
    const t = q.trim().toLowerCase();
    return (rows || []).filter(fn).filter((c) => !t || `${c.case_no} ${c.item.product_name} ${c.employee_name} ${c.requisition_no} ${c.responsible_it_name}`.toLowerCase().includes(t));
  }, [rows, filter, q]);

  return (
    <div className="space-y-5" data-testid="corrections-list">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">{it ? "Correction Cases" : "My Corrections"}</h2>
          <p className="text-slate-500 text-sm mt-1">{it ? "Items employees rejected at handover — track each one until the correct item is delivered and confirmed." : "Problems you reported with a delivery, and their progress."}</p>
        </div>
        {it && <div className="inline-flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
          {[["cases", "Cases"], ["analytics", "Analytics"], ...(head ? [["settings", "Limits"]] : [])].map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)} className={`px-3.5 h-8 rounded ${tab === k ? "bg-amber-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}>{k === "settings" && <Settings size={13} className="inline mr-1" />}{l}</button>))}
        </div>}
      </div>

      {tab === "analytics" ? (analytics ? <Analytics data={analytics} /> : <div className="text-sm text-slate-500"><Loader2 className="inline animate-spin" size={14} /> Loading…</div>)
        : tab === "settings" ? <SettingsPanel /> : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {FILTERS.filter(([k]) => it || ["open", "done", "all"].includes(k)).map(([k, label]) => (
              <button key={k} onClick={() => setFilter(k)} data-testid={`filter-${k}`}
                className={`rounded-full border px-3 py-1 text-xs ${filter === k ? "border-amber-500 bg-amber-50 text-amber-800 font-semibold" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}>
                {label} <span className="text-slate-400">{counts[k]}</span></button>))}
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search case, item, employee…" className="ml-auto h-8 w-60 rounded-md border border-slate-300 px-3 text-sm" />
          </div>
          {error ? <div className="rounded-lg border bg-white p-10 text-center text-sm text-red-600">{error}</div>
            : rows === null ? <div className="text-sm text-slate-500"><Loader2 className="inline animate-spin" size={14} /> Loading…</div> : <CaseTable rows={shown} it={it} />}
        </>
      )}
    </div>
  );
}

export default function Corrections() {
  const { id } = useParams();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { allowed, menu } = useAuth();
  const mine = pathname.startsWith("/corrections/mine");
  if (menu.length > 0 && !id) {
    const need = mine ? "my-corrections" : "corrections";
    if (!(allowed || []).includes(need)) return <Navigate to="/" replace />;
  }
  if (id && id !== "mine") return <CaseDetail id={id} back={() => navigate(-1)} />;
  return <CaseList mineOnly={mine} />;
}