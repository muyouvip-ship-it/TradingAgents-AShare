import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowPathIcon,
  BeakerIcon,
  ChartBarIcon,
  CpuChipIcon,
  PencilSquareIcon,
  PlayIcon,
  SparklesIcon,
  TrashIcon,
} from "@heroicons/react/24/outline";
import { api } from "@/services/api";
import type {
  EvolutionCandidate,
  EvolutionExperiment,
  OfficialStrategyPack,
  OfficialStrategyPackItem,
  StrategyDefinition,
  StrategyTier,
} from "@/types";

const strategyTypeLabels: Record<string, string> = {
  selection: "选股策略",
  trading: "交易策略",
  risk: "风控策略",
  portfolio: "组合策略",
};

const statusLabels: Record<string, string> = {
  draft: "草稿",
  active: "已启用",
  paused: "已停用",
  archived: "已归档",
  candidate: "候选",
};

const experimentStatusLabels: Record<string, string> = {
  pending: "待执行",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
};

const tierLabels: Record<StrategyTier, string> = {
  aggressive: "激进",
  stable: "稳健",
  defensive: "防守",
};

const strategySourceLabels: Record<string, string> = {
  manual: "手工创建",
  llm: "白话生成",
  evolution: "进化生成",
  template: "模板克隆",
};

function formatPercent(value?: number | null) {
  if (value == null) return "--";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

function sanitizeStrategyTags(tags?: string[]) {
  return (tags || []).filter((tag) => tag !== "模板" && tag !== "模板策略");
}

function getRecentRunLabel(strategyType?: string | null) {
  return strategyType === "selection" ? "最近验证" : "最近回测";
}

function formatDateTime(value?: string | null) {
  if (!value) return "--";
  return new Date(value).toLocaleString();
}

export default function StrategiesV2() {
  const navigate = useNavigate();
  const [strategies, setStrategies] = useState<StrategyDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [selectedStrategy, setSelectedStrategy] =
    useState<StrategyDefinition | null>(null);
  const [candidates, setCandidates] = useState<EvolutionCandidate[]>([]);
  const [selectedExperiment, setSelectedExperiment] =
    useState<EvolutionExperiment | null>(null);
  const [flowMessage, setFlowMessage] = useState<string | null>(null);
  const [versions, setVersions] = useState<unknown[]>([]);
  const [officialPacks, setOfficialPacks] = useState<OfficialStrategyPack[]>(
    [],
  );
  const [loadingPacks, setLoadingPacks] = useState(true);
  const [cloningPackId, setCloningPackId] = useState<string | null>(null);
  const [cloningBlueprintId, setCloningBlueprintId] = useState<string | null>(
    null,
  );
  const [previewItem, setPreviewItem] =
    useState<OfficialStrategyPackItem | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = useState<string | null>(null);
  const [showOfficialPacks, setShowOfficialPacks] = useState(false);
  const selectedStrategyRunLabel = getRecentRunLabel(
    selectedStrategy?.strategy_type,
  );

  const loadStrategies = async () => {
    setLoading(true);
    try {
      const response = await api.getStrategyPlatformList({
        strategy_type: typeFilter || undefined,
        search: search || undefined,
      });
      const items = response.strategies;
      setStrategies(items);
      setSelectedStrategy((current) =>
        current && items.some((item) => item.id === current.id)
          ? current
          : (items[0] ?? null),
      );
      setFlowMessage(null);
    } catch (error) {
      console.warn("策略平台 API 暂不可用", error);
      setStrategies([]);
      setSelectedStrategy(null);
      setFlowMessage("策略列表加载失败，当前不再显示本地预览数据。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadStrategies();
  }, [typeFilter]);

  useEffect(() => {
    const loadOfficialPacks = async () => {
      setLoadingPacks(true);
      try {
        const response = await api.getOfficialStrategyPacks();
        setOfficialPacks(response.packs);
      } catch (error) {
        console.warn("官方策略包接口暂不可用", error);
        setOfficialPacks([]);
      } finally {
        setLoadingPacks(false);
      }
    };
    void loadOfficialPacks();
  }, []);

  const createEvolution = async (strategy = selectedStrategy) => {
    if (!strategy) return;
    setSelectedStrategy(strategy);
    setFlowMessage("正在基于 Trade Snapshot 做归因进化...");
    try {
      const experiment = await api.createEvolutionExperiment({
        strategy_id: strategy.id,
        objective: "calmar_then_win_rate",
        search_space: {
          mutations: [
            "factor_weight",
            "threshold",
            "risk_overlay",
            "trade_snapshot_attribution",
          ],
        },
      });
      const detail = await api
        .getEvolutionExperiment(experiment.id)
        .catch(() => experiment);
      setSelectedExperiment(detail);
      setCandidates(detail.candidates);
      setFlowMessage("已生成候选策略，需确认后才会变成新版本。");
    } catch (error) {
      console.warn("进化实验接口暂不可用", error);
      setSelectedExperiment(null);
      setCandidates([]);
      setFlowMessage("归因进化失败，当前不再展示本地候选数据。");
    }
  };

  const loadVersions = async (strategy = selectedStrategy) => {
    if (!strategy) return;
    setSelectedStrategy(strategy);
    try {
      const response = await api.getStrategyVersions(strategy.id);
      setVersions(response.versions);
      setFlowMessage(`已加载 ${response.versions.length} 个版本。`);
    } catch (error) {
      console.warn("策略版本接口暂不可用", error);
      setVersions([]);
      setFlowMessage("版本列表加载失败，请确认后端服务。");
    }
  };

  const editStrategy = (strategy = selectedStrategy) => {
    if (!strategy) return;
    setSelectedStrategy(strategy);
    navigate(`/strategies/${strategy.id}/edit`);
  };

  const deleteStrategy = async (strategy = selectedStrategy) => {
    if (!strategy) return;
    setSelectedStrategy(strategy);
    const confirmed = window.confirm(
      `确认删除策略「${strategy.name}」吗？该操作会同时清理关联回测与进化记录。`,
    );
    if (!confirmed) return;
    const finalConfirmed = window.confirm(
      `请再次确认：删除「${strategy.name}」后将无法恢复，是否继续？`,
    );
    if (!finalConfirmed) return;
    try {
      await api.deleteStrategyDefinition(strategy.id);
      setStrategies((current) => {
        const next = current.filter((item) => item.id !== strategy.id);
        setSelectedStrategy((currentSelected) =>
          currentSelected?.id === strategy.id
            ? (next[0] ?? null)
            : currentSelected,
        );
        return next;
      });
      setVersions([]);
      setCandidates([]);
      setSelectedExperiment(null);
      setFlowMessage("策略已删除。");
    } catch (error) {
      console.warn("策略删除接口暂不可用", error);
      setFlowMessage("策略删除失败，请确认后端服务。");
    }
  };

  const clonePack = async (packId: string) => {
    setCloningPackId(packId);
    try {
      const response = await api.cloneOfficialStrategyPack(packId);
      setStrategies((current) => [...response.strategies, ...current]);
      setSelectedStrategy(response.strategies[0] ?? null);
      setFlowMessage(response.message);
    } catch (error) {
      console.warn("官方策略包克隆失败", error);
      setFlowMessage("官方策略包克隆失败，请确认后端服务。");
    } finally {
      setCloningPackId(null);
    }
  };

  const clonePackItem = async (packId: string, blueprintId: string) => {
    setCloningBlueprintId(blueprintId);
    try {
      const cloned = await api.cloneOfficialStrategyPackItem(
        packId,
        blueprintId,
      );
      setStrategies((current) => [cloned, ...current]);
      setSelectedStrategy(cloned);
      setFlowMessage(`已克隆策略「${cloned.name}」。`);
    } catch (error) {
      console.warn("官方策略单档克隆失败", error);
      setFlowMessage("官方策略单档克隆失败，请确认后端服务。");
    } finally {
      setCloningBlueprintId(null);
    }
  };

  const previewPackItem = async (packId: string, blueprintId: string) => {
    setPreviewLoadingId(blueprintId);
    try {
      const item = await api.getOfficialStrategyPackItem(packId, blueprintId);
      setPreviewItem(item);
    } catch (error) {
      console.warn("官方策略 DSL 预览失败", error);
      setFlowMessage("官方策略 DSL 预览失败，请确认后端服务。");
    } finally {
      setPreviewLoadingId(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 p-6 dark:bg-slate-950">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">
            <CpuChipIcon className="h-4 w-4" />
            PostgreSQL + Parquet + Polars + DuckDB
          </div>
          <h1 className="mt-3 text-2xl font-bold text-slate-900 dark:text-slate-100">
            策略管理工作台
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            白话生成、DSL 编写、回测、进化、纸交易一体化入口。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setShowOfficialPacks(true)}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <BeakerIcon className="h-4 w-4" />
            官方策略包
          </button>
          <button
            onClick={() => navigate("/strategies/create")}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
          >
            <SparklesIcon className="h-4 w-4" />
            创建策略
          </button>
          <button
            onClick={() => navigate("/backtest")}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <PlayIcon className="h-4 w-4" />
            进入回测
          </button>
        </div>
      </div>

      <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-col gap-3 lg:flex-row">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void loadStrategies();
            }}
            placeholder="搜索策略名称、描述、标签..."
            className="flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
          <select
            value={typeFilter}
            onChange={(event) => setTypeFilter(event.target.value)}
            className="rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            <option value="">全部类型</option>
            <option value="selection">选股策略</option>
            <option value="trading">交易策略</option>
            <option value="risk">风控策略</option>
            <option value="portfolio">组合策略</option>
          </select>
          <button
            onClick={loadStrategies}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white dark:bg-slate-100 dark:text-slate-900"
          >
            <ArrowPathIcon
              className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
            />
            刷新
          </button>
        </div>
        {flowMessage && (
          <div className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">
            {flowMessage}
          </div>
        )}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_0.9fr]">
        <div className="space-y-4">
          {loading ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
              正在加载策略列表...
            </div>
          ) : strategies.length === 0 ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
              当前没有可展示的真实策略数据。请确认后端服务可用，或先创建一条策略。
            </div>
          ) : (
            strategies.map((strategy) => (
              <div
                key={strategy.id}
                onClick={() => setSelectedStrategy(strategy)}
                className={`w-full rounded-2xl border bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md dark:bg-slate-900 ${
                  selectedStrategy?.id === strategy.id
                    ? "border-blue-400 ring-2 ring-blue-100 dark:ring-blue-500/20"
                    : "border-slate-200 dark:border-slate-800"
                }`}
              >
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                        {strategy.name}
                      </h2>
                      <Badge>
                        {strategyTypeLabels[strategy.strategy_type]}
                      </Badge>
                      <Badge
                        tone={
                          strategy.status === "active" ? "emerald" : "slate"
                        }
                      >
                        {statusLabels[strategy.status]}
                      </Badge>
                      <Badge tone="blue">v{strategy.version}</Badge>
                    </div>
                    <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                      {strategy.description}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {sanitizeStrategyTags(strategy.tags).map((tag) => (
                        <Badge key={tag} tone="slate">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          setSelectedStrategy(strategy);
                          navigate(`/backtest?strategy_id=${strategy.id}`);
                        }}
                        className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white"
                      >
                        <PlayIcon className="h-4 w-4" />
                        回测
                      </button>
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          editStrategy(strategy);
                        }}
                        className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200"
                      >
                        <PencilSquareIcon className="h-4 w-4" />
                        编辑
                      </button>
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          void loadVersions(strategy);
                        }}
                        className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200"
                      >
                        查看版本
                      </button>
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          void createEvolution(strategy);
                        }}
                        className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200"
                      >
                        <BeakerIcon className="h-4 w-4" />
                        归因进化
                      </button>
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          void deleteStrategy(strategy);
                        }}
                        className="inline-flex items-center gap-2 rounded-lg border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-600 dark:border-rose-900/60 dark:text-rose-300"
                      >
                        <TrashIcon className="h-4 w-4" />
                        删除
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              版本记录
            </h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {selectedStrategy
                ? `当前策略：${selectedStrategy.name}`
                : "先选择一条策略后查看版本记录。"}
            </p>
            <div className="mt-4 space-y-2">
              {versions.length === 0 ? (
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  {selectedStrategy
                    ? `${selectedStrategy.name} 暂无可读取版本记录，或你还没有点击“查看版本”。`
                    : "当前还没有选中策略。"}
                </div>
              ) : (
                versions.map((raw: any) => (
                  <div
                    key={raw.id}
                    className="rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-700"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-900 dark:text-slate-100">
                        版本 v{raw.version}
                      </span>
                      <Badge
                        tone={
                          raw.compile_status === "passed" ? "emerald" : "amber"
                        }
                      >
                        {raw.compile_status === "passed"
                          ? "编译通过"
                          : "待检查"}
                      </Badge>
                    </div>
                    <div className="mt-1 text-slate-500 dark:text-slate-400">
                      {raw.change_summary || "无变更说明"}
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      {raw.created_at}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
              <SparklesIcon className="h-5 w-5 text-fuchsia-500" />
              进化实验详情
            </h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {selectedStrategy
                ? `围绕 ${selectedStrategy.name} 查看最近一次归因进化实验。`
                : "先选择策略，再发起归因进化。"}
            </p>
            <div className="mt-4 space-y-3">
              {!selectedExperiment ? (
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  {selectedStrategy
                    ? "当前还没有已加载的进化实验。点击策略卡上的“归因进化”后，这里会显示实验状态、目标函数和候选数量。"
                    : "当前还没有选中策略。"}
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <MiniMetric
                      label="实验编号"
                      value={selectedExperiment.id.slice(0, 8)}
                      tone="blue"
                    />
                    <MiniMetric
                      label="候选数量"
                      value={`${selectedExperiment.candidates.length}`}
                      tone="purple"
                    />
                    <MiniMetric
                      label="实验状态"
                      value={
                        experimentStatusLabels[selectedExperiment.status] ||
                        selectedExperiment.status
                      }
                      tone="emerald"
                    />
                    <MiniMetric
                      label="实验进度"
                      value={formatPercent(selectedExperiment.progress)}
                      tone="amber"
                    />
                  </div>
                  <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-950 dark:text-slate-300">
                    <div>
                      <span className="font-semibold">目标函数：</span>
                      {selectedExperiment.objective}
                    </div>
                    <div className="mt-1">
                      <span className="font-semibold">策略编号：</span>
                      {selectedExperiment.strategy_id}
                    </div>
                    <div className="mt-1">
                      <span className="font-semibold">创建时间：</span>
                      {selectedExperiment.created_at}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
              <BeakerIcon className="h-5 w-5 text-purple-500" />
              进化候选
            </h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              这里只显示后端真实返回的候选结果，不再补本地样例。
            </p>
            <div className="mt-4 space-y-3">
              {candidates.length === 0 ? (
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  {selectedStrategy
                    ? "当前还没有候选结果。归因进化完成后，这里才会出现候选策略。"
                    : "当前还没有选中策略。"}
                </div>
              ) : (
                candidates.map((candidate) => (
                  <div
                    key={candidate.id}
                    className="rounded-xl border border-slate-200 p-4 dark:border-slate-700"
                  >
                    <div className="flex items-center justify-between">
                      <h3 className="font-semibold text-slate-900 dark:text-slate-100">
                        {candidate.name}
                      </h3>
                      <Badge tone="purple">
                        评分 {candidate.score.toFixed(1)}
                      </Badge>
                    </div>
                    <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                      {candidate.improvement_summary}
                    </p>
                    <div className="mt-3 grid grid-cols-3 gap-2">
                      <MiniMetric
                        label="收益"
                        value={formatPercent(candidate.metrics.total_return)}
                        tone="rose"
                      />
                      <MiniMetric
                        label="胜率"
                        value={formatPercent(candidate.metrics.win_rate)}
                        tone="emerald"
                      />
                      <MiniMetric
                        label="回撤"
                        value={formatPercent(candidate.metrics.max_drawdown)}
                        tone="amber"
                      />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {candidate.risk_flags.map((flag) => (
                        <Badge key={flag} tone="amber">
                          {flag}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
              <ChartBarIcon className="h-5 w-5 text-cyan-500" />
              当前策略摘要
            </h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              只展示当前选中策略的真实元信息，避免把“已启用”误读成正在跑任务。
            </p>
            <div className="mt-4 space-y-3">
              {!selectedStrategy ? (
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  当前还没有选中策略。
                </div>
              ) : (
                <div className="grid gap-3 md:grid-cols-2">
                  <MiniMetric
                    label="策略类型"
                    value={strategyTypeLabels[selectedStrategy.strategy_type]}
                    tone="blue"
                  />
                  <MiniMetric
                    label="生命周期状态"
                    value={statusLabels[selectedStrategy.status]}
                    tone="emerald"
                  />
                  <MiniMetric
                    label="创建来源"
                    value={
                      strategySourceLabels[selectedStrategy.source || ""] ||
                      "未标注"
                    }
                    tone="purple"
                  />
                  <MiniMetric
                    label="累计记录数"
                    value={String(selectedStrategy.run_count ?? 0)}
                    tone="amber"
                  />
                  <MiniMetric
                    label={selectedStrategyRunLabel}
                    value={formatDateTime(selectedStrategy.last_run_time)}
                    tone="slate"
                  />
                  <MiniMetric
                    label="更新时间"
                    value={formatDateTime(selectedStrategy.updated_at)}
                    tone="slate"
                  />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {previewItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="max-h-[88vh] w-full max-w-5xl overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-slate-900">
            <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5 dark:border-slate-800">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  {previewItem.name}
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {strategyTypeLabels[previewItem.strategy_type]} ·{" "}
                  {tierLabels[previewItem.tier]} · 官方版本 v
                  {previewItem.version}
                </p>
              </div>
              <button
                onClick={() => setPreviewItem(null)}
                className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-300"
              >
                关闭
              </button>
            </div>
            <div className="max-h-[70vh] overflow-auto p-5">
              <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
                {previewItem.description}
              </p>
              <pre className="rounded-2xl bg-slate-950 p-4 text-xs leading-relaxed text-slate-100">
                {JSON.stringify(previewItem.dsl ?? {}, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}

      {showOfficialPacks && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="max-h-[88vh] w-full max-w-6xl overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-slate-900">
            <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5 dark:border-slate-800">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  官方策略包
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  每种策略类型提供“激进 / 稳健 /
                  防守”三档官方样板，支持一键克隆到你的策略列表。
                </p>
              </div>
              <div className="flex items-center gap-3">
                {loadingPacks && (
                  <div className="text-sm text-slate-400">加载中...</div>
                )}
                <button
                  onClick={() => setShowOfficialPacks(false)}
                  className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-300"
                >
                  关闭
                </button>
              </div>
            </div>
            <div className="max-h-[70vh] overflow-auto p-5">
              {officialPacks.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-300 p-6 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  官方策略包当前不可用，页面不再展示本地预览包。
                </div>
              ) : (
                <div className="grid gap-4 xl:grid-cols-2">
                  {officialPacks.map((pack) => (
                    <div
                      key={pack.id}
                      className="rounded-2xl border border-slate-200 p-4 dark:border-slate-700"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-semibold text-slate-900 dark:text-slate-100">
                              {pack.name}
                            </h3>
                            <Badge>
                              {strategyTypeLabels[pack.strategy_type]}
                            </Badge>
                          </div>
                          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                            {pack.description}
                          </p>
                        </div>
                        <button
                          onClick={() => void clonePack(pack.id)}
                          disabled={cloningPackId === pack.id}
                          className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
                        >
                          {cloningPackId === pack.id ? "克隆中..." : "一键克隆"}
                        </button>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {pack.tags.map((tag) => (
                          <Badge key={tag} tone="slate">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                      <div className="mt-4 grid gap-3">
                        {pack.items.map((item) => (
                          <div
                            key={item.blueprint_id}
                            className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950"
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium text-slate-900 dark:text-slate-100">
                                {item.name}
                              </span>
                              <Badge
                                tone={
                                  item.tier === "aggressive"
                                    ? "rose"
                                    : item.tier === "stable"
                                      ? "blue"
                                      : "emerald"
                                }
                              >
                                {tierLabels[item.tier]}
                              </Badge>
                              <Badge tone="slate">v{item.version}</Badge>
                            </div>
                            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                              {item.description}
                            </p>
                            <div className="mt-2 text-xs text-slate-400">
                              官方样板不在这里展示统一回测收益、夏普、回撤、胜率，避免把不同区间和不同链路结果误读为可直接横向比较。
                            </div>
                            {item.tags.length > 0 && (
                              <div className="mt-3 flex flex-wrap gap-2">
                                {item.tags.map((tag) => (
                                  <Badge key={tag} tone="slate">
                                    {tag}
                                  </Badge>
                                ))}
                              </div>
                            )}
                            <div className="mt-3 flex flex-wrap gap-2">
                              <button
                                onClick={() =>
                                  void previewPackItem(
                                    pack.id,
                                    item.blueprint_id,
                                  )
                                }
                                disabled={
                                  previewLoadingId === item.blueprint_id
                                }
                                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300"
                              >
                                {previewLoadingId === item.blueprint_id
                                  ? "加载中..."
                                  : "预览 DSL"}
                              </button>
                              <button
                                onClick={() =>
                                  void clonePackItem(pack.id, item.blueprint_id)
                                }
                                disabled={
                                  cloningBlueprintId === item.blueprint_id
                                }
                                className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                              >
                                {cloningBlueprintId === item.blueprint_id
                                  ? "克隆中..."
                                  : "克隆此档"}
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function MiniMetric({
  label,
  value,
  tone = "slate",
}: {
  label: string;
  value: string;
  tone?: "slate" | "emerald" | "blue" | "rose" | "amber" | "purple";
}) {
  const toneClass = {
    slate: "text-slate-900 dark:text-slate-100",
    emerald: "text-emerald-600 dark:text-emerald-300",
    blue: "text-blue-600 dark:text-blue-300",
    rose: "text-rose-600 dark:text-rose-300",
    amber: "text-amber-600 dark:text-amber-300",
    purple: "text-purple-600 dark:text-purple-300",
  }[tone];
  return (
    <div className="rounded-xl bg-slate-50 p-2 dark:bg-slate-950">
      <p className="text-[11px] text-slate-400">{label}</p>
      <p className={`text-sm font-semibold ${toneClass}`}>{value}</p>
    </div>
  );
}

function Badge({
  children,
  tone = "slate",
}: {
  children: ReactNode;
  tone?: "slate" | "emerald" | "blue" | "purple" | "amber" | "rose";
}) {
  const toneClass = {
    slate: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    emerald:
      "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300",
    blue: "bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-300",
    purple:
      "bg-purple-50 text-purple-600 dark:bg-purple-500/10 dark:text-purple-300",
    amber:
      "bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300",
    rose: "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300",
  }[tone];
  return (
    <span
      className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${toneClass}`}
    >
      {children}
    </span>
  );
}
