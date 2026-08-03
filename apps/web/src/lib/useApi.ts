"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

interface State<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/** Fetch a GET endpoint on mount, with optional polling for pipeline pages. */
export function useApi<T>(path: string | null, pollMs = 0) {
  const [state, setState] = useState<State<T>>({ data: null, loading: true, error: null });

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const data = await api.get<T>(path);
      setState({ data, loading: false, error: null });
    } catch (err) {
      setState({ data: null, loading: false, error: (err as Error).message });
    }
  }, [path]);

  useEffect(() => {
    load();
    if (pollMs > 0) {
      const id = setInterval(load, pollMs);
      return () => clearInterval(id);
    }
  }, [load, pollMs]);

  return { ...state, reload: load };
}
