import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Package, Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

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
    <div className="min-h-screen flex">
      <div className="hidden lg:flex flex-col justify-between w-1/2 bg-[#070E20] p-14 text-white relative overflow-hidden">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-600 flex items-center justify-center">
            <Package size={22} />
          </div>
          <div>
            <div className="font-head font-bold text-xl leading-none">IMS</div>
            <div className="text-slate-400 text-xs mt-1">Inventory &amp; Requisition</div>
          </div>
        </div>
        <div>
          <h2 className="font-head text-4xl font-bold leading-tight">IT Requisition &amp;<br /><span className="text-amber-500">Asset Management</span></h2>
          <p className="text-slate-400 mt-4 max-w-md leading-relaxed">
            Raise product &amp; service requisitions, route them through role-based approval chains, and manage assets end-to-end.
          </p>
        </div>
        <div className="font-mono text-xs text-slate-500">Primitek Group · Head Office</div>
      </div>

      <div className="flex-1 flex items-center justify-center p-8 bg-[#F8FAFC]">
        <form onSubmit={submit} className="w-full max-w-sm" data-testid="login-form">
          <h1 className="font-head text-2xl font-bold text-slate-900">Welcome back</h1>
          <p className="text-slate-500 text-sm mt-1 mb-8">Sign in to your IMS workspace.</p>

          {error && (
            <div className="mb-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3" data-testid="login-error">
              {error}
            </div>
          )}

          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Email</label>
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
            data-testid="login-email"
            className="w-full mb-5 px-4 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20 outline-none transition-colors"
            placeholder="you@company.com"
          />
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Password</label>
          <input
            type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
            data-testid="login-password"
            className="w-full mb-6 px-4 py-2.5 rounded-lg border border-slate-300 focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20 outline-none transition-colors"
            placeholder="••••••••"
          />
          <button
            type="submit" disabled={loading} data-testid="login-submit"
            className="w-full py-2.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold transition-colors flex items-center justify-center gap-2 disabled:opacity-60"
          >
            {loading && <Loader2 size={18} className="animate-spin" />}
            Sign In
          </button>
        </form>
      </div>
    </div>
  );
}
