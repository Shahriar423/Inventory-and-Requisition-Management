import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Search, X } from "lucide-react";

const inputCls =
  "h-9 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-800 placeholder:text-slate-400 " +
  "focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";

/** Searchable single-select (used for employees, who can number in the hundreds). */
export function SearchPicker({ options, value, onChange, placeholder = "Select…", testId }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef(null);
  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? options.filter((o) => `${o.label} ${o.sub || ""}`.toLowerCase().includes(t)) : options;
  }, [q, options]);

  return (
    <div ref={ref} className="relative" data-testid={testId}>
      <div className={`${inputCls} flex items-center gap-2 cursor-text`} onClick={() => setOpen(true)}>
        <Search size={14} className="text-slate-400 shrink-0" />
        {open ? (
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type a name, ID or department…" className="flex-1 min-w-0 outline-none bg-transparent" />
        ) : (
          <span className={`flex-1 truncate ${selected ? "" : "text-slate-400"}`}>{selected ? selected.label : placeholder}</span>
        )}
        {value && !open ? (
          <button type="button" aria-label="Clear" onClick={(e) => { e.stopPropagation(); onChange(""); }} className="text-slate-400 hover:text-slate-700"><X size={14} /></button>
        ) : <ChevronDown size={14} className="text-slate-400 shrink-0" />}
      </div>
      {open && (
        <div className="absolute z-30 mt-1 w-full max-h-64 overflow-auto rounded-md border border-slate-200 bg-white shadow-lg">
          {shown.length === 0 && <div className="px-3 py-2 text-sm text-slate-400">No match</div>}
          {shown.map((o) => (
            <button type="button" key={o.value} onClick={() => { onChange(o.value); setOpen(false); setQ(""); }}
              className={`w-full text-left px-3 py-2 text-sm hover:bg-blue-50 border-b border-slate-50 ${o.value === value ? "bg-blue-50" : ""}`}>
              <div className="text-slate-800">{o.label}</div>
              {o.sub && <div className="text-xs text-slate-500">{o.sub}</div>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Renders the filter inputs for a report type. Every field is optional. */
export default function FilterFields({ fields, values, onChange, lookups = {}, disabledKeys = [], onEnter }) {
  const employees = useMemo(() => (lookups.employees || []).map((e) => ({
    value: e.id, label: e.name, sub: [e.code, e.department].filter(Boolean).join(" · "),
  })), [lookups.employees]);

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {fields.map((f) => {
        const v = values[f.key] || "";
        const dis = disabledKeys.includes(f.key);
        return (
          <label key={f.key} className="block min-w-0">
            <span className="block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">{f.label}</span>
            {f.type === "text" && (
              <input value={v} disabled={dis} onChange={(e) => onChange(f.key, e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onEnter && onEnter()} className={inputCls} data-testid={`rf-${f.key}`} />
            )}
            {f.type === "date" && (
              <input type="date" value={v} disabled={dis} onChange={(e) => onChange(f.key, e.target.value)} className={inputCls} data-testid={`rf-${f.key}`} />
            )}
            {f.type === "select" && (
              <select value={v} disabled={dis} onChange={(e) => onChange(f.key, e.target.value)} className={inputCls} data-testid={`rf-${f.key}`}>
                <option value="">{f.empty_label || "All"}</option>
                {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            )}
            {f.type === "department" && (
              <select value={v} disabled={dis} onChange={(e) => onChange(f.key, e.target.value)} className={inputCls} data-testid={`rf-${f.key}`}>
                <option value="">All departments</option>
                {(lookups.departments || []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            )}
            {f.type === "category" && (
              <select value={v} disabled={dis} onChange={(e) => onChange(f.key, e.target.value)} className={inputCls} data-testid={`rf-${f.key}`}>
                <option value="">All categories</option>
                {(lookups.categories || []).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            )}
            {f.type === "employee" && (
              <SearchPicker options={employees} value={v} onChange={(x) => onChange(f.key, x)} placeholder="Any employee" testId={`rf-${f.key}`} />
            )}
          </label>
        );
      })}
    </div>
  );
}

export { inputCls };