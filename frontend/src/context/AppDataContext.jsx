import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiGet } from "../api/client.js";

const AppDataContext = createContext(null);

export function AppDataProvider({ children }) {
  const [profile, setProfile] = useState(null);
  const [preferences, setPreferences] = useState(null);
  const [resumes, setResumes] = useState([]);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);

  const reloadProfile = useCallback(async () => {
    try {
      setProfile(await apiGet("/profile"));
    } catch {
      setProfile(null);
    }
  }, []);

  const reloadPreferences = useCallback(async () => {
    setPreferences(await apiGet("/preferences"));
  }, []);

  const reloadResumes = useCallback(async () => {
    setResumes(await apiGet("/resumes"));
  }, []);

  const reloadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [h, p, prefs, res] = await Promise.allSettled([
        apiGet("/health"),
        apiGet("/profile"),
        apiGet("/preferences"),
        apiGet("/resumes"),
      ]);
      setHealth(h.status === "fulfilled" ? h.value : null);
      setProfile(p.status === "fulfilled" ? p.value : null);
      setPreferences(prefs.status === "fulfilled" ? prefs.value : null);
      setResumes(res.status === "fulfilled" ? res.value : []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reloadAll();
  }, [reloadAll]);

  const value = {
    profile,
    preferences,
    resumes,
    health,
    loading,
    reloadProfile,
    reloadPreferences,
    reloadResumes,
    reloadAll,
  };

  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>;
}

export function useAppData() {
  const context = useContext(AppDataContext);
  if (!context) throw new Error("useAppData must be used within AppDataProvider");
  return context;
}