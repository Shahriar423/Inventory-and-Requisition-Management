/** Read / Print / Export choice for an assigned report. "Read" is always on. */
export const PERM_LABELS = { read: "Read", print: "Print", export: "Export" };

export default function PermBoxes({ value = ["read"], onChange, disabled = false }) {
  const toggle = (k) => onChange(value.includes(k) ? value.filter((x) => x !== k) : [...value, k]);
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-700" data-testid="perm-boxes">
      {[["read", "Read (view)"], ["print", "Print"], ["export", "Export PDF / Excel"]].map(([k, label]) => (
        <label key={k} className="inline-flex items-center gap-2">
          <input type="checkbox" checked={k === "read" || value.includes(k)} disabled={k === "read" || disabled}
            onChange={() => toggle(k)} data-testid={`perm-${k}`} className="h-4 w-4 rounded border-slate-300" />
          {label}
        </label>
      ))}
    </div>
  );
}
