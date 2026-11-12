import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/apiClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useAuth } from "@/context/AuthContext";
import Avatar from "@/components/Avatar";

const MAX_INPUT = 10 * 1024 * 1024;   // what we accept from the computer; it is shrunk to ~512px before upload

/** Centre-crops to a square and shrinks to 512x512 (JPEG) so uploads stay small and every picture looks alike. */
function toSquareBlob(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const side = Math.min(img.width, img.height);
      const out = Math.min(512, side);
      const canvas = document.createElement("canvas");
      canvas.width = out; canvas.height = out;
      canvas.getContext("2d").drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, out, out);
      URL.revokeObjectURL(url);
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("convert"))), "image/jpeg", 0.9);
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("read")); };
    img.src = url;
  });
}

/** Dialog: a signed-in user changes or removes their own profile picture. */
export default function ProfilePhotoDialog({ open, onOpenChange }) {
  const { user, refreshMe } = useAuth();
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef(null);

  useEffect(() => { if (!open) { setFile(null); setPreview(""); } }, [open]);
  useEffect(() => {
    if (!file) { setPreview(""); return undefined; }
    const u = URL.createObjectURL(file);
    setPreview(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  const pick = (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (!/^image\/(png|jpe?g|webp)$/i.test(f.type)) return toast.error("Please choose a PNG, JPEG or WebP image");
    if (f.size > MAX_INPUT) return toast.error("That picture is too large (max 10 MB)");
    setFile(f);
  };

  const save = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const blob = await toSquareBlob(file);
      const fd = new FormData();
      fd.append("file", blob, "avatar.jpg");
      await api.post("/auth/me/avatar", fd, { headers: { "Content-Type": "multipart/form-data" } });
      await refreshMe();
      toast.success("Profile picture updated");
      onOpenChange(false);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not update the picture");
    } finally { setBusy(false); }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.delete("/auth/me/avatar");
      await refreshMe();
      toast.success("Profile picture removed");
      onOpenChange(false);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Could not remove the picture");
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm" data-testid="profile-photo-modal">
        <DialogHeader>
          <DialogTitle>Profile picture</DialogTitle>
          <DialogDescription>PNG, JPEG or WebP. It is cropped to a square automatically.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col items-center gap-4 py-2">
          {preview
            ? <img src={preview} alt="Preview" className="w-28 h-28 rounded-full object-cover" data-testid="photo-preview" />
            : <Avatar user={user} size={112} testid="photo-current" />}
          <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" onChange={pick} className="hidden" data-testid="photo-input" />
          <button type="button" onClick={() => input.current?.click()} disabled={busy}
            className="px-4 py-2 rounded-lg border border-slate-300 text-sm font-medium text-slate-700 hover:bg-slate-50">
            {preview ? "Choose a different picture" : "Choose a picture"}
          </button>
        </div>
        <div className="flex items-center justify-between pt-1">
          {user?.avatar_version && !file
            ? <button type="button" onClick={remove} disabled={busy} data-testid="photo-remove" className="text-sm text-red-600 hover:text-red-700">Remove picture</button>
            : <span />}
          <div className="flex gap-2">
            <button type="button" onClick={() => onOpenChange(false)} className="px-4 py-2 rounded-lg text-slate-500 text-sm hover:text-slate-700">Cancel</button>
            <button type="button" onClick={save} disabled={!file || busy} data-testid="photo-save"
              className="px-4 py-2 rounded-lg bg-amber-600 text-white text-sm font-semibold hover:bg-amber-700 disabled:opacity-50">
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}