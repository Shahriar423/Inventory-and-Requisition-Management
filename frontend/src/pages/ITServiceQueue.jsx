import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Inbox, Hand, Undo2, CheckCircle2, Wrench, ThumbsUp, ThumbsDown, PackageCheck, RefreshCw, Paperclip, X, User } from "lucide-react";
import api, { API, withAuthParam, formatApiErrorDetail } from "@/lib/apiClient";
import { StatusBadge } from "@/lib/status";

/**
 * IT Service Queue - shared ticket queues for the IT sub-teams.
 *   Application executives   -> Application tickets only
 *   Network_Infra executives -> Network & Infra tickets only
 *   IT Head / Super Admin    -> both queues
 * The server does the filtering (GET /api/it-service/queue); this page only renders what it is given.
 * Pick up / release / complete are atomic on the server: if a colleague got there first you get a
 * "Already picked up by ..." message and the list refreshes.
 * Hardware that cannot be fixed on site uses the External Repair workflow (no swap slip):
 *   Request External Repair -> IT Head approves/rejects -> product at service center -> Mark Repaired & Delivered.
 */
const VIEWS = [["open", "Open queue"], ["active", "In progress"], ["repair", "Repairs"], ["mine", "Mine"], ["done", "Completed"]];
const PRIORITY_CLS = { low: "bg-slate-100 text-slate-600", medium: "bg-sky-100 text-sky-700", high: "bg-amber-100 text-amber-700", critical: "bg-red-100 text-red-700" };
const TEAM_CLS = { Application: "bg-violet-100 text-violet-700", Network_Infra: "bg-teal-100 text-teal-700" };
const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

export default function ITServiceQueue() {
  const [view, setView] = useState("open");
  const [team, setTeam] = useState("");            // "" = every queue I can see
  const [data, setData] = useState({ allowed_teams: [], counts: {}, tickets: [] });
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState("");
  const [selId, setSelId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [device, setDevice] = useState("");          // device details for a repair request
  const [center, setCenter] = useState("");          // service center / vendor on approval
  const [panel, setPanel] = useState("");            // "repair" while the request-repair form is open

  const load = useCallback(async (opts = {}) => {
    if (!opts.silent) setLoading(true);
    try {
      const { data: d } = await api.get("/it-service/queue", { params: { view, ...(team ? { team } : {}) } });
      setData(d); setDenied("");
    } catch (e) {
      if (e.response?.status === 403) setDenied(formatApiErrorDetail(e.response?.data?.detail));
      else if (!opts.silent) toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally { setLoading(false); }
  }, [view, team]);

  useEffect(() => { load(); }, [load]);
  // Keep the shared queue fresh while the page is open (someone else may pick tickets up).
  useEffect(() => {
    const t = setInterval(() => load({ silent: true }), 30000);
    return () => clearInterval(t);
  }, [load]);

  const openDetail = async (id) => {
    setSelId(id); setNote(""); setDevice(""); setCenter(""); setPanel("");
    try { const { data: d } = await api.get(`/it-service/tickets/${id}`); setDetail(d); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); setSelId(null); }
  };
  const closeDetail = () => { setSelId(null); setDetail(null); setPanel(""); };

  // One helper for every ticket action. Each is atomic on the server: if a colleague (or the IT Head)
  // already moved the ticket, you get the reason as an error and both the list and the panel refresh.
  const run = async (path, body, okMsg, reopen) => {
    if (!detail) return;
    setBusy(true);
    try {
      await api.post(`/it-service/tickets/${detail.id}/${path}`, body);
      toast.success(okMsg);
      if (reopen) await openDetail(detail.id); else closeDetail();
      await load({ silent: true });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
      await load({ silent: true });
      if (detail?.id) openDetail(detail.id).catch(() => {});
    } finally { setBusy(false); }
  };
  const claim = () => run("claim", undefined, "Ticket picked up - it is yours now", true);
  const release = () => run("release", { note: note.trim() || null }, "Ticket returned to the queue", false);
  const complete = () => run("complete", { note: note.trim() || null }, "Ticket completed", false);
  const requestRepair = () => {
    if (!note.trim()) return toast.error("Explain why this cannot be repaired on site");
    return run("request-repair", { reason: note.trim(), device_details: device.trim() || null }, "Sent to the IT Head for approval", false);
  };
  const decide = (action) => {
    if (action === "reject" && !note.trim()) return toast.error("Give the executive feedback when rejecting");
    return run("repair-decision", { action, note: note.trim() || null, service_center: center.trim() || null },
      action === "approve" ? "Approved - item is now at the service center" : "Rejected - ticket is back with the executive", false);
  };
  const markRepaired = () => run("mark-repaired", { note: note.trim() || null }, "Repaired & delivered - ticket closed", false);

  if (denied) {
    return (
      <div className="max-w-xl mx-auto py-16 text-center text-slate-500" data-testid="itq-denied">
        <Inbox size={28} className="mx-auto mb-3 opacity-50" />
        {denied}
      </div>
    );
  }

  const multi = data.allowed_teams.length > 1;
  const teamLabel = (k) => data.allowed_teams.find((t) => t.key === k)?.label || k;

  return (
    <div className="space-y-4" data-testid="it-service-queue-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-head text-2xl font-bold text-slate-900">IT Service Queue</h2>
          <p className="text-slate-500 text-sm mt-0.5">
            {multi ? "Both sub-team queues." : `${data.allowed_teams[0]?.label || "Your"} queue.`} Anyone on the team can pick up a ticket; once picked up it is theirs.
          </p>
        </div>
        <button onClick={() => load()} className="px-3 py-2 rounded-lg border border-slate-300 text-slate-600 text-sm font-semibold flex items-center gap-2 hover:bg-slate-50" data-testid="itq-refresh">
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {multi && (
        <div className="flex flex-wrap gap-2" data-testid="itq-team-filter">
          {[{ key: "", label: "All queues" }, ...data.allowed_teams].map((t) => (
            <button key={t.key || "all"} onClick={() => setTeam(t.key)} data-testid={`itq-team-${t.key || "all"}`}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold border ${team === t.key ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-300 hover:bg-slate-50"}`}>
              {t.label}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-1 border-b border-slate-200">
        {VIEWS.map(([k, l]) => (
          <button key={k} onClick={() => { setView(k); closeDetail(); }} data-testid={`itq-view-${k}`}
            className={`px-4 py-2 text-sm font-semibold -mb-px border-b-2 ${view === k ? "border-amber-600 text-amber-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {l}{data.counts?.[k] !== undefined && k !== "done" ? <span className={`ml-1.5 text-xs font-mono px-1.5 py-0.5 rounded ${k === "repair" && data.counts.repair_approvals > 0 ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>{data.counts[k]}</span> : null}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
        {loading ? (
          <div className="py-12 text-center text-slate-400">Loading tickets…</div>
        ) : data.tickets.length === 0 ? (
          <div className="py-12 text-center text-slate-400" data-testid="itq-empty">
            <Inbox size={22} className="mx-auto mb-2 opacity-50" />
            Nothing here.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50/50">
                <th className="px-4 py-3 font-semibold">Ticket</th>
                <th className="px-4 py-3 font-semibold">Request</th>
                <th className="px-4 py-3 font-semibold">Priority</th>
                <th className="px-4 py-3 font-semibold">Requested by</th>
                {multi && <th className="px-4 py-3 font-semibold">Queue</th>}
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">Picked up by</th>
                <th className="px-4 py-3 font-semibold">Raised</th>
              </tr>
            </thead>
            <tbody>
              {data.tickets.map((t) => (
                <tr key={t.id} onClick={() => openDetail(t.id)} data-testid={`itq-row-${t.requisition_no}`}
                  className={`border-b border-slate-50 cursor-pointer hover:bg-amber-50/40 ${selId === t.id ? "bg-amber-50/60" : ""}`}>
                  <td className="px-4 py-3 font-mono font-semibold text-slate-800">{t.requisition_no}</td>
                  <td className="px-4 py-3 text-slate-700">{t.items.map((it) => it.product_name).join(", ")}</td>
                  <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold capitalize ${PRIORITY_CLS[t.priority] || ""}`}>{t.priority}</span></td>
                  <td className="px-4 py-3 text-slate-600">{t.requisition_for || t.requisitioner_name}<div className="text-xs text-slate-400">{t.requisitioner_department_name || ""}</div></td>
                  {multi && <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${TEAM_CLS[t.it_team] || ""}`}>{teamLabel(t.it_team)}</span></td>}
                  <td className="px-4 py-3"><StatusBadge status={t.status} /></td>
                  <td className="px-4 py-3 text-slate-600">{t.service_assigned_to_name || "—"}</td>
                  <td className="px-4 py-3 text-slate-500 whitespace-nowrap">{fmt(t.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detail && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40" onClick={closeDetail} data-testid="itq-detail-overlay">
          <div className="w-full max-w-lg bg-white h-full overflow-y-auto shadow-2xl p-6 space-y-5" onClick={(e) => e.stopPropagation()} data-testid="itq-detail">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-mono text-lg font-bold text-slate-900">{detail.requisition_no}</div>
                <div className="flex flex-wrap items-center gap-2 mt-1">
                  <StatusBadge status={detail.status} />
                  <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${TEAM_CLS[detail.it_team] || ""}`}>{detail.it_team_label}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold capitalize ${PRIORITY_CLS[detail.priority] || ""}`}>{detail.priority}</span>
                </div>
              </div>
              <button onClick={closeDetail} className="text-slate-400 hover:text-slate-700" aria-label="Close"><X size={20} /></button>
            </div>

            <div className="text-sm text-slate-600 space-y-1">
              <div className="flex items-center gap-2"><User size={14} className="text-slate-400" /> For <strong className="text-slate-800">{detail.requisition_for || detail.requisitioner_name}</strong>
                {detail.requisitioner_department_name ? ` · ${detail.requisitioner_department_name}` : ""}</div>
              <div>Raised by {detail.requisitioner_name} on {fmt(detail.created_at)}</div>
              <div>Picked up by: <strong className="text-slate-800">{detail.service_assigned_to_name || "nobody yet"}</strong></div>
            </div>

            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Request</div>
              <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
                {detail.items.map((it, i) => (
                  <div key={i} className="px-3 py-2 text-sm">
                    <div className="font-medium text-slate-800">{it.product_name}</div>
                    {it.remarks && <div className="text-slate-500 mt-0.5">{it.remarks}</div>}
                  </div>
                ))}
              </div>
              {detail.requester_note && <p className="text-sm text-slate-500 mt-2">Note: {detail.requester_note}</p>}
              {(detail.attachments || []).map((a) => (
                <a key={a.id} href={withAuthParam(`${API}/files/${a.id}/download`)} target="_blank" rel="noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm text-sky-700 hover:underline mt-2 mr-3"><Paperclip size={13} /> {a.name}</a>
              ))}
            </div>

            {detail.repair_request && (
              <div className="rounded-lg border border-purple-200 bg-purple-50 px-3 py-3 text-sm space-y-1" data-testid="itq-repair-info">
                <div className="font-semibold text-purple-800">External repair · {detail.repair_request.status}</div>
                <div className="text-slate-700"><span className="text-slate-500">Reason:</span> {detail.repair_request.reason}</div>
                {detail.repair_request.device_details && <div className="text-slate-700"><span className="text-slate-500">Device:</span> {detail.repair_request.device_details}</div>}
                <div className="text-xs text-slate-500">Requested by {detail.repair_request.requested_by} · {fmt(detail.repair_request.requested_at)}</div>
                {detail.repair_request.decided_by && (
                  <div className="text-slate-700">
                    <span className="text-slate-500">{detail.repair_request.status === "rejected" ? "Rejected" : "Approved"} by {detail.repair_request.decided_by}:</span>{" "}
                    {detail.repair_request.decision_note || "—"}
                    {detail.repair_request.service_center ? ` (Service center: ${detail.repair_request.service_center})` : ""}
                  </div>
                )}
              </div>
            )}

            {(detail.actions.release || detail.actions.complete || detail.actions.decide_repair || detail.actions.mark_repaired || panel === "repair") && (
              <div className="space-y-3">
                {detail.actions.decide_repair && (
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Service center / vendor (optional)</label>
                    <input value={center} onChange={(e) => setCenter(e.target.value)} data-testid="itq-center"
                      className="w-full h-10 px-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm" />
                  </div>
                )}
                {panel === "repair" && (
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Device details (optional)</label>
                    <input value={device} onChange={(e) => setDevice(e.target.value)} placeholder="Tag / serial, what you checked on site" data-testid="itq-device"
                      className="w-full h-10 px-3 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm" />
                  </div>
                )}
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
                    {panel === "repair" ? "Why can't it be fixed on site? *" : detail.actions.decide_repair ? "Feedback (required to reject)" : "Note (optional)"}
                  </label>
                  <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} data-testid="itq-note"
                    className="w-full px-3 py-2 rounded-md border border-slate-300 focus:border-amber-500 outline-none text-sm" />
                </div>
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              {detail.actions.claim && (
                <button disabled={busy} onClick={claim} data-testid="itq-claim"
                  className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-semibold flex items-center gap-2 disabled:opacity-50"><Hand size={15} /> Pick up</button>
              )}
              {detail.actions.complete && (
                <button disabled={busy} onClick={complete} data-testid="itq-complete"
                  className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold flex items-center gap-2 disabled:opacity-50"><CheckCircle2 size={15} /> Mark complete</button>
              )}
              {detail.actions.request_repair && panel !== "repair" && (
                <button disabled={busy} onClick={() => setPanel("repair")} data-testid="itq-request-repair"
                  className="px-4 py-2 rounded-lg border border-purple-500 text-purple-700 hover:bg-purple-50 text-sm font-semibold flex items-center gap-2"><Wrench size={15} /> Request External Repair</button>
              )}
              {panel === "repair" && (
                <>
                  <button disabled={busy} onClick={requestRepair} data-testid="itq-send-repair"
                    className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-700 text-white text-sm font-semibold flex items-center gap-2 disabled:opacity-50"><Wrench size={15} /> Send to IT Head</button>
                  <button disabled={busy} onClick={() => setPanel("")} className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 text-sm font-semibold">Cancel</button>
                </>
              )}
              {detail.actions.decide_repair && (
                <>
                  <button disabled={busy} onClick={() => decide("approve")} data-testid="itq-approve-repair"
                    className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold flex items-center gap-2 disabled:opacity-50"><ThumbsUp size={15} /> Approve repair</button>
                  <button disabled={busy} onClick={() => decide("reject")} data-testid="itq-reject-repair"
                    className="px-4 py-2 rounded-lg border border-red-400 text-red-600 hover:bg-red-50 text-sm font-semibold flex items-center gap-2 disabled:opacity-50"><ThumbsDown size={15} /> Reject</button>
                </>
              )}
              {detail.actions.mark_repaired && (
                <button disabled={busy} onClick={markRepaired} data-testid="itq-mark-repaired"
                  className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold flex items-center gap-2 disabled:opacity-50"><PackageCheck size={15} /> Mark Repaired &amp; Delivered</button>
              )}
              {detail.actions.release && panel !== "repair" && (
                <button disabled={busy} onClick={release} data-testid="itq-release"
                  className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50 text-sm font-semibold flex items-center gap-2 disabled:opacity-50"><Undo2 size={15} /> Return to queue</button>
              )}
            </div>
            {detail.status === "pending_repair_approval" && !detail.actions.decide_repair && (
              <p className="text-xs text-slate-400">Waiting for the IT Head to approve or reject the external repair.</p>
            )}

            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">History</div>
              <ol className="space-y-1.5 text-sm">
                {[...(detail.history || [])].reverse().map((h, i) => (
                  <li key={i} className="text-slate-600"><span className="text-slate-400 text-xs mr-2">{fmt(h.at)}</span><strong className="text-slate-700">{h.by}</strong>{h.note ? ` — ${h.note}` : ` — ${h.action}`}</li>
                ))}
              </ol>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}