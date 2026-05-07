import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import JSZip from "jszip";
import {
  ArrowDownTrayIcon,
  ArrowPathIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ClockIcon,
  ChartBarIcon,
  PlayIcon,
  ShieldCheckIcon,
} from "@heroicons/react/24/outline";
import { api } from "@/services/api";
import type {
  BacktestCompareResponse,
  BacktestCompareRun,
  BacktestEquityPoint,
  BacktestMinuteConfirmationItem,
  BacktestOrderItem,
  BacktestPositionItem,
  BacktestRun,
  BacktestSignalItem,
  BacktestStatusEvent,
  BacktestTradeRecord,
  BacktestTradeSnapshot,
  BacktestUiMode,
  BacktestUniverseScope,
  BacktestWatchlistItem,
  StrategyDefinition,
  StrategyPlatformType,
} from "@/types";
import {
  classifyBacktestTruth,
  getBacktestDataSourceText,
  getBacktestTruthLabel,
  getBacktestTruthTone,
  isFormalCompareEligible,
  isSelectionValidationRun,
} from "@/utils/backtestTrust";

function formatPercent(value?: number | null) {
  if (value == null) return "--";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function formatDateTime(value?: string | null) {
  if (!value) return "--";
  return value.slice(0, 19).replace("T", " ");
}

function downloadBlob(filename: string, blob: Blob) {
  const link = document.createElement("a");
  const url = window.URL.createObjectURL(blob);
  link.href = url;
  link.download = filename;
  link.click();
  window.URL.revokeObjectURL(url);
}

function toChineseBacktestStatus(value?: string | null) {
  if (!value) return "--";
  const mapping: Record<string, string> = {
    pending: "待执行",
    running: "执行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return mapping[value] || value;
}

function toChineseBacktestStage(value?: string | null) {
  if (!value) return "--";
  const mapping: Record<string, string> = {
    queued: "排队中",
    created: "任务创建",
    compile: "编译策略",
    prepare_data: "准备数据",
    run_engine: "执行引擎",
    write_artifacts: "写入结果",
    completed: "完成",
    failed: "失败",
    cancelled: "已取消",
    heartbeat: "心跳",
    running: "执行中",
  };
  return mapping[value] || value;
}

function toChineseStrategyType(type?: StrategyPlatformType | string | null) {
  const mapping: Record<string, string> = {
    selection: "选股策略",
    trading: "交易策略",
    risk: "风控策略",
    portfolio: "组合策略",
  };
  return type ? mapping[String(type)] || String(type) : "未识别策略";
}

function getStrategyTypeHint(type?: StrategyPlatformType | string | null) {
  if (type === "selection")
    return "本次重点验证候选池质量；股票池决定扫描范围，买卖参数仅在选择交易型模式时参与撮合。";
  if (type === "risk")
    return "本次重点验证风控覆盖效果；建议使用已有交易信号搭配不同成本与资金约束。";
  if (type === "portfolio")
    return "本次验证选股、交易、仓位和风控一体化表现，适合日线选股 + 分时买卖模式。";
  return "本次重点验证买卖信号、成交成本和 A 股撮合约束，适合日线或日线 + 分时模式。";
}

function getStrategyFocusTags(
  type?: StrategyPlatformType | string | null,
): string[] {
  if (type === "selection") return ["候选池质量", "股票池范围", "选股时机"];
  if (type === "risk") return ["回撤控制", "仓位约束", "风险覆盖"];
  if (type === "portfolio") return ["组合协同", "仓位管理", "日线 + 分时"];
  return ["买卖信号", "成交成本", "A 股撮合"];
}

function getCapitalLabel(type?: StrategyPlatformType | string | null) {
  if (type === "risk" || type === "portfolio") return "组合初始资金";
  return "初始资金";
}

function getModeHint(
  type?: StrategyPlatformType | string | null,
  useMinuteMode?: boolean,
) {
  if (type === "selection") {
    return useMinuteMode
      ? "当前会先按日线产出候选池，再用分钟层确认入场时机；适合“选股 + 波段交易”联动验证。"
      : "当前仅验证选股信号与候选池，不读取分钟线，适合快速筛选选股策略。";
  }
  if (type === "risk") {
    return useMinuteMode
      ? "当前会在分钟层检查风控策略对真实买卖节奏的影响。"
      : "当前主要看风控条件对日线交易链路的约束效果。";
  }
  if (type === "portfolio") {
    return useMinuteMode
      ? "当前以组合策略全链路验证为主，适合同时检查选股、仓位、风控和分时执行。"
      : "当前仅验证组合策略的日线层表现，不进入分钟确认。";
  }
  return useMinuteMode
    ? "当前启用分钟执行层，适合验证交易策略的入场确认和买卖节奏。"
    : "当前仅运行日线层，适合快速检查交易策略的大方向与成本敏感度。";
}

function parseSymbolList(value: string): string[] {
  return value
    .split(/[,，\s\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

const terminalBacktestStatuses = new Set(["completed", "failed", "cancelled"]);

type BacktestFormState = {
  universe_scope: BacktestUniverseScope;
  sector_name: string;
  symbols: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  commission_rate: number;
  min_commission: number;
  stamp_duty_rate: number;
  slippage_rate: number;
  backtest_mode: BacktestUiMode;
  minute_lazy_load: boolean;
  minute_missing_data_policy: "skip" | "fallback";
  benchmark: string;
};

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function parseSseBlock(block: string): { event: string; data: unknown } | null {
  const lines = block.split("\n").map((line) => line.trimEnd());
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLines = lines.filter((line) => line.startsWith("data:"));
  if (dataLines.length === 0) return null;
  const event = eventLine?.replace(/^event:\s*/, "") || "message";
  const rawData = dataLines
    .map((line) => line.replace(/^data:\s?/, ""))
    .join("\n");
  try {
    return { event, data: JSON.parse(rawData) };
  } catch {
    return null;
  }
}

function mergeRecentRuns(items: BacktestRun[], limit = 8) {
  const deduped = new Map<string, BacktestRun>();
  for (const item of items) {
    if (!item?.id) continue;
    if (!deduped.has(item.id)) {
      deduped.set(item.id, item);
    }
  }
  return Array.from(deduped.values()).slice(0, limit);
}

function getBacktestSummary(
  run?: BacktestRun | BacktestCompareRun | null,
): Record<string, unknown> {
  if (!run) return {};
  if ("summary" in run && run.summary && typeof run.summary === "object") {
    return run.summary as Record<string, unknown>;
  }
  return ((run as BacktestRun).result?.summary ?? {}) as Record<
    string,
    unknown
  >;
}

function getBacktestModeLabel(run?: BacktestRun | BacktestCompareRun | null) {
  const summary = getBacktestSummary(run);
  const requestConfig =
    summary.request_config && typeof summary.request_config === "object"
      ? (summary.request_config as Record<string, unknown>)
      : {};
  const mode = String(
    summary.backtest_mode ||
      requestConfig.backtest_mode ||
      ((run as BacktestRun | undefined)?.frequency === "daily_minute"
        ? "daily_select_intraday_trade"
        : "daily_only"),
  );
  const mapping: Record<string, string> = {
    daily_only: "全日 K 回测",
    minute_only: "全分钟 K 回测",
    daily_select_intraday_trade: "日线选股 + 分时买卖",
  };
  return mapping[mode] || mode;
}

function getBacktestDisplayName(
  run: BacktestRun | BacktestCompareRun,
  strategyNameMap: Record<string, string>,
) {
  const summary = getBacktestSummary(run);
  const named =
    typeof summary.strategy_name === "string"
      ? summary.strategy_name.trim()
      : "";
  if (named) return named;
  const strategyNamed = strategyNameMap[run.strategy_id];
  if (strategyNamed) return strategyNamed;
  return `策略 ${run.strategy_id.slice(0, 8)}`;
}

function getBacktestVersionHint(run: BacktestRun | BacktestCompareRun) {
  if (!run.strategy_version_id) return "当前版本";
  return `版本 ${run.strategy_version_id.slice(0, 8)}`;
}

function formatBacktestRangeDate(value?: string | null) {
  if (!value) return "--";
  return value.slice(0, 10);
}

function getBacktestRecordTitle(
  run: BacktestRun | BacktestCompareRun,
  strategyNameMap: Record<string, string>,
) {
  const baseName = getBacktestDisplayName(run, strategyNameMap);
  return `${baseName} · ${getBacktestModeLabel(run)}`;
}

function getBacktestDateRange(run: BacktestRun | BacktestCompareRun) {
  if ("start_date" in run && "end_date" in run) {
    return `${formatBacktestRangeDate(run.start_date)} ~ ${formatBacktestRangeDate(run.end_date)}`;
  }
  const summary = getBacktestSummary(run);
  const requestConfig =
    summary.request_config && typeof summary.request_config === "object"
      ? (summary.request_config as Record<string, unknown>)
      : {};
  const startDate =
    typeof requestConfig.start_date === "string"
      ? requestConfig.start_date
      : "";
  const endDate =
    typeof requestConfig.end_date === "string" ? requestConfig.end_date : "";
  if (startDate && endDate) {
    return `${formatBacktestRangeDate(startDate)} ~ ${formatBacktestRangeDate(endDate)}`;
  }
  return "区间待确认";
}

function getBacktestRecordMeta(run: BacktestRun | BacktestCompareRun) {
  return `${getBacktestVersionHint(run)} · ${getBacktestDateRange(run)}`;
}

export default function Backtest() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const streamAbortRef = useRef<AbortController | null>(null);
  const [strategies, setStrategies] = useState<StrategyDefinition[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState(
    searchParams.get("strategy_id") || "",
  );
  const [running, setRunning] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [run, setRun] = useState<BacktestRun | null>(null);
  const [recentRuns, setRecentRuns] = useState<BacktestRun[]>([]);
  const [allRuns, setAllRuns] = useState<BacktestRun[]>([]);
  const [compareRunIds, setCompareRunIds] = useState<string[]>([]);
  const [historyScope, setHistoryScope] = useState<"current" | "all">(
    "current",
  );
  const [setupExpanded, setSetupExpanded] = useState(false);
  const [compareResult, setCompareResult] =
    useState<BacktestCompareResponse | null>(null);
  const [equity, setEquity] = useState<BacktestEquityPoint[]>([]);
  const [trades, setTrades] = useState<BacktestTradeRecord[]>([]);
  const [watchlists, setWatchlists] = useState<BacktestWatchlistItem[]>([]);
  const [minuteConfirmations, setMinuteConfirmations] = useState<
    BacktestMinuteConfirmationItem[]
  >([]);
  const [snapshots, setSnapshots] = useState<BacktestTradeSnapshot[]>([]);
  const [signals, setSignals] = useState<BacktestSignalItem[]>([]);
  const [positions, setPositions] = useState<BacktestPositionItem[]>([]);
  const [orders, setOrders] = useState<BacktestOrderItem[]>([]);
  const [statusEvents, setStatusEvents] = useState<BacktestStatusEvent[]>([]);
  const [streamConnected, setStreamConnected] = useState(false);
  const [streamMessage, setStreamMessage] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [form, setForm] = useState<BacktestFormState>({
    universe_scope: "all" as BacktestUniverseScope,
    sector_name: "",
    symbols: "",
    start_date: "2024-09-01",
    end_date: "2024-12-31",
    initial_capital: 1000000,
    commission_rate: 0.0003,
    min_commission: 5,
    stamp_duty_rate: 0.001,
    slippage_rate: 0.001,
    backtest_mode: "daily_select_intraday_trade" as BacktestUiMode,
    minute_lazy_load: true,
    minute_missing_data_policy: "skip" as "skip" | "fallback",
    benchmark: "沪深300",
  });

  useEffect(() => {
    const load = async () => {
      const [strategiesResult, recentRunsResult, allRunsResult] =
        await Promise.allSettled([
        api.getStrategyPlatformList(),
        api.listStrategyPlatformBacktests({
          strategy_id: selectedStrategy || undefined,
          limit: 8,
        }),
        api.listStrategyPlatformBacktests({
          limit: 24,
        }),
      ]);

      if (strategiesResult.status === "fulfilled") {
        const items = strategiesResult.value.strategies;
        setStrategies(items);
        setSelectedStrategy((current) => {
          if (current && items.some((item) => item.id === current))
            return current;
          return items[0]?.id || "";
        });
      } else {
        const error = strategiesResult.reason;
        console.warn("策略列表接口暂不可用", error);
        setStrategies([]);
        setSelectedStrategy((current) => current || "");
      }

      if (recentRunsResult.status === "fulfilled") {
        setRecentRuns(mergeRecentRuns(recentRunsResult.value.items));
      } else {
        console.warn("最近回测历史接口暂不可用", recentRunsResult.reason);
      }
      if (allRunsResult.status === "fulfilled") {
        setAllRuns(mergeRecentRuns(allRunsResult.value.items, 24));
      } else {
        console.warn("全量回测历史接口暂不可用", allRunsResult.reason);
      }
    };
    void load();
  }, [selectedStrategy]);

  useEffect(
    () => () => {
      streamAbortRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    setCompareRunIds([]);
    setCompareResult(null);
  }, [selectedStrategy]);

  useEffect(() => {
    setCompareRunIds([]);
    setCompareResult(null);
  }, [historyScope]);

  const rememberRecentRun = (nextRun: BacktestRun) => {
    setRecentRuns((current) => mergeRecentRuns([nextRun, ...current]));
    setAllRuns((current) => mergeRecentRuns([nextRun, ...current], 24));
  };

  const toggleCompareRun = (runId: string) => {
    setCompareRunIds((current) =>
      current.includes(runId)
        ? current.filter((item) => item !== runId)
        : [...current, runId].slice(-4),
    );
  };

  const exportFullPackage = async () => {
    if (!run) return;
    setExporting(true);
    try {
      const zip = new JSZip();
      const exportedAt = new Date().toISOString();
      zip.file(
        "meta/summary.json",
        JSON.stringify(
          {
            exported_at: exportedAt,
            strategy_id: run.strategy_id,
            run_id: run.id,
            summary,
            diagnostics,
            metrics,
          },
          null,
          2,
        ),
      );
      zip.file(
        "meta/status_events.json",
        JSON.stringify(statusEvents, null, 2),
      );
      zip.file("data/equity.json", JSON.stringify(equity, null, 2));
      zip.file("data/trades.json", JSON.stringify(trades, null, 2));
      zip.file("data/watchlists.json", JSON.stringify(watchlists, null, 2));
      zip.file(
        "data/minute_confirmations.json",
        JSON.stringify(minuteConfirmations, null, 2),
      );
      zip.file("data/trade_snapshots.json", JSON.stringify(snapshots, null, 2));
      zip.file("data/signals.json", JSON.stringify(signals, null, 2));
      zip.file("data/positions.json", JSON.stringify(positions, null, 2));
      zip.file("data/orders.json", JSON.stringify(orders, null, 2));
      const blob = await zip.generateAsync({ type: "blob" });
      downloadBlob(
        `回测完整结果_${run.strategy_id}_${form.start_date}_${form.end_date}.zip`,
        blob,
      );
    } finally {
      setExporting(false);
    }
  };

  const resetDetailStates = () => {
    setTrades([]);
    setWatchlists([]);
    setMinuteConfirmations([]);
    setSnapshots([]);
    setSignals([]);
    setPositions([]);
    setOrders([]);
  };

  const appendStatusEvent = (event: BacktestStatusEvent) => {
    setStreamMessage(event.message ?? null);
    setStatusEvents((current) => {
      const eventKey = event.sequence
        ? `${event.run_id}_${event.sequence}`
        : `${event.run_id}_${event.event}_${event.status}_${event.progress}_${event.updated_at ?? event.timestamp ?? ""}`;
      const exists = current.some((item) => {
        const itemKey = item.sequence
          ? `${item.run_id}_${item.sequence}`
          : `${item.run_id}_${item.event}_${item.status}_${item.progress}_${item.updated_at ?? item.timestamp ?? ""}`;
        return itemKey === eventKey;
      });
      if (exists) return current;
      return [event, ...current].slice(0, 60);
    });
    setRun((current) => {
      if (!current || current.id !== event.run_id) return current;
      return {
        ...current,
        status: event.status,
        progress: event.progress,
        error_message: event.error_message ?? current.error_message,
        completed_at: event.completed_at ?? current.completed_at,
      };
    });
  };

  const loadBacktestDetails = async (targetRun: BacktestRun) => {
    setRun(targetRun);
    rememberRecentRun(targetRun);
    if (targetRun.status !== "completed") {
      setMessage(
        targetRun.status === "failed"
          ? `回测失败：${targetRun.error_message || "请查看实时状态或后端日志。"}`
          : targetRun.status === "cancelled"
            ? "回测任务已取消。"
            : "回测任务仍在执行中。",
      );
      return;
    }

    const [equityResponse, tradesResponse] = await Promise.all([
      api.getStrategyPlatformBacktestEquity(targetRun.id),
      api.getStrategyPlatformBacktestTrades(targetRun.id),
    ]);
    setEquity(equityResponse.items);
    setTrades(tradesResponse.items);

    const [
      watchlistResponse,
      minuteResponse,
      snapshotResponse,
      signalResponse,
      positionResponse,
      orderResponse,
    ] = await Promise.allSettled([
      api.getStrategyPlatformBacktestWatchlists(targetRun.id),
      api.getStrategyPlatformBacktestMinuteConfirmations(targetRun.id),
      api.getStrategyPlatformBacktestTradeSnapshots(targetRun.id),
      api.getStrategyPlatformBacktestSignals(targetRun.id),
      api.getStrategyPlatformBacktestPositions(targetRun.id),
      api.getStrategyPlatformBacktestOrders(targetRun.id),
    ]);

    if (watchlistResponse.status === "fulfilled")
      setWatchlists(watchlistResponse.value.items);
    if (minuteResponse.status === "fulfilled")
      setMinuteConfirmations(minuteResponse.value.items);
    if (snapshotResponse.status === "fulfilled")
      setSnapshots(snapshotResponse.value.items);
    if (signalResponse.status === "fulfilled")
      setSignals(signalResponse.value.items);
    if (positionResponse.status === "fulfilled")
      setPositions(positionResponse.value.items);
    if (orderResponse.status === "fulfilled")
      setOrders(orderResponse.value.items);

    setCompareRunIds((current) =>
      current.includes(targetRun.id)
        ? current
        : [targetRun.id, ...current].slice(0, 4),
    );
    const targetSummary = (targetRun.result?.summary ?? {}) as Record<
      string,
      unknown
    >;
    const targetSelectionOnlyMode = Boolean(
      targetSummary.selection_only_mode ??
      targetSummary.strategy_type === "selection",
    );
    setMessage(
      targetSelectionOnlyMode
        ? "选股回测完成：已生成候选池与筛选结果，本次不执行交易撮合，也不计算策略收益。"
        : "回测完成：已生成资金曲线、交易记录、订单、成交快照、信号和持仓明细。",
    );
  };

  const pollBacktestUntilTerminal = async (runId: string) => {
    setStreamMessage("流式连接不可用，已切换为 1 秒轮询状态。");
    for (let attempt = 0; attempt < 240; attempt += 1) {
      const latest = await api.getStrategyPlatformBacktest(runId);
      appendStatusEvent({
        run_id: latest.id,
        event: "heartbeat",
        status: latest.status,
        progress: latest.progress,
        stage: latest.status,
        message:
          latest.status === "running"
            ? "轮询中：回测仍在执行"
            : "轮询中：回测已结束",
        updated_at: new Date().toISOString(),
        error_message: latest.error_message,
        completed_at: latest.completed_at,
      });
      setRun(latest);
      if (terminalBacktestStatuses.has(latest.status)) return latest;
      await delay(1000);
    }
    return api.getStrategyPlatformBacktest(runId);
  };

  const waitForBacktestStream = async (runId: string) => {
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    setStreamConnected(false);
    try {
      const response = await api.streamStrategyPlatformBacktest(
        runId,
        controller.signal,
      );
      setStreamConnected(true);
      const reader = response.body?.getReader();
      if (!reader) return pollBacktestUntilTerminal(runId);
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const parsed = parseSseBlock(block);
          if (
            !parsed ||
            typeof parsed.data !== "object" ||
            parsed.data === null
          )
            continue;
          const event = {
            ...(parsed.data as BacktestStatusEvent),
            event: parsed.event as BacktestStatusEvent["event"],
          };
          appendStatusEvent(event);
          if (terminalBacktestStatuses.has(event.status)) {
            return api.getStrategyPlatformBacktest(runId);
          }
        }
      }
      return api.getStrategyPlatformBacktest(runId);
    } catch (error) {
      if (controller.signal.aborted) {
        return api.getStrategyPlatformBacktest(runId);
      }
      console.warn("回测流式状态连接失败，切换轮询", error);
      return pollBacktestUntilTerminal(runId);
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
      }
      setStreamConnected(false);
    }
  };

  const runBacktest = async () => {
    if (!selectedStrategy) {
      setMessage("请先选择策略。");
      return;
    }
    if (form.backtest_mode === "minute_only") {
      setMessage(
        "全分钟 K 回测真引擎尚未开放，请先使用“全日 K 回测”或“日线选股 + 分时买卖”。",
      );
      return;
    }
    const symbols = parseSymbolList(form.symbols);
    if (form.universe_scope === "symbols" && symbols.length === 0) {
      setMessage("选择“指定个股”时，请至少填写 1 个股票代码。");
      return;
    }
    if (form.universe_scope === "sector" && !form.sector_name.trim()) {
      setMessage("选择“指定板块”时，请填写板块/行业/概念名称。");
      return;
    }
    const frequency =
      form.backtest_mode === "daily_select_intraday_trade"
        ? "daily_minute"
        : "daily";
    const useMinuteConfirm =
      form.backtest_mode === "daily_select_intraday_trade";
    streamAbortRef.current?.abort();
    setRunning(true);
    setMessage(null);
    setRun(null);
    setEquity([]);
    setStatusEvents([]);
    setStreamMessage(null);
    setStreamConnected(false);
    resetDetailStates();

    try {
      const created = await api.runStrategyPlatformBacktest({
        strategy_id: selectedStrategy,
        symbols: form.universe_scope === "symbols" ? symbols : [],
        start_date: form.start_date,
        end_date: form.end_date,
        initial_capital: form.initial_capital,
        frequency,
        benchmark: form.benchmark,
        use_minute_confirm: useMinuteConfirm,
        backtest_mode: form.backtest_mode,
        universe: {
          scope: form.universe_scope,
          sector:
            form.universe_scope === "sector"
              ? form.sector_name.trim()
              : undefined,
          symbols: form.universe_scope === "symbols" ? symbols : undefined,
        },
        cost_config: {
          commission_rate: form.commission_rate,
          min_commission: form.min_commission,
          stamp_duty_rate: form.stamp_duty_rate,
          slippage_rate: form.slippage_rate,
        },
        minute_config: {
          lazy_load: form.minute_lazy_load,
          execution_granularity: useMinuteConfirm ? "minute" : "daily",
          missing_data_policy: form.minute_missing_data_policy,
        },
        walk_forward: {},
      });
      setRun(created);
      rememberRecentRun(created);
      appendStatusEvent({
        run_id: created.id,
        event: "status",
        status: created.status,
        progress: created.progress,
        stage: "created",
        message:
          created.status === "completed"
            ? "回测已完成，正在加载明细"
            : "回测任务已创建，正在连接实时状态",
        updated_at: new Date().toISOString(),
        error_message: created.error_message,
        completed_at: created.completed_at,
      });
      const finalRun = terminalBacktestStatuses.has(created.status)
        ? created
        : await waitForBacktestStream(created.id);
      if (finalRun.status === "completed") {
        rememberRecentRun(finalRun);
        navigate(`/backtest/runs/${finalRun.id}`);
        return;
      }
      await loadBacktestDetails(finalRun);
    } catch (error) {
      console.warn("回测接口暂不可用", error);
      setRun(null);
      resetDetailStates();
      setMessage(
        "回测任务创建失败，当前不再展示本地预览结果。请确认后端服务后重试。",
      );
    } finally {
      setRunning(false);
      setStreamConnected(false);
    }
  };

  const cancelCurrentRun = async () => {
    if (!run) {
      setMessage("当前没有可取消的回测任务。");
      return;
    }
    setCancelling(true);
    try {
      const cancelled = await api.cancelStrategyPlatformBacktest(run.id);
      setRun(cancelled);
      appendStatusEvent({
        run_id: cancelled.id,
        event: "status",
        status: cancelled.status,
        progress: cancelled.progress,
        stage: "cancelled",
        message:
          cancelled.status === "cancelled"
            ? "回测任务已取消"
            : "当前回测已处于终态",
        updated_at: new Date().toISOString(),
        error_message: cancelled.error_message,
        completed_at: cancelled.completed_at,
      });
      rememberRecentRun(cancelled);
      setMessage(
        cancelled.status === "cancelled"
          ? "回测任务已取消。"
          : "当前回测已处于终态，后端返回现有任务状态。",
      );
    } catch (error) {
      console.warn("取消回测接口暂不可用", error);
      setMessage("取消回测失败，请确认后端服务。");
    } finally {
      setCancelling(false);
    }
  };

  const compareSelectedRuns = async () => {
    if (compareRunIds.length < 2) {
      setMessage("请至少选择 2 个回测结果进行对比。");
      return;
    }
    if (selectionCompareBlocked) {
      setMessage(
        "当前多结果对比只支持收益型回测，选股验证结果请进入详情页逐条查看。",
      );
      return;
    }
    if (hasFormalCompareSelection) {
      setMessage(
        "当前选择里包含非真实数据或未完成回测；请只保留真实且已完成的回测再对比。",
      );
      return;
    }
    setComparing(true);
    try {
      const result = await api.compareStrategyPlatformBacktests(compareRunIds);
      setCompareResult(result);
      document
        .getElementById("compare")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
      setMessage(`已完成 ${result.runs.length} 组回测结果对比。`);
    } catch (error) {
      console.warn("回测对比接口暂不可用", error);
      setMessage(
        "回测对比失败，当前不再使用本地回退结果。请确认后端服务后重试。",
      );
    } finally {
      setComparing(false);
    }
  };

  const metrics = run?.metrics;
  const summary = (run?.result?.summary ?? {}) as Record<string, unknown>;
  const diagnostics = (run?.result?.diagnostics ?? {}) as Record<
    string,
    unknown
  >;
  const strategyType = String(summary.strategy_type ?? "");
  const selectionOnlyMode = Boolean(
    summary.selection_only_mode ??
    diagnostics.selection_only_mode ??
    strategyType === "selection",
  );
  const watchlistDays = Number(summary.watchlist_days ?? 0);
  const confirmHitRate = Number(diagnostics.confirm_hit_rate ?? 0);
  const minuteDataMissing = Number(diagnostics.minute_data_missing ?? 0);
  const fallbackMode = Boolean(diagnostics.fallback_mode ?? false);
  const truthLevel = classifyBacktestTruth(run);
  const truthLabel = getBacktestTruthLabel(truthLevel);
  const truthTone = getBacktestTruthTone(truthLevel);
  const currentDataSource = getBacktestDataSourceText(run);
  const currentRunIsTerminal = run
    ? ["completed", "failed", "cancelled"].includes(run.status)
    : true;
  const latestStatusEvent = statusEvents[0];
  const liveProgress = Math.round(
    ((latestStatusEvent?.progress ?? run?.progress ?? 0) || 0) * 100,
  );
  const liveStatus = latestStatusEvent?.status ?? run?.status;
  const currentStrategyRuns = recentRuns.filter((item) =>
    selectedStrategy ? item.strategy_id === selectedStrategy : true,
  );
  const visibleRecentRuns =
    historyScope === "all" ? allRuns : currentStrategyRuns;
  const selectedCompareRuns = visibleRecentRuns.filter((item) =>
    compareRunIds.includes(item.id),
  );
  const strategyNameMap = useMemo(
    () =>
      Object.fromEntries(
        strategies.map((strategy) => [strategy.id, strategy.name]),
      ),
    [strategies],
  );
  const selectedStrategyDef = strategies.find(
    (strategy) => strategy.id === selectedStrategy,
  );
  const selectedStrategyType =
    selectedStrategyDef?.strategy_type ?? "portfolio";
  useEffect(() => {
    if (!selectedStrategyDef) return;
    setForm((current) => {
      if (selectedStrategyDef.strategy_type === "selection") {
        return current.backtest_mode === "daily_only"
          ? current
          : { ...current, backtest_mode: "daily_only" };
      }
      if (current.backtest_mode !== "daily_only") return current;
      return { ...current, backtest_mode: "daily_select_intraday_trade" };
    });
  }, [selectedStrategyDef]);
  const useMinuteMode = form.backtest_mode === "daily_select_intraday_trade";
  const supportsMinuteAdvanced =
    selectedStrategyType === "trading" || selectedStrategyType === "portfolio";
  const strategyFocusTags = getStrategyFocusTags(selectedStrategyType);
  const selectionWorkbench = selectedStrategyType === "selection";
  const primaryActionLabel = selectionWorkbench ? "开始验证" : "开始回测";
  const detailActionLabel = selectionWorkbench
    ? "打开验证详情"
    : "打开结果详情";
  const workspaceTitle = selectionWorkbench
    ? "策略验证工作台"
    : "策略回测工作台";
  const setupTitle = selectionWorkbench ? "验证配置" : "回测配置";
  const recentSectionTitle = selectionWorkbench
    ? "当前策略最近验证记录"
    : "当前策略最近回测与对比";
  const selectionCompareBlocked = compareRunIds.some((runId) => {
    const item = visibleRecentRuns.find((candidate) => candidate.id === runId);
    return item ? isSelectionValidationRun(item) : false;
  });
  const hasFormalCompareSelection = compareRunIds.some((runId) => {
    const item = visibleRecentRuns.find((candidate) => candidate.id === runId);
    return item ? !isFormalCompareEligible(item) : true;
  });
  const chainStatusText = run
    ? selectionOnlyMode
      ? "当前为选股验证，只展示候选池与筛选链路，不解释收益表现。"
      : truthLevel === "real"
        ? `当前回测走真实链路，数据来源：${currentDataSource}，分钟缺失数：${minuteDataMissing}。`
        : `当前结果仅适合流程验证，数据来源：${currentDataSource}，分钟缺失数：${minuteDataMissing}。`
    : "先发起一次回测，系统会在这里展示链路可信度与数据来源。";
  const resultFocusRun =
    (run?.status === "completed" ? run : null) ??
    visibleRecentRuns.find((item) => item.status === "completed") ??
    run ??
    visibleRecentRuns[0] ??
    null;
  const resultFocusSummary = getBacktestSummary(resultFocusRun);
  const resultFocusIsSelection = isSelectionValidationRun(resultFocusRun);
  const resultFocusTitle = resultFocusRun
    ? getBacktestRecordTitle(resultFocusRun, strategyNameMap)
    : selectionWorkbench
      ? "还没有选股结果"
      : "还没有回测结果";
  const resultFocusSubtitle = resultFocusRun
    ? `${getBacktestRecordMeta(resultFocusRun)} · 完成时间 ${formatDateTime(resultFocusRun.completed_at || resultFocusRun.created_at)}`
    : selectionWorkbench
      ? "选择策略和扫描范围后开始验证，完成后进入候选池详情。"
      : "选择策略并运行一次回测后，核心结果会在这里聚焦展示。";
  const resultFocusActionLabel = resultFocusIsSelection
    ? "查看选股结果"
    : "查看回测结果";

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-5 dark:bg-slate-950 sm:p-6">
      <div className="mb-5 flex flex-col gap-4 border-b border-slate-200 pb-5 dark:border-slate-800 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-lg bg-blue-50 px-3 py-1 text-xs font-medium text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">
            <ChartBarIcon className="h-4 w-4" />
            结果优先工作台
          </div>
          <h1 className="mt-3 text-2xl font-bold text-slate-900 dark:text-slate-100">
            {workspaceTitle}
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {selectionWorkbench
              ? "先验证选股候选池，再进入结果详情查看入选股票、排名和确认链路。"
              : "发起回测后优先看结果、历史和对比，参数配置保持在右侧。"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => run && navigate(`/backtest/runs/${run.id}`)}
            disabled={!run}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 shadow-sm disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <ChartBarIcon className="h-4 w-4" />
            {detailActionLabel}
          </button>
          <button
            onClick={cancelCurrentRun}
            disabled={!run || cancelling || currentRunIsTerminal}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-700 shadow-sm disabled:opacity-50 dark:border-amber-800 dark:bg-amber-500/10 dark:text-amber-200"
          >
            {cancelling ? (
              <ArrowPathIcon className="h-4 w-4 animate-spin" />
            ) : (
              <ShieldCheckIcon className="h-4 w-4" />
            )}
            {cancelling ? "取消中..." : "取消当前任务"}
          </button>
          <button
            onClick={exportFullPackage}
            disabled={!run || exporting}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 shadow-sm disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <ArrowDownTrayIcon className="h-4 w-4" />
            {exporting ? "打包导出中..." : "导出完整结果"}
          </button>
          <button
            onClick={runBacktest}
            disabled={running || !selectedStrategy}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-sm disabled:opacity-60"
          >
            {running ? (
              <ArrowPathIcon className="h-4 w-4 animate-spin" />
            ) : (
              <PlayIcon className="h-4 w-4" />
            )}
            {running ? "运行中..." : primaryActionLabel}
          </button>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="order-2 space-y-4 xl:order-2">
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {setupTitle}
            </h2>
            <div className="mt-4 space-y-4">
              <CompactBacktestSetup
                strategies={strategies}
                selectedStrategy={selectedStrategy}
                setSelectedStrategy={setSelectedStrategy}
                selectedStrategyType={selectedStrategyType}
                form={form}
                setForm={setForm}
                selectionWorkbench={selectionWorkbench}
                running={running}
                primaryActionLabel={primaryActionLabel}
                onRun={runBacktest}
              />
              <button
                type="button"
                onClick={() => setSetupExpanded((current) => !current)}
                className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 dark:border-slate-700 dark:text-slate-300"
              >
                <span>{setupExpanded ? "收起完整参数" : "展开完整参数"}</span>
                {setupExpanded ? (
                  <ChevronDownIcon className="h-4 w-4" />
                ) : (
                  <ChevronRightIcon className="h-4 w-4" />
                )}
              </button>
              {setupExpanded && (
                <div className="space-y-4 border-t border-slate-100 pt-4 dark:border-slate-800">
              <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-950">
                <label className="block">
                  <span className="text-sm text-slate-500">策略版本</span>
                  <select
                    value={selectedStrategy}
                    onChange={(event) =>
                      setSelectedStrategy(event.target.value)
                    }
                    className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  >
                    {strategies.map((strategy) => (
                      <option key={strategy.id} value={strategy.id}>
                        {strategy.name} · 第 {strategy.version} 版
                      </option>
                    ))}
                  </select>
                </label>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">
                    {toChineseStrategyType(selectedStrategyType)}
                  </span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {getStrategyTypeHint(selectedStrategyType)}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {strategyFocusTags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] text-slate-500 dark:border-slate-700 dark:text-slate-300"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>

              <div className="space-y-3 rounded-lg border border-slate-100 p-4 dark:border-slate-800">
                <div>
                  <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                    {selectedStrategyType === "risk"
                      ? "风控作用范围"
                      : "股票池 / 候选范围"}
                  </h3>
                  <p className="mt-1 text-xs text-slate-400">
                    {selectedStrategyType === "selection"
                      ? "选股策略先定义扫描范围，再交给策略 DSL 进行候选筛选。"
                      : selectedStrategyType === "risk"
                        ? "风控策略会将这里视为风险规则验证范围。"
                        : "这里决定回测扫描的股票范围，具体信号逻辑仍由策略 DSL 决定。"}
                  </p>
                </div>
                <label className="block">
                  <span className="text-sm text-slate-500">扫描范围</span>
                  <select
                    value={form.universe_scope}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        universe_scope: event.target
                          .value as BacktestUniverseScope,
                      })
                    }
                    className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  >
                    <option value="all">
                      全部 A 股（默认，全市场日 K 扫描）
                    </option>
                    <option value="beijing">北交所</option>
                    <option value="chinext">创业板</option>
                    <option value="main_board">主板</option>
                    <option value="sector">指定板块 / 行业 / 概念</option>
                    <option value="symbols">指定个股</option>
                  </select>
                </label>
                {form.universe_scope === "sector" && (
                  <TextInput
                    label="板块 / 行业 / 概念名称"
                    value={form.sector_name}
                    onChange={(value) =>
                      setForm({ ...form, sector_name: value })
                    }
                  />
                )}
                {form.universe_scope === "symbols" && (
                  <>
                    <TextInput
                      label="指定个股代码"
                      value={form.symbols}
                      onChange={(value) => setForm({ ...form, symbols: value })}
                    />
                    <p className="-mt-2 text-xs text-slate-400">
                      支持逗号、空格或换行分隔，例如：300750.SZ, 300520.SZ。
                    </p>
                  </>
                )}
                {form.universe_scope !== "symbols" && (
                  <p className="text-xs text-slate-400">
                    不填个股时，后端会读取当前日期范围内全部可用 A 股日
                    K，再按策略 DSL 和扫描范围筛选候选池。
                  </p>
                )}
              </div>

              <div className="space-y-3 rounded-lg border border-slate-100 p-4 dark:border-slate-800">
                <div>
                  <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                    资金、周期与成本
                  </h3>
                  <p className="mt-1 text-xs text-slate-400">
                    {selectedStrategyType === "selection"
                      ? "选股策略也保留资金与成本参数，便于切换到交易型验证模式时直接复用。"
                      : selectedStrategyType === "risk"
                        ? "风控策略回测时，资金规模和成本参数会直接影响风险暴露与回撤表现。"
                        : "这些参数决定回测成本、资金规模和结果可比性。"}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <TextInput
                    label="开始日期"
                    type="date"
                    value={form.start_date}
                    onChange={(value) =>
                      setForm({ ...form, start_date: value })
                    }
                  />
                  <TextInput
                    label="结束日期"
                    type="date"
                    value={form.end_date}
                    onChange={(value) => setForm({ ...form, end_date: value })}
                  />
                </div>
                <TextInput
                  label={getCapitalLabel(selectedStrategyType)}
                  type="number"
                  value={String(form.initial_capital)}
                  onChange={(value) =>
                    setForm({ ...form, initial_capital: Number(value) })
                  }
                />
                <TextInput
                  label="基准指数"
                  value={form.benchmark}
                  onChange={(value) => setForm({ ...form, benchmark: value })}
                />
                <div className="grid grid-cols-2 gap-3">
                  <TextInput
                    label="佣金率"
                    type="number"
                    value={String(form.commission_rate)}
                    onChange={(value) =>
                      setForm({ ...form, commission_rate: Number(value) })
                    }
                  />
                  <TextInput
                    label="最低佣金"
                    type="number"
                    value={String(form.min_commission)}
                    onChange={(value) =>
                      setForm({ ...form, min_commission: Number(value) })
                    }
                  />
                  <TextInput
                    label="印花税率"
                    type="number"
                    value={String(form.stamp_duty_rate)}
                    onChange={(value) =>
                      setForm({ ...form, stamp_duty_rate: Number(value) })
                    }
                  />
                  <TextInput
                    label="滑点率"
                    type="number"
                    value={String(form.slippage_rate)}
                    onChange={(value) =>
                      setForm({ ...form, slippage_rate: Number(value) })
                    }
                  />
                </div>
              </div>

              <div className="space-y-3 rounded-lg border border-slate-100 p-4 dark:border-slate-800">
                <div>
                  <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                    回测模式
                  </h3>
                  <p className="mt-1 text-xs text-slate-400">
                    {getModeHint(selectedStrategyType, useMinuteMode)}
                  </p>
                </div>
                <label className="block">
                  <span className="text-sm text-slate-500">执行方式</span>
                  <select
                    value={form.backtest_mode}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        backtest_mode: event.target.value as BacktestUiMode,
                      })
                    }
                    className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  >
                    <option value="daily_only">全日 K 回测</option>
                    <option value="daily_select_intraday_trade">
                      日线选股 + 分时买卖
                    </option>
                    <option value="minute_only" disabled>
                      全分钟 K 回测（真引擎即将支持）
                    </option>
                  </select>
                </label>
                {useMinuteMode ? (
                  <div className="space-y-3">
                    <div className="rounded-xl bg-blue-50 p-3 text-sm text-blue-700 dark:bg-blue-500/10 dark:text-blue-200">
                      <label className="flex items-center justify-between gap-3">
                        <span>
                          分钟懒加载：只读取候选股票在候选交易日的 1 分钟
                          K，避免把多年全市场分钟线一次性塞进内存。
                        </span>
                        <input
                          type="checkbox"
                          checked={form.minute_lazy_load}
                          onChange={(event) =>
                            setForm({
                              ...form,
                              minute_lazy_load: event.target.checked,
                            })
                          }
                        />
                      </label>
                      <p className="mt-2 text-xs text-blue-600/80 dark:text-blue-200/80">
                        5m / 15m / 30m 等多周期规则由策略 DSL
                        定义，回测页只决定是否启用分钟执行层。
                      </p>
                    </div>
                    {supportsMinuteAdvanced && (
                      <details
                        className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-950"
                        open
                      >
                        <summary className="cursor-pointer list-none font-medium text-slate-700 dark:text-slate-200">
                          高级分钟执行设置
                        </summary>
                        <div className="mt-3 space-y-3">
                          <label className="block">
                            <span className="text-sm text-slate-500">
                              分钟数据缺失处理
                            </span>
                            <select
                              value={form.minute_missing_data_policy}
                              onChange={(event) =>
                                setForm({
                                  ...form,
                                  minute_missing_data_policy: event.target
                                    .value as "skip" | "fallback",
                                })
                              }
                              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                            >
                              <option value="skip">跳过当日分钟确认</option>
                              <option value="fallback">回退到日线逻辑</option>
                            </select>
                          </label>
                          <div className="rounded-xl bg-slate-100 px-3 py-2 text-xs text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                            多周期分时条件仍由策略 DSL
                            决定；这里仅配置分钟层执行边界、缺失数据处理与加载方式。
                          </div>
                        </div>
                      </details>
                    )}
                  </div>
                ) : (
                  <div className="rounded-xl bg-slate-50 p-3 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                    当前仅扫描日
                    K，不读取分钟线，适合选股策略候选池验证和中低频交易策略。
                  </div>
                )}
              </div>
                </div>
              )}
            </div>
            {message && (
            <div className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">
                {message}
              </div>
            )}
          </div>

          {(run || statusEvents.length > 0 || running) && (
            <div className="rounded-lg border border-blue-100 bg-white p-4 shadow-sm dark:border-blue-900/60 dark:bg-slate-900">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                    实时回测状态
                  </h2>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {streamMessage ||
                      latestStatusEvent?.message ||
                      "等待回测状态推送"}
                  </p>
                </div>
                <span
                  className={`rounded-full px-2 py-1 text-xs font-semibold ${streamConnected ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300" : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300"}`}
                >
                  {streamConnected
                    ? "实时连接中"
                    : running
                      ? "连接准备中"
                      : "未连接"}
                </span>
              </div>
              <div className="mt-4">
                <div className="mb-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                  <span>{toChineseBacktestStatus(liveStatus)}</span>
                  <span>{liveProgress}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div
                    className="h-full rounded-full bg-blue-600 transition-all duration-500"
                    style={{
                      width: `${Math.min(100, Math.max(0, liveProgress))}%`,
                    }}
                  />
                </div>
              </div>
              <div className="mt-4 max-h-64 space-y-2 overflow-y-auto pr-1">
                {statusEvents.length === 0 ? (
                  <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                    {selectionWorkbench
                      ? "开始验证后，这里会实时显示排队、编译、准备数据、执行引擎和写入结果等阶段。"
                      : "开始回测后，这里会实时显示排队、编译、准备数据、执行引擎和写入结果等阶段。"}
                  </div>
                ) : (
                  statusEvents.map((item, index) => (
                    <div
                      key={`${item.run_id}_${item.sequence ?? index}_${item.updated_at ?? item.timestamp ?? index}`}
                      className="rounded-lg border border-slate-100 p-3 dark:border-slate-800"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-medium text-slate-800 dark:text-slate-100">
                          {toChineseBacktestStage(item.stage)}
                        </div>
                        <div className="text-xs text-slate-400">
                          {Math.round((item.progress || 0) * 100)}%
                        </div>
                      </div>
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {item.message || toChineseBacktestStatus(item.status)}
                      </div>
                      <div className="mt-1 text-[11px] text-slate-400">
                        {formatDateTime(item.updated_at || item.timestamp)}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="flex flex-col gap-3">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
                  <ClockIcon className="h-5 w-5 text-blue-500" />
                  历史回测记录
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {historyScope === "current"
                    ? recentSectionTitle
                    : "全部策略最近回测与验证记录"}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setHistoryScope("current")}
                  className={`rounded-lg px-3 py-2 text-sm font-medium ${historyScope === "current" ? "bg-blue-600 text-white" : "border border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300"}`}
                >
                  当前策略
                </button>
                <button
                  type="button"
                  onClick={() => setHistoryScope("all")}
                  className={`rounded-lg px-3 py-2 text-sm font-medium ${historyScope === "all" ? "bg-blue-600 text-white" : "border border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300"}`}
                >
                  全部历史
                </button>
                <button
                  onClick={compareSelectedRuns}
                  disabled={
                    comparing ||
                    compareRunIds.length < 2 ||
                    hasFormalCompareSelection
                  }
                  className="ml-auto rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
                >
                  {comparing
                    ? "对比中..."
                    : `开始对比（${compareRunIds.length}）`}
                </button>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              {visibleRecentRuns.length === 0 ? (
                <div className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  {selectionWorkbench
                    ? "当前策略完成一次验证后，这里会沉淀最近记录。"
                    : "当前策略完成一次回测后，这里会沉淀最近结果。"}
                </div>
              ) : (
                visibleRecentRuns.map((item) => (
                  <label
                    key={item.id}
                    className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
                  >
                    <input
                      type="checkbox"
                      checked={compareRunIds.includes(item.id)}
                      onChange={() => toggleCompareRun(item.id)}
                      disabled={!isFormalCompareEligible(item)}
                      className="mt-1"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-slate-900 dark:text-slate-100">
                          {getBacktestRecordTitle(item, strategyNameMap)}
                        </span>
                        <span
                          className={`rounded-full px-2 py-1 text-xs font-semibold ${item.status === "completed" ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300" : item.status === "cancelled" ? "bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}
                        >
                          {toChineseBacktestStatus(item.status)}
                        </span>
                        <span
                          className={`rounded-full px-2 py-1 text-xs font-semibold ${getBacktestTruthTone(classifyBacktestTruth(item))}`}
                        >
                          {getBacktestTruthLabel(classifyBacktestTruth(item))}
                        </span>
                      </div>
                      <div className="mt-1 text-xs text-slate-400">
                        {getBacktestRecordMeta(item)}
                      </div>
                      <div className="mt-1 text-xs text-slate-400">
                        完成时间：
                        {formatDateTime(item.completed_at || item.created_at)}
                      </div>
                      <div className="mt-1 text-xs text-slate-400">
                        数据来源：{getBacktestDataSourceText(item)}
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                        <div className="rounded-lg bg-slate-50 px-2 py-1 text-slate-600 dark:bg-slate-950 dark:text-slate-300">
                          收益率 {formatPercent(item.metrics?.total_return)}
                        </div>
                        <div className="rounded-lg bg-slate-50 px-2 py-1 text-slate-600 dark:bg-slate-950 dark:text-slate-300">
                          夏普 {item.metrics?.sharpe_ratio?.toFixed(2) ?? "--"}
                        </div>
                      </div>
                      {!isFormalCompareEligible(item) && (
                        <div className="mt-2 text-xs text-amber-600 dark:text-amber-300">
                          {isSelectionValidationRun(item)
                            ? "当前记录属于选股验证，不参与收益型多结果对比。"
                            : "当前结果不参与正式对比；仅支持已完成且数据来源为真实数据的回测。"}
                        </div>
                      )}
                      <div className="mt-3">
                        <button
                          type="button"
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            navigate(`/backtest/runs/${item.id}`);
                          }}
                          className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-300"
                        >
                          {isSelectionValidationRun(item)
                            ? "查看选股结果"
                            : "查看回测结果"}
                        </button>
                      </div>
                    </div>
                  </label>
                ))
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
              <span>
                已选 {selectedCompareRuns.length} 组，最多支持 4 组同时对比。
              </span>
              <button
                onClick={() => setCompareRunIds([])}
                className="rounded-lg border border-slate-200 px-2 py-1 text-slate-500 dark:border-slate-700 dark:text-slate-300"
              >
                清空选择
              </button>
            </div>
            <div className="mt-3 text-xs text-slate-400">
              对比只接受真实数据且已完成的回测；回退链路、Synthetic
              数据、失败任务不会进入正式对比。
            </div>
          </div>

        </section>

        <section className="order-1 space-y-5 xl:order-1">
          <div className="rounded-lg border border-blue-100 bg-white p-5 shadow-sm dark:border-blue-900/60 dark:bg-slate-900">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-lg bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">
                    {selectionWorkbench ? "选股结果" : "回测结果"}
                  </span>
                  {resultFocusRun && (
                    <span
                      className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${getBacktestTruthTone(classifyBacktestTruth(resultFocusRun))}`}
                    >
                      {getBacktestTruthLabel(classifyBacktestTruth(resultFocusRun))}
                    </span>
                  )}
                </div>
                <h2 className="mt-3 text-xl font-semibold text-slate-900 dark:text-slate-100">
                  {resultFocusTitle}
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {resultFocusSubtitle}
                </p>
              </div>
              <button
                onClick={() =>
                  resultFocusRun && navigate(`/backtest/runs/${resultFocusRun.id}`)
                }
                disabled={!resultFocusRun}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm disabled:opacity-50"
              >
                <ChartBarIcon className="h-4 w-4" />
                {resultFocusActionLabel}
              </button>
            </div>
            <div className="mt-5 grid gap-3 md:grid-cols-3">
              <ResultFact
                label={selectionWorkbench ? "候选池天数" : "总收益率"}
                value={
                  selectionWorkbench
                    ? String(
                        (resultFocusSummary.watchlist_days ?? watchlistDays) ||
                          "--",
                      )
                    : formatPercent(resultFocusRun?.metrics?.total_return)
                }
              />
              <ResultFact
                label="任务状态"
                value={toChineseBacktestStatus(resultFocusRun?.status)}
              />
              <ResultFact
                label={selectionWorkbench ? "数据来源" : "最大回撤"}
                value={
                  selectionWorkbench
                    ? getBacktestDataSourceText(resultFocusRun)
                    : formatPercent(resultFocusRun?.metrics?.max_drawdown)
                }
              />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-5">
            <Metric
              title="任务状态"
              value={toChineseBacktestStatus(run?.status)}
              tone="blue"
            />
            <Metric
              title="运行进度"
              value={`${Math.round((run?.progress ?? 0) * 100)}%`}
              tone="blue"
            />
            <Metric
              title="数据来源"
              value={truthLabel}
              tone={truthLevel === "real" ? "emerald" : "amber"}
            />
            <Metric
              title="候选池天数"
              value={String(watchlistDays || "--")}
              tone="amber"
            />
            <Metric
              title="分钟确认命中率"
              value={watchlistDays ? formatPercent(confirmHitRate) : "--"}
              tone="rose"
            />
          </div>

          {run && (
            <div
              className={`rounded-2xl border px-4 py-3 text-sm shadow-sm ${truthTone}`}
            >
              <div className="font-semibold">数据来源：{truthLabel}</div>
              <div className="mt-1">
                原始标识：{currentDataSource}。
                {truthLevel === "real"
                  ? " 当前结果可作为正式回测继续分析。"
                  : " 当前结果仅适合做链路/流程验证，不应直接用于正式收益比较。"}
              </div>
            </div>
          )}

          <div
            className={`rounded-2xl border px-4 py-3 text-sm shadow-sm ${fallbackMode ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-500/10 dark:text-amber-200" : "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-200"}`}
          >
            <div className="font-semibold">链路状态</div>
            <div className="mt-1">{chainStatusText}</div>
          </div>

          <div
            id="compare"
            className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  {selectionWorkbench ? "多结果对比" : "多回测对比"}
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {selectionWorkbench
                    ? "选股验证以单次链路分析为主；收益型对比仍保留在同一入口。"
                    : "工作台保留对比入口，详细单次结果已移动到结果详情页。"}
                </p>
              </div>
              {compareResult && (
                <div className="text-sm text-slate-500 dark:text-slate-400">
                  当前对比：{compareResult.runs.length} 组
                </div>
              )}
            </div>
            {!compareResult ? (
              <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                {selectionWorkbench
                  ? "当前工作台以验证记录查看为主；多结果对比仅对收益型回测开放。"
                  : "从左侧“当前策略最近回测与对比”勾选至少两组回测后，点击“开始对比”生成对比摘要。"}
              </div>
            ) : (
              <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {(
                  [
                    {
                      key: "total_return",
                      label: "总收益率",
                      format: "percent",
                    },
                    {
                      key: "annual_return",
                      label: "年化收益",
                      format: "percent",
                    },
                    {
                      key: "sharpe_ratio",
                      label: "夏普比率",
                      format: "number",
                    },
                    {
                      key: "max_drawdown",
                      label: "最大回撤",
                      format: "percent",
                    },
                    { key: "win_rate", label: "胜率", format: "percent" },
                    { key: "volatility", label: "波动率", format: "percent" },
                  ] as const
                ).map((metric) => (
                  <CompareMetricCard
                    key={metric.key}
                    title={metric.label}
                    metricKey={metric.key}
                    format={metric.format}
                    runs={compareResult.runs}
                    summary={compareResult.summary[metric.key]}
                    strategyNameMap={strategyNameMap}
                  />
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function CompactBacktestSetup({
  strategies,
  selectedStrategy,
  setSelectedStrategy,
  selectedStrategyType,
  form,
  setForm,
  selectionWorkbench,
  running,
  primaryActionLabel,
  onRun,
}: {
  strategies: StrategyDefinition[];
  selectedStrategy: string;
  setSelectedStrategy: (value: string) => void;
  selectedStrategyType: StrategyPlatformType | string;
  form: BacktestFormState;
  setForm: Dispatch<SetStateAction<BacktestFormState>>;
  selectionWorkbench: boolean;
  running: boolean;
  primaryActionLabel: string;
  onRun: () => void;
}) {
  const modeOptions: Array<{ value: BacktestUiMode; label: string }> =
    selectionWorkbench
      ? [
          { value: "daily_only", label: "选股验证" },
          { value: "daily_select_intraday_trade", label: "选股 + 分时" },
        ]
      : [
          { value: "daily_select_intraday_trade", label: "日线 + 分时" },
          { value: "daily_only", label: "全日 K" },
        ];

  return (
    <div className="space-y-4">
      <label className="block">
        <span className="text-sm text-slate-500">策略</span>
        <select
          value={selectedStrategy}
          onChange={(event) => setSelectedStrategy(event.target.value)}
          className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        >
          {strategies.map((strategy) => (
            <option key={strategy.id} value={strategy.id}>
              {strategy.name} · 第 {strategy.version} 版
            </option>
          ))}
        </select>
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-lg bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">
          {toChineseStrategyType(selectedStrategyType)}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {selectionWorkbench ? "候选池优先" : "收益与风控优先"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <TextInput
          label="开始日期"
          type="date"
          value={form.start_date}
          onChange={(value) =>
            setForm((current) => ({ ...current, start_date: value }))
          }
        />
        <TextInput
          label="结束日期"
          type="date"
          value={form.end_date}
          onChange={(value) =>
            setForm((current) => ({ ...current, end_date: value }))
          }
        />
      </div>

      <label className="block">
        <span className="text-sm text-slate-500">扫描范围</span>
        <select
          value={form.universe_scope}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              universe_scope: event.target.value as BacktestUniverseScope,
            }))
          }
          className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        >
          <option value="all">全部 A 股</option>
          <option value="beijing">北交所</option>
          <option value="chinext">创业板</option>
          <option value="main_board">主板</option>
          <option value="sector">指定板块 / 行业 / 概念</option>
          <option value="symbols">指定个股</option>
        </select>
      </label>

      {form.universe_scope === "sector" && (
        <TextInput
          label="板块 / 行业 / 概念名称"
          value={form.sector_name}
          onChange={(value) =>
            setForm((current) => ({ ...current, sector_name: value }))
          }
        />
      )}
      {form.universe_scope === "symbols" && (
        <TextInput
          label="指定个股代码"
          value={form.symbols}
          onChange={(value) =>
            setForm((current) => ({ ...current, symbols: value }))
          }
        />
      )}

      <div className="grid grid-cols-2 gap-2">
        {modeOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() =>
              setForm((current) => ({
                ...current,
                backtest_mode: option.value,
              }))
            }
            className={`rounded-lg border px-3 py-2 text-sm font-medium ${form.backtest_mode === option.value ? "border-blue-500 bg-blue-50 text-blue-700 dark:border-blue-400 dark:bg-blue-500/10 dark:text-blue-200" : "border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300"}`}
          >
            {option.label}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={onRun}
        disabled={running || !selectedStrategy}
        className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm disabled:opacity-60"
      >
        {running ? (
          <ArrowPathIcon className="h-4 w-4 animate-spin" />
        ) : (
          <PlayIcon className="h-4 w-4" />
        )}
        {running ? "运行中..." : primaryActionLabel}
      </button>
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="text-sm text-slate-500">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
      />
    </label>
  );
}

function Metric({
  title,
  value,
  tone,
  onClick,
  active = false,
}: {
  title: string;
  value: string;
  tone: "rose" | "blue" | "amber" | "emerald";
  onClick?: () => void;
  active?: boolean;
}) {
  const toneClass = {
    rose: "text-rose-600 dark:text-rose-300",
    blue: "text-blue-600 dark:text-blue-300",
    amber: "text-amber-600 dark:text-amber-300",
    emerald: "text-emerald-600 dark:text-emerald-300",
  }[tone];
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-2xl border bg-white p-4 text-left shadow-sm transition hover:border-blue-300 dark:bg-slate-900 ${active ? "border-blue-400 ring-2 ring-blue-200 dark:border-blue-500 dark:ring-blue-900" : "border-slate-200 dark:border-slate-800"}`}
    >
      <p className="text-sm text-slate-500">{title}</p>
      <p className={`mt-2 text-2xl font-bold ${toneClass}`}>{value}</p>
    </button>
  );
}

function ResultFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-950">
      <div className="text-xs text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className="mt-1 truncate text-lg font-semibold text-slate-900 dark:text-slate-100">
        {value}
      </div>
    </div>
  );
}

function CompareMetricCard({
  title,
  metricKey,
  format,
  runs,
  summary,
  strategyNameMap,
}: {
  title: string;
  metricKey: string;
  format: "percent" | "number";
  runs: BacktestCompareRun[];
  summary?: {
    best: { run_id: string; value: number };
    worst: { run_id: string; value: number };
  };
  strategyNameMap: Record<string, string>;
}) {
  const values = runs
    .map((run) => Number(run.metrics[metricKey]))
    .filter((value) => Number.isFinite(value));
  const minValue = values.length > 0 ? Math.min(...values) : 0;
  const maxValue = values.length > 0 ? Math.max(...values) : 0;
  const betterMode = metricKey === "volatility" ? "min" : "max";
  const formatValue = (value: number) =>
    format === "percent" ? formatPercent(value) : value.toFixed(2);
  const bestRun = summary
    ? runs.find((run) => run.run_id === summary.best.run_id)
    : null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold text-slate-900 dark:text-slate-100">
          {title}
        </h3>
        {summary && bestRun && (
          <span className="text-xs text-slate-400">
            最佳：{getBacktestRecordTitle(bestRun, strategyNameMap)}
          </span>
        )}
      </div>
      <div className="mt-3 space-y-3">
        {runs.map((run) => {
          const value = Number(run.metrics[metricKey] ?? 0);
          const raw =
            maxValue === minValue
              ? 1
              : (value - minValue) / (maxValue - minValue);
          const normalized = betterMode === "min" ? 1 - raw : raw;
          const width = `${Math.max(18, Math.round(normalized * 100))}%`;
          const isBest = summary?.best.run_id === run.run_id;
          return (
            <div key={`${metricKey}_${run.run_id}`} className="space-y-1">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 truncate text-slate-500 dark:text-slate-400">
                  {getBacktestRecordTitle(run, strategyNameMap)}
                  {isBest && (
                    <span className="ml-2 rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300">
                      最佳
                    </span>
                  )}
                </span>
                <span className="font-medium text-slate-700 dark:text-slate-200">
                  {formatValue(value)}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                <div
                  className={`h-full rounded-full ${isBest ? "bg-emerald-500" : "bg-blue-500"}`}
                  style={{ width }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
