import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

function BrandMark() {
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M17 1 L31.6 9v16L17 33 2.4 25V9Z" fill="#0B0F19" />
      <path d="M17 1 L31.6 9v16L17 33 2.4 25V9Z" stroke="#1F2937" strokeWidth="0.5" />
      <circle cx="17" cy="12" r="3.4" fill="#E11D2E" />
      <circle cx="12.2" cy="19.2" r="1.9" fill="#FFFFFF" />
      <circle cx="21.8" cy="19.2" r="1.9" fill="#FFFFFF" />
    </svg>
  );
}

function SignInIllustration() {
  return (
    <svg viewBox="0 0 360 300" className="w-full h-auto max-w-sm" xmlns="http://www.w3.org/2000/svg">
      {/* ground shadow */}
      <ellipse cx="190" cy="272" rx="120" ry="10" fill="#0B0F19" opacity="0.08" />

      {/* checklist card, back-left */}
      <g transform="translate(18,150)">
        <rect x="0" y="0" width="96" height="120" rx="10" fill="#FFFFFF" stroke="#D8DEE6" />
        <rect x="14" y="52" width="16" height="16" rx="3" fill="#F2B90C" />
        <path d="M18 60l3 3 6-6" stroke="#0B0F19" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="36" y="56" width="46" height="7" rx="3.5" fill="#E5E9EF" />
        <rect x="14" y="78" width="16" height="16" rx="3" fill="#16A34A" />
        <path d="M18 86l3 3 6-6" stroke="#FFFFFF" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="36" y="82" width="46" height="7" rx="3.5" fill="#E5E9EF" />
        <rect x="14" y="104" width="16" height="16" rx="3" fill="#F1F3F6" stroke="#D8DEE6" />
        <rect x="36" y="108" width="30" height="7" rx="3.5" fill="#E5E9EF" />
        <rect x="0" y="0" width="96" height="14" rx="10" fill="#E11D2E" />
      </g>

      {/* browser / dashboard window */}
      <g transform="translate(96,52)">
        <rect x="0" y="0" width="216" height="150" rx="10" fill="#FFFFFF" stroke="#D8DEE6" />
        <rect x="0" y="0" width="216" height="24" rx="10" fill="#0B0F19" />
        <circle cx="16" cy="12" r="3.4" fill="#E11D2E" />
        <circle cx="28" cy="12" r="3.4" fill="#F2B90C" />
        <circle cx="40" cy="12" r="3.4" fill="#16A34A" />
        <line x1="18" y1="118" x2="198" y2="118" stroke="#E5E9EF" strokeWidth="1.5" />
        <polyline points="26,92 62,72 98,84 134,58 170,68 198,40" fill="none" stroke="#0B0F19" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="198" cy="40" r="4.5" fill="#E11D2E" />
        <rect x="30" y="96" width="18" height="22" rx="2" fill="#F2B90C" />
        <rect x="62" y="80" width="18" height="38" rx="2" fill="#E11D2E" />
        <rect x="94" y="90" width="18" height="28" rx="2" fill="#F2B90C" />
        <rect x="126" y="66" width="18" height="52" rx="2" fill="#0B0F19" />
        <rect x="158" y="76" width="18" height="42" rx="2" fill="#F2B90C" />
      </g>

      {/* stacked crates, right */}
      <g transform="translate(268,120)">
        <rect x="0" y="24" width="52" height="34" rx="4" fill="#E11D2E" />
        <rect x="0" y="24" width="52" height="10" rx="4" fill="#B71424" />
        <rect x="10" y="0" width="34" height="26" rx="4" fill="#F2B90C" />
        <rect x="10" y="0" width="34" height="8" rx="4" fill="#C99807" />
      </g>

      {/* person */}
      <g transform="translate(150,150)">
        <circle cx="24" cy="10" r="11" fill="#0B0F19" />
        <path d="M4 78c0-24 8.9-40 20-40s20 16 20 40" fill="#E11D2E" />
        <rect x="21" y="34" width="6" height="14" fill="#0B0F19" />
      </g>
      {/* monitor stand under person, connecting to dashboard */}
      <rect x="163" y="150" width="8" height="46" fill="#0B0F19" />
      <rect x="145" y="192" width="44" height="6" rx="3" fill="#0B0F19" />
    </svg>
  );
}

export default function Login() {
  const { login, formatApiErrorDetail } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#EDF0F2] flex flex-col">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center gap-3">
          <BrandMark />
          <span className="font-head font-extrabold text-lg text-slate-900 tracking-tight">
            Primi<span className="text-[#E11D2E]">tek</span> Group
          </span>
          <span className="text-slate-300">|</span>
          <span className="text-slate-500 text-sm">Inventory &amp; Requisition Management</span>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-4xl bg-[#C7CDD3] rounded-2xl shadow-sm p-10 grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
          <div className="hidden md:flex items-center justify-center">
            <SignInIllustration />
          </div>

          <form onSubmit={submit} className="w-full" data-testid="login-form">
            <h1 className="font-head text-3xl font-bold text-slate-900">Sign In</h1>
            <p className="text-slate-600 text-sm mt-1 mb-7">Access your Requisition & Ineventory Dashboard</p>

            {error && (
              <div className="mb-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3" data-testid="login-error">
                {error}
              </div>
            )}

            <label className="block text-sm font-semibold text-slate-800 mb-1.5">Email</label>
            <input
              type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
              data-testid="login-email"
              className="w-full mb-5 px-4 py-3 rounded-lg bg-[#E9ECF7] border border-transparent focus:border-[#E11D2E] focus:ring-2 focus:ring-red-500/15 outline-none transition-colors placeholder:text-slate-400"
              placeholder="you@company.com"
            />
            <label className="block text-sm font-semibold text-slate-800 mb-1.5">Password</label>
            <input
              type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
              data-testid="login-password"
              className="w-full mb-7 px-4 py-3 rounded-lg bg-[#E9ECF7] border border-transparent focus:border-[#E11D2E] focus:ring-2 focus:ring-red-500/15 outline-none transition-colors placeholder:text-slate-400"
              placeholder="••••••••"
            />
            <button
              type="submit" disabled={loading} data-testid="login-submit"
              className="w-full py-3.5 rounded-lg bg-[#E11D2E] hover:bg-[#C4172A] text-white font-bold text-base transition-colors flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {loading && <Loader2 size={18} className="animate-spin" />}
              Login
            </button>
            <p className="mt-5 text-center text-sm font-medium text-slate-900" data-testid="login-forgot-hint">
              <b className="font-bold text-[#E11D2E]">Forgot your password?</b> Please contact the IT Team.
            </p>
            <p className="text-center text-xs text-slate-500 mt-3 font-mono">
              Primitek IMS · Secure Sign-in
            </p>
          </form>
        </div>
      </main>
    </div>
  );
}