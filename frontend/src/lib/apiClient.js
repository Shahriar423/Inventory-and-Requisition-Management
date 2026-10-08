import axios from "axios";

export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Token is stored in sessionStorage rather than a cookie so each browser TAB keeps its own
// independent login. sessionStorage is per-tab (a new tab opened via Ctrl+T / File > New Tab
// starts empty; only an exact tab *duplicate* copies it), unlike cookies which are shared
// by every tab in the browser. The backend still sets a cookie too (harmless fallback), but
// get_current_user() prioritizes this Authorization header over the cookie.
const TOKEN_KEY = "ims_access_token";
export const getToken = () => sessionStorage.getItem(TOKEN_KEY);
export const setToken = (t) => sessionStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => sessionStorage.removeItem(TOKEN_KEY);

// Helper for links opened via window.open() (PDF downloads, etc.) — those are plain
// navigations, not axios requests, so they can't carry the Authorization header. Append
// this tab's token as a query param instead; the backend accepts either.
export const withAuthParam = (url) => {
  const token = getToken();
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}auth=${encodeURIComponent(token)}`;
};

// Lightweight cross-component refresh signal. The bell notification lives in the global
// header and can change requisition/dashboard state (e.g. confirming receipt flips a
// requisition to "approved") while a completely different page component (Dashboard,
// RequisitionList) is mounted below it — those pages fetch once on mount and have no
// other way to know the data changed elsewhere. Call requestDataRefresh() after any
// action that changes requisition/dashboard data; pages listen via onDataRefresh().
const REFRESH_EVENT = "ims:data-refresh";
export const requestDataRefresh = () => window.dispatchEvent(new Event(REFRESH_EVENT));
export const onDataRefresh = (handler) => {
  window.addEventListener(REFRESH_EVENT, handler);
  return () => window.removeEventListener(REFRESH_EVENT, handler);
};

const api = axios.create({
  baseURL: API,
  withCredentials: true,
  headers: { "Cache-Control": "no-cache" },
});

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}

export default api;