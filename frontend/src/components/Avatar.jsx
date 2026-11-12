import { useEffect, useState } from "react";
import { API, withAuthParam } from "@/lib/apiClient";

export function initials(name) {
  return (name || "?").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}

/** A person's profile picture, or their initials when they have not uploaded one (or it fails to load). */
export default function Avatar({ user, size = 40, className = "", testid }) {
  const [failed, setFailed] = useState(false);
  const version = user?.avatar_version;
  useEffect(() => { setFailed(false); }, [version, user?.id]);
  const box = { width: size, height: size, fontSize: Math.max(11, Math.round(size * 0.36)) };
  if (version && user?.id && !failed) {
    return (
      <img
        src={withAuthParam(`${API}/users/${user.id}/avatar?v=${encodeURIComponent(version)}`)}
        alt={user?.name || "Profile"} style={box} onError={() => setFailed(true)}
        data-testid={testid} className={`rounded-full object-cover bg-slate-100 ${className}`}
      />
    );
  }
  return (
    <div style={box} data-testid={testid}
      className={`rounded-full bg-amber-100 text-amber-700 flex items-center justify-center font-semibold ${className}`}>
      {initials(user?.name)}
    </div>
  );
}