import { createContext, useContext, useEffect, useState, useCallback } from "react";
import api, { formatApiErrorDetail } from "@/lib/apiClient";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null = checking, false = anon, object = auth
  const [menu, setMenu] = useState([]);
  const [allowed, setAllowed] = useState([]);

  const loadPermissions = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/permissions");
      setMenu(data.menu);
      setAllowed(data.allowed);
    } catch (e) {
      setMenu([]);
    }
  }, []);

  const bootstrap = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
      await loadPermissions();
    } catch (e) {
      setUser(false);
    }
  }, [loadPermissions]);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    // Prefer the login payload if it already includes enriched fields; then refresh
    // from /auth/me so department_name / role_label_display are always present
    // immediately (no page refresh required on New Requisition, Header, etc.).
    setUser(data.user);
    try {
      const me = await api.get("/auth/me");
      setUser(me.data);
    } catch (e) {
      /* keep login user if /me fails */
    }
    await loadPermissions();
    return data.user;
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch (e) {}
    setUser(false);
    setMenu([]);
  };

  return (
    <AuthContext.Provider value={{ user, menu, allowed, login, logout, refreshMe: bootstrap, formatApiErrorDetail }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);