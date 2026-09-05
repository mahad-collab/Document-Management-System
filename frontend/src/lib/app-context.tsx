"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, ApiError, loginUrl } from "./api";
import type { CurrentUserInfo, Department, UUID } from "./types";

const SELECTED_DEPT_KEY = "puma-dms.selectedDepartmentId";

interface AppContextValue {
  user: CurrentUserInfo | null;
  loadingUser: boolean;
  departments: Department[];
  loadingDepartments: boolean;
  selectedDepartmentId: UUID | null;
  setSelectedDepartmentId: (id: UUID | null) => void;
  selectedDepartment: Department | null;
  refreshUser: () => Promise<void>;
  refreshDepartments: () => Promise<void>;
  logout: () => Promise<void>;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUserInfo | null>(null);
  const [loadingUser, setLoadingUser] = useState(true);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loadingDepartments, setLoadingDepartments] = useState(false);
  const [selectedDepartmentId, setSelectedDepartmentIdState] = useState<UUID | null>(null);

  const refreshUser = useCallback(async () => {
    setLoadingUser(true);
    try {
      const me = await api.me();
      setUser(me);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
      } else {
        throw err;
      }
    } finally {
      setLoadingUser(false);
    }
  }, []);

  const refreshDepartments = useCallback(async () => {
    setLoadingDepartments(true);
    try {
      const list = await api.listDepartments();
      setDepartments(list);
    } finally {
      setLoadingDepartments(false);
    }
  }, []);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  useEffect(() => {
    if (user) refreshDepartments();
  }, [user, refreshDepartments]);

  useEffect(() => {
    const stored = typeof window !== "undefined" ? window.localStorage.getItem(SELECTED_DEPT_KEY) : null;
    if (stored) setSelectedDepartmentIdState(stored);
  }, []);

  // If the previously-selected department disappears from the list (or none
  // was ever chosen), default to the first one the user actually holds.
  useEffect(() => {
    if (departments.length === 0) return;
    const stillValid = departments.some((d) => d.id === selectedDepartmentId);
    if (!stillValid) {
      const fallback = departments.find((d) => user?.departments.includes(d.id)) ?? departments[0];
      setSelectedDepartmentIdState(fallback?.id ?? null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [departments]);

  const setSelectedDepartmentId = useCallback((id: UUID | null) => {
    setSelectedDepartmentIdState(id);
    if (typeof window !== "undefined") {
      if (id) window.localStorage.setItem(SELECTED_DEPT_KEY, id);
      else window.localStorage.removeItem(SELECTED_DEPT_KEY);
    }
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
    setDepartments([]);
    setSelectedDepartmentId(null);
  }, [setSelectedDepartmentId]);

  const selectedDepartment = useMemo(
    () => departments.find((d) => d.id === selectedDepartmentId) ?? null,
    [departments, selectedDepartmentId]
  );

  const value: AppContextValue = {
    user,
    loadingUser,
    departments,
    loadingDepartments,
    selectedDepartmentId,
    setSelectedDepartmentId,
    selectedDepartment,
    refreshUser,
    refreshDepartments,
    logout,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}

export { loginUrl };
