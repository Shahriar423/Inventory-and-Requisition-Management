import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Mail, Lock, Eye, EyeOff, ShieldCheck } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/apiClient";
import logo from "@/assets/primitek-logo.webp";

// Animated "requisition -> approval -> purchase -> stock -> delivery" scene.
// Pure SVG + CSS keyframes (no libraries). Respects prefers-reduced-motion.
const SCENE_CSS = `
.lg-node-on{opacity:0;animation:lgNodeOn 8s ease-in-out infinite}
@keyframes lgNodeOn{0%{opacity:0}5%{opacity:1}22%{opacity:1}32%{opacity:0}100%{opacity:0}}

.lg-box{transform-box:fill-box;transform-origin:50% 100%;opacity:0;animation:lgBoxIn 9s ease-out infinite}
@keyframes lgBoxIn{0%{opacity:0;transform:scale(.2)}5%{opacity:1;transform:scale(1.1)}8%{opacity:1;transform:scale(1)}88%{opacity:1;transform:scale(1)}96%{opacity:0;transform:scale(1)}100%{opacity:0}}

.lg-tick{stroke-dasharray:22;stroke-dashoffset:22;animation:lgTick 8s ease-out infinite}
@keyframes lgTick{0%{stroke-dashoffset:22}8%{stroke-dashoffset:0}85%{stroke-dashoffset:0}94%{stroke-dashoffset:22}100%{stroke-dashoffset:22}}
.lg-tickbg{opacity:0;animation:lgTickBg 8s ease-out infinite}
@keyframes lgTickBg{0%{opacity:0}6%{opacity:1}85%{opacity:1}94%{opacity:0}100%{opacity:0}}

.lg-stamp{transform-box:fill-box;transform-origin:center;opacity:0;animation:lgStamp 8s cubic-bezier(.2,1.4,.4,1) infinite}
@keyframes lgStamp{0%,56%{opacity:0;transform:scale(1.8) rotate(-8deg)}64%{opacity:1;transform:scale(1) rotate(-4deg)}88%{opacity:1;transform:scale(1) rotate(-4deg)}96%,100%{opacity:0}}

.lg-belt-box{animation:lgBelt 9s linear infinite}
@keyframes lgBelt{from{transform:translateX(-70px)}to{transform:translateX(540px)}}
.lg-belt-line{animation:lgBeltLine 1.2s linear infinite}
@keyframes lgBeltLine{to{stroke-dashoffset:-18}}
.lg-wheel{transform-box:fill-box;transform-origin:center;animation:lgSpin 2.4s linear infinite}
@keyframes lgSpin{to{transform:rotate(360deg)}}

.lg-float{animation:lgFloat 6s ease-in-out infinite}
@keyframes lgFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}

.lg-pulse{animation:lgPulse 2.4s ease-in-out infinite}
@keyframes lgPulse{0%,100%{opacity:.55}50%{opacity:1}}

@media (prefers-reduced-motion: reduce){
  .lg-node-on,.lg-box,.lg-tick,.lg-tickbg,.lg-stamp,.lg-belt-box,.lg-belt-line,.lg-wheel,.lg-float,.lg-pulse{animation:none!important}
  .lg-box,.lg-tickbg,.lg-stamp{opacity:1}.lg-tick{stroke-dashoffset:0}
  .lg-belt-box{transform:translateX(160px)}
}
`;

const BOX_COLORS = ["#F2B90C", "#E11D2E", "#F8FAFC", "#F2B90C", "#F8FAFC", "#E11D2E", "#E11D2E", "#F2B90C", "#F8FAFC", "#F8FAFC", "#E11D2E", "#F2B90C"];

function InventoryScene() {
  const nodes = [
    { x: 60, label: "Request", delay: "0s" },
    { x: 193, label: "Approve", delay: "2.6s" },
    { x: 327, label: "Purchase", delay: "5.2s" },
    { x: 460, label: "Handover", delay: "7.6s" },
  ];
  const shelfRows = [10, 60, 110];          // top y of each box row
  const colX = [18, 66, 114, 162];          // x of each box column

  return (
    <svg viewBox="0 0 520 380" className="w-full h-auto" xmlns="http://www.w3.org/2000/svg" role="img"
      aria-label="Requisition approved, goods received into stock and dispatched">
      <style>{SCENE_CSS}</style>

      {/* floating background dots */}
      <circle className="lg-float" cx="30" cy="150" r="3" fill="#E11D2E" opacity=".5" />
      <circle className="lg-float" style={{ animationDelay: "1.5s" }} cx="500" cy="190" r="4" fill="#F2B90C" opacity=".5" />
      <circle className="lg-float" style={{ animationDelay: "3s" }} cx="260" cy="365" r="3" fill="#16A34A" opacity=".5" />

      {/* ---- process pipeline ---- */}
      <line x1="60" y1="44" x2="460" y2="44" stroke="#334155" strokeWidth="2" strokeDasharray="4 6" />
      {nodes.map((n, i) => (
        <g key={n.label} transform={`translate(${n.x},44)`}>
          <circle r="17" fill="#111827" stroke="#334155" strokeWidth="1.5" />
          <circle r="17" fill="#E11D2E" className="lg-node-on" style={{ animationDelay: n.delay }} />
          {/* icons */}
          {i === 0 && (<g stroke="#fff" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round">
            <rect x="-6" y="-8" width="12" height="16" rx="2" /><path d="M-3 -3h6M-3 1h6M-3 5h3" /></g>)}
          {i === 1 && (<path d="M-7 0l4.5 4.5L7 -5" stroke="#fff" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />)}
          {i === 2 && (<g stroke="#fff" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round">
            <path d="M-8 -8h3l2 10h9l2-7h-12" /><circle cx="-1" cy="6" r="1.4" fill="#fff" /><circle cx="7" cy="6" r="1.4" fill="#fff" /></g>)}
          {i === 3 && (<g stroke="#fff" strokeWidth="1.7" fill="none" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="0" cy="-3.5" r="3.8" /><path d="M-7.5 8.5c0-4.4 3.3-7 7.5-7s7.5 2.6 7.5 7" /></g>)}
          <text y="36" textAnchor="middle" fontSize="11" fontWeight="600" fill="#94A3B8" fontFamily="inherit">{n.label}</text>
        </g>
      ))}
      <circle r="4.5" fill="#F2B90C">
        <animateMotion dur="8s" repeatCount="indefinite" path="M60 44 L460 44" />
      </circle>

      {/* ---- requisition document ---- */}
      <g transform="translate(34,112)">
        <rect width="156" height="158" rx="12" fill="#FFFFFF" />
        <path d="M0 12a12 12 0 0 1 12-12h132a12 12 0 0 1 12 12v10H0Z" fill="#E11D2E" />
        <text x="14" y="16" fontSize="9" fontWeight="800" fill="#fff" letterSpacing="1.4" fontFamily="inherit">REQUISITION</text>
        <circle cx="140" cy="11" r="3" fill="#fff" className="lg-pulse" />
        {[0, 1, 2].map((r) => (
          <g key={r} transform={`translate(14,${38 + r * 28})`}>
            <rect width="16" height="16" rx="4" fill="#F1F3F6" stroke="#D8DEE6" />
            <rect width="16" height="16" rx="4" fill="#16A34A" className="lg-tickbg" style={{ animationDelay: `${0.6 + r * 1.5}s` }} />
            <path d="M3.5 8.5l3 3 6-6.5" stroke="#fff" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"
              className="lg-tick" style={{ animationDelay: `${0.6 + r * 1.5}s` }} />
            <rect x="26" y="2" width={[84, 68, 76][r]} height="6" rx="3" fill="#E2E8F0" />
            <rect x="26" y="11" width={[44, 52, 38][r]} height="4" rx="2" fill="#EEF1F5" />
          </g>
        ))}
        <g className="lg-stamp" transform="translate(78,142)">
          <rect x="-48" y="-9" width="96" height="18" rx="4" fill="#fff" stroke="#16A34A" strokeWidth="1.6" />
          <text textAnchor="middle" y="4" fontSize="10" fontWeight="800" fill="#16A34A" letterSpacing="1.6" fontFamily="inherit">APPROVED</text>
        </g>
      </g>

      {/* ---- stock shelves ---- */}
      <g transform="translate(250,112)">
        <text x="0" y="-8" fontSize="10" fontWeight="700" fill="#94A3B8" letterSpacing="1.6" fontFamily="inherit">STOCK</text>
        <rect x="0" y="0" width="6" height="158" rx="2" fill="#475569" />
        <rect x="244" y="0" width="6" height="158" rx="2" fill="#475569" />
        {shelfRows.map((y) => (<rect key={y} x="0" y={y + 34} width="250" height="6" rx="2" fill="#64748B" />))}
        {shelfRows.map((y, r) =>
          colX.map((x, c) => {
            const i = r * 4 + c;
            const w = 40 + ((i * 7) % 3) * 4;
            const h = 28 + ((i * 5) % 3) * 2;
            return (
              <g key={i} className="lg-box" style={{ animationDelay: `${i * 0.45}s` }}>
                <rect x={x} y={y + 34 - h} width={w} height={h} rx="3" fill={BOX_COLORS[i]} />
                <rect x={x} y={y + 34 - h} width={w} height="6" rx="3" fill="#000" opacity=".14" />
                <rect x={x + w / 2 - 4} y={y + 34 - h} width="8" height={h} fill="#000" opacity=".08" />
              </g>
            );
          })
        )}
      </g>

      {/* ---- conveyor belt: goods received and dispatched ---- */}
      <g>
        <rect x="20" y="304" width="480" height="16" rx="8" fill="#1F2937" />
        <line x1="30" y1="312" x2="490" y2="312" stroke="#64748B" strokeWidth="2" strokeDasharray="10 8" className="lg-belt-line" />
        {[50, 130, 210, 290, 370, 450].map((x) => (
          <g key={x}>
            <circle cx={x} cy="332" r="8" fill="#334155" className="lg-wheel" />
            <circle cx={x} cy="332" r="2.2" fill="#94A3B8" />
          </g>
        ))}
        {[0, 3, 6].map((d, i) => (
          <g key={d} className="lg-belt-box" style={{ animationDelay: `${d}s` }}>
            <rect x="0" y="270" width="44" height="34" rx="4" fill={["#F2B90C", "#E11D2E", "#F8FAFC"][i]} />
            <rect x="0" y="270" width="44" height="7" rx="3" fill="#000" opacity=".14" />
            <rect x="18" y="270" width="8" height="34" fill="#000" opacity=".08" />
          </g>
        ))}
        {/* <text x="20" y="362" fontSize="10" fontWeight="600" fill="#64748B" letterSpacing="1.2" fontFamily="inherit">GOODS RECEIVED  →  ISSUED TO EMPLOYEE</text> */}
      </g>
    </svg>
  );
}

export default function Login() {
  const { login, formatApiErrorDetail } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
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
      setError(
        err.response
          ? formatApiErrorDetail(err.response.data?.detail)
          : `Cannot reach the server at ${API}. Is the backend running?`
      );
    } finally {
      setLoading(false);
    }
  };

  const inputCls =
    "w-full pl-11 pr-4 py-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-900 placeholder:text-slate-400 " +
    "focus:bg-white focus:border-[#E11D2E] focus:ring-4 focus:ring-red-500/10 outline-none transition";

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#F5F7F9] to-[#E6EBF0] flex flex-col">
      {/* Header: exact brand logo, flush left */}
      <header className="bg-white border-b border-slate-200">
        <div className="px-5 sm:px-10 py-2.5 inline-flex flex-col items-start">
          <img src={logo} alt="Primitek Group" width="860" height="162" decoding="async" className="h-9 w-auto select-none" draggable="false" data-testid="login-logo" />
          <span className="mt-1 text-[11px] font-medium tracking-wide text-slate-500 leading-none" data-testid="login-tagline">
            Inventory &amp; Requisition Management
          </span>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center px-4 py-10">
        <div className="w-full max-w-5xl bg-white rounded-3xl shadow-[0_24px_60px_-20px_rgba(15,23,42,0.35)] border border-slate-200/70 overflow-hidden grid grid-cols-1 md:grid-cols-[1.1fr_1fr]">
          {/* Left: animated inventory + requisition scene */}
          <div
            className="hidden md:flex relative flex-col justify-between p-8 text-white"
            style={{ backgroundColor: "#0B0F19", backgroundImage: "radial-gradient(rgba(255,255,255,.06) 1px, transparent 1px)", backgroundSize: "22px 22px" }}
          >
            <div className="pointer-events-none absolute -top-24 -left-24 h-64 w-64 rounded-full bg-[#E11D2E]/25 blur-3xl" />
            <div className="pointer-events-none absolute -bottom-24 -right-16 h-64 w-64 rounded-full bg-[#F2B90C]/15 blur-3xl" />

            <div className="relative">
              {/* <div className="text-[11px] font-semibold tracking-[0.22em] text-[#F2B90C]">REQUISITION · PROCUREMENT · STOCK</div> */}
              <h2 className="font-head text-2xl font-bold leading-snug mt-2">
                Smart Requisitions & Inventory,<br />tracked end to end.
              </h2>
            </div>

            <div className="relative my-4"><InventoryScene /></div>

            <div className="relative flex flex-wrap gap-2 text-xs text-slate-300">
              {[["#E11D2E", "Requisition"], ["#F2B90C", "Approval"], ["#16A34A", "Stock & Handover"]].map(([c, t]) => (
                <span key={t} className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: c }} />{t}
                </span>
              ))}
            </div>
          </div>

          {/* Right: sign-in form */}
          <form onSubmit={submit} className="w-full p-8 sm:p-12 flex flex-col justify-center" data-testid="login-form">
            <h1 className="font-head text-3xl font-bold text-slate-900">Welcome back</h1>
            <p className="text-slate-500 text-sm mt-1.5 mb-8">Sign in to your Requisition &amp; Inventory dashboard</p>

            {error && (
              <div className="mb-5 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-4 py-3" data-testid="login-error">
                {error}
              </div>
            )}

            <label className="block text-sm font-semibold text-slate-700 mb-1.5">Email</label>
            <div className="relative mb-5">
              <Mail size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username"
                data-testid="login-email" className={inputCls} placeholder="you@company.com" />
            </div>

            <label className="block text-sm font-semibold text-slate-700 mb-1.5">Password</label>
            <div className="relative mb-7">
              <Lock size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
              <input type={showPw ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} required
                autoComplete="current-password" data-testid="login-password" className={`${inputCls} pr-12`} placeholder="••••••••" />
              <button type="button" onClick={() => setShowPw((v) => !v)} aria-label={showPw ? "Hide password" : "Show password"}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition">
                {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>

            <button type="submit" disabled={loading} data-testid="login-submit"
              className="w-full py-3.5 rounded-xl bg-gradient-to-r from-[#E11D2E] to-[#C4172A] hover:from-[#C4172A] hover:to-[#A91224] text-white font-bold text-base shadow-lg shadow-red-500/25 transition flex items-center justify-center gap-2 disabled:opacity-60">
              {loading && <Loader2 size={18} className="animate-spin" />}
              {loading ? "Signing in…" : "Login"}
            </button>

            <p className="mt-6 text-center text-sm text-slate-600" data-testid="login-forgot-hint">
              <b className="font-semibold text-[#E11D2E]">Forgot your password?</b> Please contact the IT Team.
            </p>
            <p className="mt-4 flex items-center justify-center gap-1.5 text-xs text-slate-400 font-mono">
              <ShieldCheck size={14} /> Primitek IMS · Secure Sign-in
            </p>
          </form>
        </div>
      </main>
    </div>
  );
}