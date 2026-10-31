import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Config, RunMeta } from "./types";

const RUN_KEY = "ews.activeRun";
const ANALYST_KEY = "ews.analyst";

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

interface Workspace {
  config?: Config;
  runs: RunMeta[];
  run?: RunMeta;
  runsLoading: boolean;
  setRunId: (id: string) => void;
  analyst: string;
  setAnalyst: (name: string) => void;
}

const Ctx = createContext<Workspace | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const config = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: Infinity });
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const [runId, setRunIdState] = useState<string | null>(() => read(RUN_KEY));
  const [analyst, setAnalystState] = useState<string>(() => read(ANALYST_KEY) ?? "");

  const list = runs.data ?? [];
  // fall back to the newest run without overwriting the stored choice
  const run = list.find((r) => r.run_id === runId) ?? list[0];

  const setRunId = useCallback((id: string) => { setRunIdState(id); write(RUN_KEY, id); }, []);
  const setAnalyst = useCallback((name: string) => { setAnalystState(name); write(ANALYST_KEY, name); }, []);

  const value = useMemo<Workspace>(() => ({
    config: config.data, runs: list, run, runsLoading: runs.isLoading, setRunId, analyst, setAnalyst,
  }), [config.data, list, run, runs.isLoading, setRunId, analyst, setAnalyst]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkspace(): Workspace {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useWorkspace outside WorkspaceProvider");
  return ctx;
}
