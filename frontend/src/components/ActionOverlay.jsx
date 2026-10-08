import { useEffect, useState } from "react";
import { Check, X } from "lucide-react";

/**
 * Full-screen dimmed overlay with a big centered checkmark (success) or X (reject),
 * shown briefly after an action completes (requisition submitted, approved, rejected).
 * Auto-calls onDone after `duration` ms so the caller can navigate/reset state.
 */
export default function ActionOverlay({ show, kind = "success", title, subtitle, duration = 1100, onDone }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!show) return;
    // Mount at opacity-0/scale-90, flip to visible on the next frame for a pop-in effect.
    setVisible(false);
    const raf = requestAnimationFrame(() => setVisible(true));
    const t = setTimeout(() => onDone && onDone(), duration);
    return () => { cancelAnimationFrame(raf); clearTimeout(t); };
  }, [show, duration, onDone]);

  if (!show) return null;
  const isReject = kind === "reject";
  const tone = isReject ? "text-red-600 bg-red-100" : "text-emerald-600 bg-emerald-100";

  return (
    <div
      className={`fixed inset-0 z-[100] flex items-center justify-center bg-white/70 backdrop-blur-sm transition-opacity duration-200 ${visible ? "opacity-100" : "opacity-0"}`}
      data-testid="action-overlay"
    >
      <div className={`flex flex-col items-center gap-3 transition-all duration-300 ${visible ? "scale-100 opacity-100" : "scale-75 opacity-0"}`}>
        <div className={`w-20 h-20 rounded-full flex items-center justify-center ${tone}`}>
          {isReject ? <X size={44} strokeWidth={3} /> : <Check size={44} strokeWidth={3} />}
        </div>
        <div className={`font-head font-bold text-lg tracking-wide ${isReject ? "text-red-600" : "text-emerald-600"}`}>{title}</div>
        {subtitle && <div className="text-sm text-slate-500">{subtitle}</div>}
      </div>
    </div>
  );
}
