import type { BacktestCompareRun, BacktestRun } from "@/types";

export type BacktestTruthLevel =
  | "real"
  | "fallback_engine"
  | "synthetic"
  | "preview"
  | "unknown";

type BacktestLike = BacktestRun | BacktestCompareRun | null | undefined;

function getSummary(run: BacktestLike): Record<string, unknown> {
  if (!run) return {};
  if ("summary" in run && run.summary && typeof run.summary === "object") {
    return run.summary as Record<string, unknown>;
  }
  return ((run as BacktestRun).result?.summary ?? {}) as Record<
    string,
    unknown
  >;
}

function getDiagnostics(run: BacktestLike): Record<string, unknown> {
  if (!run) return {};
  if (
    "diagnostics" in run &&
    run.diagnostics &&
    typeof run.diagnostics === "object"
  ) {
    return run.diagnostics as Record<string, unknown>;
  }
  return ((run as BacktestRun).result?.diagnostics ?? {}) as Record<
    string,
    unknown
  >;
}

export function classifyBacktestTruth(run: BacktestLike): BacktestTruthLevel {
  if (!run) return "unknown";
  const summary = getSummary(run);
  const diagnostics = getDiagnostics(run);
  const runId = "id" in run ? run.id : run.run_id;
  const dataSource =
    typeof summary.data_source === "string" ? summary.data_source : "";
  const engineMode =
    typeof summary.engine_mode === "string" ? summary.engine_mode : "";

  if (runId.startsWith("local-preview")) return "preview";
  if (dataSource.startsWith("synthetic:")) return "synthetic";
  if (engineMode === "fallback_engine" || Boolean(diagnostics.fallback_mode))
    return "fallback_engine";
  if (dataSource) return "real";
  return "unknown";
}

export function getBacktestTruthLabel(level: BacktestTruthLevel): string {
  if (level === "real") return "真实数据";
  if (level === "fallback_engine") return "回退链路";
  if (level === "synthetic") return "Synthetic 数据";
  if (level === "preview") return "本地预览";
  return "待确认";
}

export function getBacktestTruthTone(level: BacktestTruthLevel): string {
  if (level === "real")
    return "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200";
  if (level === "unknown")
    return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
  return "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200";
}

export function getBacktestDataSourceText(run: BacktestLike): string {
  const summary = getSummary(run);
  return typeof summary.data_source === "string" ? summary.data_source : "--";
}

export function isSelectionValidationRun(run: BacktestLike): boolean {
  if (!run) return false;
  const summary = getSummary(run);
  return Boolean(
    summary.selection_only_mode ?? summary.strategy_type === "selection",
  );
}

export function isFormalCompareEligible(run: BacktestLike): boolean {
  if (!run) return false;
  return (
    run.status === "completed" &&
    classifyBacktestTruth(run) === "real" &&
    !isSelectionValidationRun(run)
  );
}
