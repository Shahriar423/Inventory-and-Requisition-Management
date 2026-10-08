import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { showResult } from "@/components/ResultPopup";
import { useAuth } from "@/context/AuthContext";

const MIN_LEN = 8;
const inp = "w-full h-11 pl-3 pr-11 rounded-lg border border-slate-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-amber-500";

function PasswordField({ label, value, onChange, testid, autoComplete, error }) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1">{label}</label>
      <div className="relative">
        <input type={show ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete} data-testid={testid} className={`${inp} ${error ? "border-red-400 focus:ring-red-400" : ""}`} />
        <button type="button" tabIndex={-1} onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700">
          {show ? <EyeOff size={18} /> : <Eye size={18} />}
        </button>
      </div>
      {error && <div className="text-xs text-red-600 mt-1">{error}</div>}
    </div>
  );
}

/** Dialog: any signed-in user changes their OWN password at any time.
 *  Opened from the profile menu in the header (controlled via open / onOpenChange).
 *  forced = true: shown after an admin reset - cannot be closed until a new password is set. */
export default function ChangePasswordDialog({ open, onOpenChange: setOpen, forced = false }) {
  const { refreshMe, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);

  const reset = () => { setCurrent(""); setNext(""); setConfirm(""); };
  const onOpenChange = (v) => { if (forced && !v) return; setOpen(v); if (!v) reset(); };

  const nextErr = next && next.length < MIN_LEN ? `Use at least ${MIN_LEN} characters` : (next && next === current ? "Must be different from the current password" : "");
  const confirmErr = confirm && confirm !== next ? "Passwords do not match" : "";
  const canSave = current && next && confirm && !nextErr && !confirmErr && !saving;

  const save = async (e) => {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      setOpen(false);
      reset();
      if (forced) await refreshMe();      // clears the "must change password" lock
      showResult({ title: "Done!", message: "Your password has been changed successfully. Use the new password next time you sign in." });
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Could not change password");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className={`max-w-md ${forced ? "[&>button]:hidden" : ""}`} data-testid="change-password-modal"
          onInteractOutside={(e) => { if (forced) e.preventDefault(); }}
          onEscapeKeyDown={(e) => { if (forced) e.preventDefault(); }}>
          <DialogHeader>
            <DialogTitle>{forced ? "Set a new password" : "Change your password"}</DialogTitle>
            <DialogDescription>{forced
              ? "Your password was reset by an administrator. Enter the temporary password you were given, then choose your own new password to continue."
              : "Enter your current password, then choose a new one. You stay signed in."}</DialogDescription>
          </DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <PasswordField label={forced ? "Temporary password" : "Current password"} value={current} onChange={setCurrent} autoComplete="current-password" testid="cp-current" />
            <PasswordField label="New password" value={next} onChange={setNext} autoComplete="new-password" testid="cp-new" error={nextErr} />
            <PasswordField label="Confirm new password" value={confirm} onChange={setConfirm} autoComplete="new-password" testid="cp-confirm" error={confirmErr} />
            <div className="flex justify-end gap-3 pt-2">
              {forced ? (
                <button type="button" onClick={logout} data-testid="cp-signout"
                  className="px-4 py-2 rounded-lg border border-slate-300 text-sm text-slate-600 hover:bg-slate-50">Sign out</button>
              ) : (
                <button type="button" onClick={() => onOpenChange(false)}
                  className="px-4 py-2 rounded-lg border border-slate-300 text-sm text-slate-600 hover:bg-slate-50">Cancel</button>
              )}
              <button type="submit" disabled={!canSave} data-testid="cp-save"
                className="px-5 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed">
                {saving ? "Saving…" : "Change password"}
              </button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}