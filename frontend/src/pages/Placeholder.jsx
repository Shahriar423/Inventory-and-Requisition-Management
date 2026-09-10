import { Construction } from "lucide-react";

export default function Placeholder({ title, note }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center" data-testid="placeholder-page">
      <div className="w-14 h-14 rounded-2xl bg-amber-100 text-amber-600 flex items-center justify-center mb-4">
        <Construction size={26} />
      </div>
      <h2 className="font-head text-2xl font-bold text-slate-900">{title}</h2>
      <p className="text-slate-500 text-sm mt-2 max-w-md">{note || "This module is part of the roadmap and will be enabled in an upcoming step."}</p>
    </div>
  );
}
