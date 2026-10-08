import { useCallback, useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";

/**
 * Centered result popup for the main system actions (submit requisition, file PR, submit PO,
 * approve, reject).
 *
 * 1. Mount <ResultPopupHost /> ONCE (App.js does this).
 * 2. Call showResult(...) from anywhere — no hooks or props needed:
 *
 *      showResult({ title: "Done!", message: "Requisition REQ-2026-0001 submitted." });
 *      showResult({ kind: "reject", title: "Rejected", message: "The requisition was rejected." });
 *      showResult({ ..., onClose: () => navigate("/requisitions/pending") });   // runs AFTER it closes
 *
 * It closes when the user clicks OK / the backdrop / presses Esc, or by itself after `duration`.
 */
let listener = null;

export function showResult(opts = {}) {
  if (listener) listener(opts);
  else if (opts.onClose) opts.onClose();   // host not mounted: never block the caller's follow-up
}

const TONES = {
  success: { ring: "bg-emerald-50", icon: "bg-emerald-100 text-emerald-600", title: "text-emerald-700", btn: "bg-emerald-600 hover:bg-emerald-700" },
  reject:  { ring: "bg-red-50",     icon: "bg-red-100 text-red-600",         title: "text-red-700",     btn: "bg-red-600 hover:bg-red-700" },
};

export default function ResultPopupHost() {
  const [popup, setPopup] = useState(null);
  const [visible, setVisible] = useState(false);
  const popupRef = useRef(null);
  popupRef.current = popup;

  const close = useCallback(() => {
    const p = popupRef.current;
    if (!p) return;
    popupRef.current = null;
    setPopup(null);
    setVisible(false);
    if (p.onClose) p.onClose();
  }, []);

  useEffect(() => {
    listener = (opts) => setPopup({ kind: "success", title: "Done!", duration: 2600, ...opts });
    return () => { listener = null; };
  }, []);

  useEffect(() => {
    if (!popup) return undefined;
    setVisible(false);
    const raf = requestAnimationFrame(() => setVisible(true));      // pop-in animation
    const t = setTimeout(close, popup.duration);
    const onKey = (e) => { if (e.key === "Escape" || e.key === "Enter") close(); };
    window.addEventListener("keydown", onKey);
    return () => { cancelAnimationFrame(raf); clearTimeout(t); window.removeEventListener("keydown", onKey); };
  }, [popup, close]);

  if (!popup) return null;
  const tone = TONES[popup.kind] || TONES.success;
  const isReject = popup.kind === "reject";

  return (
    <div
      className={`fixed inset-0 z-[200] flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4 transition-opacity duration-200 ${visible ? "opacity-100" : "opacity-0"}`}
      onClick={close}
      data-testid="result-popup"
    >
      <div
        role="alertdialog"
        aria-live="assertive"
        onClick={(e) => e.stopPropagation()}
        className={`w-full max-w-md rounded-2xl bg-white shadow-2xl px-8 py-10 text-center transition-all duration-300 ${visible ? "scale-100 opacity-100" : "scale-90 opacity-0"}`}
      >
        <div className={`mx-auto w-28 h-28 rounded-full flex items-center justify-center ${tone.ring}`}>
          <div className={`w-20 h-20 rounded-full flex items-center justify-center ${tone.icon}`}>
            {isReject ? <X size={46} strokeWidth={3} /> : <Check size={46} strokeWidth={3} />}
          </div>
        </div>
        <h2 className={`mt-6 text-3xl font-bold tracking-tight ${tone.title}`} data-testid="result-popup-title">{popup.title}</h2>
        {popup.message && <p className="mt-2 text-sm text-slate-500 leading-relaxed">{popup.message}</p>}
        <button
          type="button"
          autoFocus
          onClick={close}
          data-testid="result-popup-ok"
          className={`mt-7 px-10 py-2.5 rounded-lg text-white text-sm font-semibold transition-colors ${tone.btn}`}
        >
          OK
        </button>
      </div>
    </div>
  );
}
