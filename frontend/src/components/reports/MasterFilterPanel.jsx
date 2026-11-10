import { List, Loader2, RotateCcw, Save, Search } from "lucide-react";
import { SearchPicker, inputCls } from "./FilterFields";

const btn = "h-9 px-3 rounded-md border border-slate-300 bg-white text-sm text-slate-700 hover:bg-slate-50 inline-flex items-center gap-2 disabled:opacity-50";
const btnPrimary = "h-9 px-4 rounded-md bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 inline-flex items-center gap-2 disabled:opacity-50";
const lbl = "block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1";

// Order and wording of the Report View / Type dropdown.
export const VIEW_OPTIONS = [
  ["all_inventory", "All Inventory"], ["stock", "Stock Status"], ["employee_assets", "Employee Assets"],
  ["department", "Department Wise"], ["movement", "Stock Movements"], ["return_damage_lost", "Return / Damage / Lost"],
  ["purchase", "Purchases"],
];
// What the From / To dates mean for each view.
export const DATE_HINT = {
  all_inventory: "Received date", stock: "Received date", employee_assets: "Assignment date", department: "Assignment date",
  movement: "Transaction date", return_damage_lost: "Return / damage date", purchase: "Purchase date",
};
// Every filter the master panel can send. Only the ones a view understands are enabled for it.
export const MASTER_KEYS = ["department_id", "employee_user_id", "status", "product", "brand", "category_id", "model_serial", "date_from", "date_to"];

const STATUS_OPTIONS = [["available", "Available"], ["assigned", "Assigned"], ["damaged", "Damaged"], ["lost", "Lost"], ["under_repair", "Under Repair"]];

/** The single, unified search panel. All inputs are optional; empty ones are ignored and the rest are ANDed. */
export default function MasterFilterPanel({ meta, view, onView, values, onValue, applicable, onSearch, onClear, onShowAll, onSave, loading, notice }) {
  // with a department chosen, only that department's employees are offered
  const employees = meta.employees.filter((e) => !values.department_id || e.department_id === values.department_id).map((e) => ({ value: e.id, label: e.name, sub: [e.code, e.department].filter(Boolean).join(" · ") }));
  const views = VIEW_OPTIONS.filter(([k]) => meta.types.some((t) => t.key === k));
  const changeDept = (id) => {
    onValue("department_id", id);
    const emp = meta.employees.find((e) => e.id === values.employee_user_id);
    if (id && emp && emp.department_id !== id) onValue("employee_user_id", "");   // drop an employee from another department
  };
  const off = (k) => !applicable.has(k);
  const hint = (k) => (off(k) ? "Not used by this report view" : undefined);
  const enter = (e) => e.key === "Enter" && onSearch();
  const field = (k, label, node) => (
    <label className={`block min-w-0 ${off(k) ? "opacity-50" : ""}`} title={hint(k)}>
      <span className={lbl}>{label}</span>{node}
    </label>
  );
  const text = (k, placeholder) => (
    <input value={values[k] || ""} disabled={off(k)} placeholder={placeholder} onChange={(e) => onValue(k, e.target.value)}
      onKeyDown={enter} className={inputCls} data-testid={`mf-${k}`} />
  );

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-4" data-testid="filter-toolbar">
      {/* Row 1: scope & type */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block min-w-0"><span className={lbl}>Report View / Type</span>
          <select value={view} onChange={(e) => onView(e.target.value)} className={inputCls} data-testid="mf-view">
            {views.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select></label>
        {field("department_id", "Department",
          <select value={values.department_id || ""} disabled={off("department_id")} onChange={(e) => changeDept(e.target.value)} className={inputCls} data-testid="mf-department_id">
            <option value="">All departments</option>
            {meta.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>)}
        <div className={`min-w-0 ${off("employee_user_id") ? "opacity-50 pointer-events-none" : ""}`} title={hint("employee_user_id")}>
          <span className={lbl}>Employee</span>
          <SearchPicker options={employees} value={values.employee_user_id || ""} onChange={(v) => onValue("employee_user_id", v)}
            placeholder="Any employee (name / ID)" testId="mf-employee_user_id" />
        </div>
        {field("status", "Unit Status",
          <select value={values.status || ""} disabled={off("status")} onChange={(e) => onValue("status", e.target.value)} className={inputCls} data-testid="mf-status">
            <option value="">All</option>
            {STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>)}
      </div>

      {/* Row 2: product & spec details */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {field("product", "Product Name", text("product"))}
        {field("brand", "Brand", text("brand"))}
        {field("category_id", "Category",
          <select value={values.category_id || ""} disabled={off("category_id")} onChange={(e) => onValue("category_id", e.target.value)} className={inputCls} data-testid="mf-category_id">
            <option value="">All categories</option>
            {meta.categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>)}
        {field("model_serial", "Model / Serial Number", text("model_serial"))}
      </div>

      {/* Row 3: date range & actions */}
      <div className="flex flex-wrap items-end gap-3">
        <div className={`flex items-end gap-2 ${off("date_from") ? "opacity-50" : ""}`} title={hint("date_from")}>
          <label className="block"><span className={lbl}>From Date <span className="normal-case font-normal text-slate-400">({DATE_HINT[view]})</span></span>
            <input type="date" value={values.date_from || ""} disabled={off("date_from")} onChange={(e) => onValue("date_from", e.target.value)} className={`${inputCls} w-40`} data-testid="mf-date_from" /></label>
          <span className="pb-2 text-sm text-slate-400">to</span>
          <label className="block"><span className={lbl}>To Date</span>
            <input type="date" value={values.date_to || ""} disabled={off("date_to")} onChange={(e) => onValue("date_to", e.target.value)} className={`${inputCls} w-40`} data-testid="mf-date_to" /></label>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
          <button className={btnPrimary} onClick={onSearch} disabled={loading} data-testid="btn-search">
            {loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />} Search</button>
          <button className={btn} onClick={onClear} data-testid="btn-clear"><RotateCcw size={15} /> Clear Filters</button>
          <button className={btn} onClick={onShowAll} disabled={loading} data-testid="btn-show-all" title="Show every record you are authorised to see"><List size={15} /> Show All</button>
          <button className="h-9 px-3 rounded-md bg-slate-800 text-white text-sm font-semibold hover:bg-slate-900 inline-flex items-center gap-2" onClick={onSave} data-testid="btn-save-assign">
            <Save size={15} /> Save &amp; Assign Report</button>
        </div>
      </div>
      {notice && <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" data-testid="search-notice">{notice}</div>}
    </div>
  );
}