import { Loader2 } from "lucide-react";

/** Suspense fallback shown inside the page area (sidebar and header stay visible) while a page chunk downloads. */
export default function PageLoader() {
  return (
    <div className="flex items-center justify-center py-24 text-slate-400" role="status" aria-live="polite" data-testid="page-loader">
      <Loader2 size={22} className="animate-spin mr-2" />
      <span className="text-sm">Loading…</span>
    </div>
  );
}
