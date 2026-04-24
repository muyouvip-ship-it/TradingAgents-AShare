import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeftIcon,
  ArrowPathIcon,
  ChartBarIcon,
  ClockIcon,
  ListBulletIcon,
  PresentationChartLineIcon,
} from '@heroicons/react/24/outline'
import { DrawdownChart, PortfolioValueChart, ReturnsDistributionChart } from '../components/Charts'
import KlinePanel from '../components/KlinePanel'
import { api } from '@/services/api'
import type {
  BacktestEquityPoint,
  BacktestMinuteConfirmationItem,
  BacktestOrderItem,
  BacktestPositionItem,
  BacktestRun,
  BacktestSignalItem,
  BacktestTradeRecord,
  BacktestTradeSnapshot,
  BacktestWatchlistItem,
} from '@/types'

type ViewMode = 'overview' | 'symbols' | 'dates' | 'flows'
type StrategyResultType = 'selection' | 'trading' | 'risk' | 'portfolio'

function formatPercent(value?: number | null) {
  if (value == null) return '--'
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

function formatDate(value?: string | null) {
  if (!value) return '--'
  return value.slice(0, 10)
}

function formatDateTime(value?: string | null) {
  if (!value) return '--'
  return value.slice(0, 19).replace('T', ' ')
}

function dateKey(value?: string | null) {
  return value ? value.slice(0, 10) : ''
}

function formatAmount(value?: number | null) {
  if (value == null) return '--'
  return `¥${Number(value).toLocaleString()}`
}

function toChineseBacktestStatus(value?: string | null) {
  if (!value) return '--'
  const mapping: Record<string, string> = {
    pending: '待执行',
    running: '执行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return mapping[value] || value
}

function toChineseEngineMode(value?: string | null) {
  if (!value) return '--'
  return value === 'true_engine' ? '真引擎' : value === 'fallback_engine' ? '回退链路' : value
}

function toChineseTimeframe(value?: string | null) {
  if (!value) return '--'
  const mapping: Record<string, string> = {
    '1m': '1 分钟',
    '5m': '5 分钟',
    '15m': '15 分钟',
    '30m': '30 分钟',
    '1d': '日线',
    '1w': '周线',
  }
  return mapping[value] || value
}

function toChineseStrategyType(value?: string | null) {
  const mapping: Record<string, string> = {
    selection: '选股策略',
    trading: '交易策略',
    risk: '风控策略',
    portfolio: '组合策略',
  }
  return value ? (mapping[value] || value) : '--'
}

function normalizeStrategyType(summary: Record<string, unknown>): StrategyResultType {
  const requestConfig = (summary.request_config || {}) as Record<string, unknown>
  const raw = String(summary.strategy_type || requestConfig.strategy_type || '')
  if (raw === 'selection' || raw === 'trading' || raw === 'risk' || raw === 'portfolio') return raw
  if (summary.selection_only_mode) return 'selection'
  return 'portfolio'
}

function getResultPageCopy(strategyType: StrategyResultType, selectionOnlyMode: boolean) {
  if (strategyType === 'selection' || selectionOnlyMode) {
    return {
      title: '选股结果详情',
      subtitle: '优先查看候选池、入选原因、分钟确认和筛选覆盖情况；收益与成交仅在交易型模式下展示。',
      overviewLabel: '选股总览',
    }
  }
  if (strategyType === 'risk') {
    return {
      title: '风控回测详情',
      subtitle: '优先查看回撤、风险暴露、拒单原因和风控覆盖效果。',
      overviewLabel: '风控总览',
    }
  }
  if (strategyType === 'trading') {
    return {
      title: '交易回测详情',
      subtitle: '优先查看资金曲线、信号、订单、成交和单票执行链路。',
      overviewLabel: '交易总览',
    }
  }
  return {
    title: '组合回测详情',
    subtitle: '优先查看组合收益、持仓分布、仓位变化和单票贡献。',
    overviewLabel: '组合总览',
  }
}

function toChineseDirection(value?: 'buy' | 'sell' | null) {
  if (!value) return '--'
  return value === 'buy' ? '买入' : '卖出'
}

function toChineseOrderStatus(value?: string | null) {
  if (!value) return '--'
  const mapping: Record<string, string> = {
    pending: '待执行',
    filled: '已成交',
    rejected: '已拒绝',
  }
  return mapping[value] || value
}

function buildChartData(items: BacktestEquityPoint[]) {
  return items.map(item => ({
    date: item.date,
    value: item.equity,
    cash: item.cash,
    position: item.positions_value,
    price: item.equity,
    drawdown: item.drawdown ?? 0,
  }))
}

function groupUniqueSymbols(payload: {
  trades: BacktestTradeRecord[]
  watchlists: BacktestWatchlistItem[]
  minuteConfirmations: BacktestMinuteConfirmationItem[]
  snapshots: BacktestTradeSnapshot[]
  signals: BacktestSignalItem[]
  positions: BacktestPositionItem[]
  orders: BacktestOrderItem[]
}) {
  return Array.from(new Set([
    ...payload.trades.map(item => item.symbol),
    ...payload.watchlists.map(item => item.symbol),
    ...payload.minuteConfirmations.map(item => item.symbol),
    ...payload.snapshots.map(item => item.symbol),
    ...payload.signals.map(item => item.symbol),
    ...payload.positions.map(item => item.symbol),
    ...payload.orders.map(item => item.symbol),
  ])).sort()
}

function MetricCard({
  title,
  value,
  hint,
}: {
  title: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="text-xs text-slate-500 dark:text-slate-400">{title}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </div>
  )
}

function SectionCard({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: ReactNode
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
        {subtitle && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}

export default function BacktestResult() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('overview')
  const [run, setRun] = useState<BacktestRun | null>(null)
  const [equity, setEquity] = useState<BacktestEquityPoint[]>([])
  const [trades, setTrades] = useState<BacktestTradeRecord[]>([])
  const [watchlists, setWatchlists] = useState<BacktestWatchlistItem[]>([])
  const [minuteConfirmations, setMinuteConfirmations] = useState<BacktestMinuteConfirmationItem[]>([])
  const [snapshots, setSnapshots] = useState<BacktestTradeSnapshot[]>([])
  const [signals, setSignals] = useState<BacktestSignalItem[]>([])
  const [positions, setPositions] = useState<BacktestPositionItem[]>([])
  const [orders, setOrders] = useState<BacktestOrderItem[]>([])
  const [selectedSymbol, setSelectedSymbol] = useState('')
  const [selectedDate, setSelectedDate] = useState('')
  const [focusedEventDate, setFocusedEventDate] = useState('')

  const load = async (silent = false) => {
    if (!runId) return
    if (silent) setRefreshing(true)
    else setLoading(true)
    setError(null)
    try {
      const runResponse = await api.getStrategyPlatformBacktest(runId)
      setRun(runResponse)
      const [equityResponse, tradesResponse] = await Promise.all([
        api.getStrategyPlatformBacktestEquity(runId).catch(() => ({ items: [] })),
        api.getStrategyPlatformBacktestTrades(runId).catch(() => ({ items: [] })),
      ])
      setEquity(equityResponse.items)
      setTrades(tradesResponse.items)

      const [watchlistsResponse, minuteResponse, snapshotsResponse, signalsResponse, positionsResponse, ordersResponse] = await Promise.all([
        api.getStrategyPlatformBacktestWatchlists(runId).catch(() => ({ items: [] })),
        api.getStrategyPlatformBacktestMinuteConfirmations(runId).catch(() => ({ items: [] })),
        api.getStrategyPlatformBacktestTradeSnapshots(runId).catch(() => ({ items: [] })),
        api.getStrategyPlatformBacktestSignals(runId).catch(() => ({ items: [] })),
        api.getStrategyPlatformBacktestPositions(runId).catch(() => ({ items: [] })),
        api.getStrategyPlatformBacktestOrders(runId).catch(() => ({ items: [] })),
      ])
      setWatchlists(watchlistsResponse.items)
      setMinuteConfirmations(minuteResponse.items)
      setSnapshots(snapshotsResponse.items)
      setSignals(signalsResponse.items)
      setPositions(positionsResponse.items)
      setOrders(ordersResponse.items)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '结果加载失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    void load()
  }, [runId])

  const symbols = useMemo(
    () => groupUniqueSymbols({ trades, watchlists, minuteConfirmations, snapshots, signals, positions, orders }),
    [trades, watchlists, minuteConfirmations, snapshots, signals, positions, orders],
  )
  const dates = useMemo(() => Array.from(new Set([
    ...watchlists.map(item => dateKey(item.date)),
    ...minuteConfirmations.map(item => dateKey(item.date || item.bar_end)),
    ...signals.map(item => dateKey(item.date)),
    ...orders.map(item => dateKey(item.execute_date || item.signal_date)),
    ...trades.map(item => dateKey(item.timestamp)),
    ...positions.map(item => dateKey(item.date)),
    ...snapshots.map(item => dateKey(item.timestamp)),
  ].filter(Boolean))).sort().reverse(), [watchlists, minuteConfirmations, signals, orders, trades, positions, snapshots])

  useEffect(() => {
    if (!selectedSymbol && symbols[0]) setSelectedSymbol(symbols[0])
    if (selectedSymbol && !symbols.includes(selectedSymbol)) setSelectedSymbol(symbols[0] || '')
  }, [selectedSymbol, symbols])

  useEffect(() => {
    setFocusedEventDate('')
  }, [selectedSymbol])

  useEffect(() => {
    if (!selectedDate && dates[0]) setSelectedDate(dates[0])
    if (selectedDate && !dates.includes(selectedDate)) setSelectedDate(dates[0] || '')
  }, [selectedDate, dates])

  const summary = (run?.result?.summary ?? {}) as Record<string, unknown>
  const diagnostics = (run?.result?.diagnostics ?? {}) as Record<string, unknown>
  const metrics = run?.metrics
  const chartData = useMemo(() => buildChartData(equity), [equity])
  const selectionOnlyMode = Boolean(summary.selection_only_mode ?? (summary.strategy_type === 'selection'))
  const strategyType = normalizeStrategyType(summary)
  const pageCopy = getResultPageCopy(strategyType, selectionOnlyMode)
  const confirmedMinuteCount = minuteConfirmations.filter(item => item.confirmed).length
  const latestWatchlistDate = watchlists
    .map(item => dateKey(item.date))
    .filter(Boolean)
    .sort()
    .reverse()[0] || ''
  const latestWatchlists = useMemo(
    () => watchlists
      .filter(item => !latestWatchlistDate || dateKey(item.date) === latestWatchlistDate)
      .sort((left, right) => (left.rank || 999999) - (right.rank || 999999))
      .slice(0, 12),
    [latestWatchlistDate, watchlists],
  )
  const topWatchlists = useMemo(
    () => [...watchlists]
      .sort((left, right) => (right.factor_score || 0) - (left.factor_score || 0))
      .slice(0, 12),
    [watchlists],
  )
  const rejectedOrders = orders.filter(item => item.status === 'rejected')
  const hasSelectionExecutionData = strategyType === 'selection' && (orders.length > 0 || trades.length > 0)

  const selectedTrades = useMemo(() => trades.filter(item => item.symbol === selectedSymbol), [selectedSymbol, trades])
  const selectedWatchlists = useMemo(() => watchlists.filter(item => item.symbol === selectedSymbol), [selectedSymbol, watchlists])
  const selectedMinuteConfirmations = useMemo(() => minuteConfirmations.filter(item => item.symbol === selectedSymbol), [selectedSymbol, minuteConfirmations])
  const selectedSignals = useMemo(() => signals.filter(item => item.symbol === selectedSymbol), [selectedSymbol, signals])
  const selectedOrders = useMemo(() => orders.filter(item => item.symbol === selectedSymbol), [selectedSymbol, orders])
  const selectedPositions = useMemo(() => positions.filter(item => item.symbol === selectedSymbol), [selectedSymbol, positions])
  const selectedSnapshots = useMemo(() => snapshots.filter(item => item.symbol === selectedSymbol), [selectedSymbol, snapshots])
  const latestSelectedSignal = useMemo(
    () => [...selectedSignals].sort((left, right) => String(right.date).localeCompare(String(left.date)))[0],
    [selectedSignals],
  )
  const latestSelectedOrder = useMemo(
    () => [...selectedOrders].sort((left, right) => String(right.execute_date || right.signal_date).localeCompare(String(left.execute_date || left.signal_date)))[0],
    [selectedOrders],
  )
  const latestSelectedTrade = useMemo(
    () => [...selectedTrades].sort((left, right) => String(right.timestamp).localeCompare(String(left.timestamp)))[0],
    [selectedTrades],
  )
  const latestSelectedSnapshot = useMemo(
    () => [...selectedSnapshots].sort((left, right) => String(right.timestamp).localeCompare(String(left.timestamp)))[0],
    [selectedSnapshots],
  )

  const selectedDateWatchlists = useMemo(() => watchlists.filter(item => dateKey(item.date) === selectedDate), [selectedDate, watchlists])
  const selectedDateMinuteConfirmations = useMemo(() => minuteConfirmations.filter(item => dateKey(item.date || item.bar_end) === selectedDate), [selectedDate, minuteConfirmations])
  const selectedDateSignals = useMemo(() => signals.filter(item => dateKey(item.date) === selectedDate), [selectedDate, signals])
  const selectedDateOrders = useMemo(() => orders.filter(item => dateKey(item.execute_date || item.signal_date) === selectedDate), [selectedDate, orders])
  const selectedDateTrades = useMemo(() => trades.filter(item => dateKey(item.timestamp) === selectedDate), [selectedDate, trades])
  const selectedDatePositions = useMemo(() => positions.filter(item => dateKey(item.date) === selectedDate), [selectedDate, positions])
  const selectedSymbolMarkers = useMemo(() => ([
    ...selectedSignals.map(item => ({
      date: item.date,
      timestamp: item.date,
      side: item.side,
      text: item.side === 'buy' ? '信号B' : '信号S',
      reason: item.reason,
      color: item.side === 'buy' ? '#dc2626' : '#16a34a',
    })),
    ...selectedTrades.map(item => ({
      date: item.timestamp,
      timestamp: item.timestamp,
      side: item.direction,
      quantity: item.quantity,
      price: item.price,
      reason: item.reason,
      text: item.direction === 'buy' ? '买入' : '卖出',
      color: item.direction === 'buy' ? '#b91c1c' : '#15803d',
    })),
  ]), [selectedSignals, selectedTrades])

  const symbolCards = useMemo(() => (
    symbols.map(symbol => {
      const symbolTrades = trades.filter(item => item.symbol === symbol)
      const symbolWatchlists = watchlists.filter(item => item.symbol === symbol)
      const symbolMinuteConfirms = minuteConfirmations.filter(item => item.symbol === symbol)
      const symbolOrders = orders.filter(item => item.symbol === symbol)
      const latestPosition = [...positions].reverse().find(item => item.symbol === symbol)
      const filledOrders = symbolOrders.filter(item => item.status === 'filled').length
      return {
        symbol,
        watchlistCount: symbolWatchlists.length,
        minuteCount: symbolMinuteConfirms.length,
        tradeCount: symbolTrades.length,
        orderCount: symbolOrders.length,
        filledOrders,
        latestValue: latestPosition?.market_value ?? 0,
      }
    })
  ), [symbols, trades, watchlists, minuteConfirmations, orders, positions])
  const dateCards = useMemo(() => (
    dates.map(date => ({
      date,
      watchlistCount: watchlists.filter(item => dateKey(item.date) === date).length,
      minuteCount: minuteConfirmations.filter(item => dateKey(item.date || item.bar_end) === date).length,
      signalCount: signals.filter(item => dateKey(item.date) === date).length,
      orderCount: orders.filter(item => dateKey(item.execute_date || item.signal_date) === date).length,
      tradeCount: trades.filter(item => dateKey(item.timestamp) === date).length,
      positionCount: positions.filter(item => dateKey(item.date) === date).length,
    }))
  ), [dates, watchlists, minuteConfirmations, signals, orders, trades, positions])

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 p-6 dark:bg-slate-950">
        <div className="flex min-h-[60vh] items-center justify-center text-slate-500 dark:text-slate-400">
          <ArrowPathIcon className="mr-2 h-5 w-5 animate-spin" />
          正在加载回测结果...
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 dark:bg-slate-950">
      <div className="mx-auto max-w-[1600px] space-y-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Link
                to="/backtest"
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
              >
                <ArrowLeftIcon className="h-4 w-4" />
                返回回测工作台
              </Link>
              <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">
                结果详情页
              </span>
              <span className="rounded-full bg-purple-50 px-3 py-1 text-xs font-medium text-purple-600 dark:bg-purple-500/10 dark:text-purple-300">
                {toChineseStrategyType(strategyType)}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {toChineseBacktestStatus(run?.status)}
              </span>
            </div>
            <h1 className="mt-3 text-2xl font-bold text-slate-900 dark:text-slate-100">{pageCopy.title}</h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {pageCopy.subtitle}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              运行编号：{run?.id} · 区间 {run?.start_date} ~ {run?.end_date}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => void load(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            >
              <ArrowPathIcon className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
              刷新结果
            </button>
            <button
              onClick={() => navigate(`/backtest?strategy_id=${run?.strategy_id ?? ''}`)}
              className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm"
            >
              基于此策略重开回测
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-500/10 dark:text-rose-200">
            {error}
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
          {(strategyType === 'selection' || selectionOnlyMode) ? (
            <>
              <MetricCard title="候选记录数" value={String(watchlists.length)} hint="所有日期候选池记录" />
              <MetricCard title="候选池天数" value={String((summary.watchlist_days ?? dates.length) || '--')} />
              <MetricCard title="覆盖股票数" value={String(symbols.length)} />
              <MetricCard title="分钟确认通过" value={String(confirmedMinuteCount)} />
              <MetricCard title="分钟确认命中率" value={formatPercent(Number(diagnostics.confirm_hit_rate ?? 0))} />
              <MetricCard title="最新候选日期" value={latestWatchlistDate || '--'} />
            </>
          ) : (
            <>
              <MetricCard title="总收益率" value={formatPercent(metrics?.total_return)} />
              <MetricCard title="年化收益" value={formatPercent(metrics?.annual_return)} />
              <MetricCard title="夏普比率" value={metrics ? metrics.sharpe_ratio.toFixed(2) : '--'} />
              <MetricCard title={strategyType === 'risk' ? '风控后最大回撤' : '最大回撤'} value={formatPercent(metrics?.max_drawdown)} />
              <MetricCard title="候选池天数" value={String(summary.watchlist_days ?? '--')} />
              <MetricCard title={strategyType === 'risk' ? '拒单 / 风控触发' : '分钟确认命中率'} value={strategyType === 'risk' ? String(rejectedOrders.length) : formatPercent(Number(diagnostics.confirm_hit_rate ?? 0))} />
            </>
          )}
        </div>

        <div className="grid gap-4 xl:grid-cols-4">
          <SectionCard title="运行摘要" subtitle="策略类型、执行链路与数据诊断">
            <div className="grid gap-3 text-sm md:grid-cols-2">
              <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                <div className="text-slate-400">执行模式</div>
                <div className="mt-1 font-medium text-slate-900 dark:text-slate-100">{toChineseEngineMode(String(summary.engine_mode ?? '--'))}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                <div className="text-slate-400">策略类型</div>
                <div className="mt-1 font-medium text-slate-900 dark:text-slate-100">{toChineseStrategyType(strategyType)}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                <div className="text-slate-400">分钟聚合周期</div>
                <div className="mt-1 font-medium text-slate-900 dark:text-slate-100">{toChineseTimeframe(String(summary.minute_aggregation ?? '--'))}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                <div className="text-slate-400">股票覆盖数</div>
                <div className="mt-1 font-medium text-slate-900 dark:text-slate-100">{symbols.length}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                <div className="text-slate-400">分钟缺失数</div>
                <div className="mt-1 font-medium text-slate-900 dark:text-slate-100">{String(diagnostics.minute_data_missing ?? 0)}</div>
              </div>
            </div>
          </SectionCard>
          <SectionCard title="查看方式" subtitle="将大结果按视角拆开看">
            <div className="grid gap-3">
              {[
                { key: 'overview', label: pageCopy.overviewLabel, icon: PresentationChartLineIcon },
                { key: 'symbols', label: strategyType === 'selection' ? '按股票看候选' : '按股票看', icon: ChartBarIcon },
                { key: 'dates', label: strategyType === 'selection' ? '按日期看选股' : '按日期看', icon: ClockIcon },
                { key: 'flows', label: strategyType === 'selection' ? '候选流水' : '流水视角', icon: ListBulletIcon },
              ].map(item => {
                const Icon = item.icon
                const active = viewMode === item.key
                return (
                  <button
                    key={item.key}
                    onClick={() => setViewMode(item.key as ViewMode)}
                    className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm ${active ? 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-500/10 dark:text-blue-200' : 'border-slate-200 bg-white text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'}`}
                  >
                    <Icon className="h-5 w-5" />
                    {item.label}
                  </button>
                )
              })}
            </div>
          </SectionCard>
          <SectionCard title="链路说明" subtitle="结果页的主设计方向">
            <div className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
              <div className="flex items-center gap-2"><ClockIcon className="h-4 w-4" /> 先看结果总览，再切股票视角</div>
              <div className="flex items-center gap-2"><ClockIcon className="h-4 w-4" /> 单票里串起候选、确认、信号、订单、成交</div>
              <div className="flex items-center gap-2"><ClockIcon className="h-4 w-4" /> 单日里聚合全市场候选、确认和执行</div>
              <div className="flex items-center gap-2"><ClockIcon className="h-4 w-4" /> 多股票时不再按表格分散查看</div>
            </div>
          </SectionCard>
          <SectionCard title="当前状态" subtitle="回测结果是否适合继续分析">
            <div className={`rounded-xl px-4 py-3 text-sm ${run?.status === 'completed' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200' : run?.status === 'running' ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200' : 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200'}`}>
              {run?.status === 'completed'
                ? '结果已完成，可以切换视角做分析。'
                : run?.status === 'running'
                  ? '回测仍在执行，当前页面可反复刷新查看增量结果。'
                  : `当前状态：${toChineseBacktestStatus(run?.status)}`}
            </div>
          </SectionCard>
        </div>

        {viewMode === 'overview' && (
          <div className="space-y-6">
            {(strategyType === 'selection' || selectionOnlyMode) && (
              <div className="grid gap-6 xl:grid-cols-2">
                <SectionCard title="最新候选池" subtitle={latestWatchlistDate ? `候选日期：${latestWatchlistDate}` : '按最近候选日期展示'}>
                  <div className="space-y-3">
                    {latestWatchlists.length === 0 ? (
                      <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">暂无候选池记录。</div>
                    ) : latestWatchlists.map(item => (
                      <button
                        key={`${item.date}_${item.symbol}_${item.rank}`}
                        onClick={() => {
                          setSelectedSymbol(item.symbol)
                          setViewMode('symbols')
                        }}
                        className="w-full rounded-xl bg-slate-50 p-3 text-left text-sm transition hover:bg-blue-50 dark:bg-slate-950 dark:hover:bg-blue-500/10"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol}</div>
                          <div className="rounded-full bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">排名 {item.rank}</div>
                        </div>
                        <div className="mt-1 text-slate-500 dark:text-slate-400">因子分 {item.factor_score.toFixed(3)} · 周线趋势 {item.weekly_trend_pass === false ? '未通过' : '通过'}</div>
                      </button>
                    ))}
                  </div>
                </SectionCard>
                <SectionCard title="高分候选" subtitle="按因子分从高到低，适合快速定位最强候选">
                  <div className="space-y-3">
                    {topWatchlists.length === 0 ? (
                      <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">暂无高分候选记录。</div>
                    ) : topWatchlists.map(item => (
                      <button
                        key={`${item.date}_${item.symbol}_${item.factor_score}_${item.rank}`}
                        onClick={() => {
                          setSelectedSymbol(item.symbol)
                          setViewMode('symbols')
                        }}
                        className="w-full rounded-xl bg-slate-50 p-3 text-left text-sm transition hover:bg-blue-50 dark:bg-slate-950 dark:hover:bg-blue-500/10"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol}</div>
                          <div className="text-xs text-slate-400">{formatDate(item.date)}</div>
                        </div>
                        <div className="mt-1 text-slate-500 dark:text-slate-400">因子分 {item.factor_score.toFixed(3)} · 当日排名 {item.rank}</div>
                      </button>
                    ))}
                  </div>
                </SectionCard>
              </div>
            )}
            {strategyType === 'risk' && !selectionOnlyMode && (
              <SectionCard title="风控执行摘要" subtitle="优先检查拒单、最大回撤和风控触发情况">
                <div className="grid gap-4 md:grid-cols-3">
                  <MetricCard title="拒单 / 风控触发" value={String(rejectedOrders.length)} />
                  <MetricCard title="最大回撤" value={formatPercent(metrics?.max_drawdown)} />
                  <MetricCard title="交易胜率" value={formatPercent(metrics?.win_rate)} />
                </div>
              </SectionCard>
            )}
            {!selectionOnlyMode && (
              <div className="grid gap-6 xl:grid-cols-3">
                <PortfolioValueChart data={chartData} />
                <DrawdownChart data={chartData} />
                <ReturnsDistributionChart data={chartData} />
              </div>
            )}
            <SectionCard title="股票覆盖概览" subtitle="适合先快速看全局，再进入单票链路">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {symbolCards.slice(0, 12).map(item => (
                  <button
                    key={item.symbol}
                    onClick={() => {
                      setSelectedSymbol(item.symbol)
                      setViewMode('symbols')
                    }}
                    className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-left dark:border-slate-700 dark:bg-slate-950"
                  >
                    <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol}</div>
                    <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                      候选 {item.watchlistCount} · 分钟确认 {item.minuteCount} · 订单 {item.orderCount} · 成交 {item.tradeCount}
                    </div>
                    <div className="mt-2 text-xs text-slate-400">最新持仓市值 {formatAmount(item.latestValue)}</div>
                  </button>
                ))}
              </div>
            </SectionCard>
          </div>
        )}

        {viewMode === 'symbols' && (
          <div className="grid gap-6 xl:grid-cols-[320px_1fr]">
            <SectionCard title={strategyType === 'selection' ? '候选股票列表' : '股票列表'} subtitle={strategyType === 'selection' ? '先选一只股票，再看它的入选原因、分钟确认和筛选快照' : '先选一只股票，再看完整链路'}>
              <div className="max-h-[920px] space-y-3 overflow-y-auto pr-1">
                {symbolCards.length === 0 ? (
                  <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">暂无股票结果。</div>
                ) : symbolCards.map(item => {
                  const active = item.symbol === selectedSymbol
                  return (
                    <button
                      key={item.symbol}
                      onClick={() => setSelectedSymbol(item.symbol)}
                      className={`w-full rounded-xl border p-4 text-left ${active ? 'border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-500/10' : 'border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900'}`}
                    >
                      <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol}</div>
                      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        候选 {item.watchlistCount} / 确认 {item.minuteCount} / 订单 {item.orderCount} / 成交 {item.tradeCount}
                      </div>
                    </button>
                  )
                })}
              </div>
            </SectionCard>

            <div className="space-y-6">
              <SectionCard title={selectedSymbol ? `${selectedSymbol} 单票链路` : '单票链路'} subtitle={strategyType === 'selection' ? '优先查看候选池、分钟确认、筛选信号和快照归因。' : '把候选池、确认、信号、订单、成交和持仓串起来看'}>
                {!selectedSymbol ? (
                  <div className="text-sm text-slate-500 dark:text-slate-400">请选择一只股票。</div>
                ) : (
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
                    <MetricCard title="候选池次数" value={String(selectedWatchlists.length)} />
                    <MetricCard title="分钟确认次数" value={String(selectedMinuteConfirmations.length)} />
                    <MetricCard title={strategyType === 'selection' ? '筛选信号数' : '信号数'} value={String(selectedSignals.length)} />
                    <MetricCard title={strategyType === 'selection' ? '执行订单数' : '订单数'} value={String(selectedOrders.length)} />
                    <MetricCard title={strategyType === 'selection' ? '执行成交数' : '成交数'} value={String(selectedTrades.length)} />
                    <MetricCard title="快照数" value={String(selectedSnapshots.length)} />
                  </div>
                )}
              </SectionCard>

              <SectionCard title={strategyType === 'selection' ? '入选时间链路' : '时间链路'} subtitle={strategyType === 'selection' ? '按事件发生顺序查看从候选到确认、再到筛选信号的过程。' : '按事件发生顺序查看单票决策过程'}>
                {selectedSymbol && (
                  <div className="mb-4 h-[460px]">
                    <KlinePanel
                      symbol={selectedSymbol}
                      onSymbolChange={setSelectedSymbol}
                      showChanlunOverlay={false}
                      focusDate={focusedEventDate}
                      markers={selectedSymbolMarkers}
                    />
                  </div>
                )}
                <div className="space-y-3">
                  {[
                    ...selectedWatchlists.map(item => ({ time: item.date, type: '候选池', text: `因子分 ${item.factor_score.toFixed(3)}，排名 ${item.rank}` })),
                    ...selectedMinuteConfirmations.map(item => ({ time: item.bar_end || item.date, type: '分钟确认', text: `${toChineseTimeframe(item.timeframe)} · ${item.confirmed ? '通过' : '未通过'}` })),
                    ...selectedSignals.map(item => ({ time: item.date, type: '信号', text: `${toChineseDirection(item.side)} · ${item.reason}` })),
                    ...selectedOrders.map(item => ({ time: item.execute_date || item.signal_date, type: '订单', text: `${toChineseDirection(item.side)} · ${toChineseOrderStatus(item.status)}` })),
                    ...selectedTrades.map(item => ({ time: item.timestamp, type: '成交', text: `${toChineseDirection(item.direction)} ${item.quantity} 股 @ ${item.price.toFixed(2)}` })),
                  ]
                    .sort((left, right) => String(right.time).localeCompare(String(left.time)))
                    .slice(0, 30)
                    .map((item, index) => (
                      <button
                        type="button"
                        onClick={() => setFocusedEventDate(String(item.time || '').slice(0, 10))}
                        key={`${item.type}_${item.time}_${index}`}
                        className={`w-full rounded-xl border p-3 text-left transition hover:border-blue-300 hover:bg-blue-50/40 dark:hover:border-blue-700 dark:hover:bg-blue-500/5 ${
                          String(item.time || '').slice(0, 10) === focusedEventDate ? 'border-blue-300 bg-blue-50/60 dark:border-blue-700 dark:bg-blue-500/10' : 'border-slate-100 dark:border-slate-800'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{item.type}</div>
                          <div className="text-xs text-slate-400">{formatDateTime(item.time)}</div>
                        </div>
                        <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">{item.text}</div>
                      </button>
                    ))}
                </div>
              </SectionCard>

              <div className="grid gap-6 xl:grid-cols-3">
                <SectionCard title={strategyType === 'selection' ? '候选与确认明细' : '成交与订单'} subtitle={strategyType === 'selection' ? '选股策略优先看候选分数、分钟确认和筛选命中。' : '适合看执行结果'}>
                  <div className="space-y-3">
                    {strategyType === 'selection' ? (
                      <>
                        {selectedWatchlists.slice(0, 8).map((item, index) => (
                          <div key={`${item.symbol}_${item.date}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                            <div className="font-medium text-slate-900 dark:text-slate-100">候选池 · 排名 {item.rank}</div>
                            <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDate(item.date)} · 因子分 {item.factor_score.toFixed(3)}</div>
                          </div>
                        ))}
                        {selectedMinuteConfirmations.slice(0, 8).map((item, index) => (
                          <div key={`${item.symbol}_${item.date}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                            <div className="font-medium text-slate-900 dark:text-slate-100">分钟确认 · {item.confirmed ? '通过' : '未通过'}</div>
                            <div className="mt-1 text-slate-500 dark:text-slate-400">{toChineseTimeframe(item.timeframe)} · {formatDateTime(item.bar_end || item.date)}</div>
                          </div>
                        ))}
                        {selectedWatchlists.length === 0 && selectedMinuteConfirmations.length === 0 && (
                          <div className="text-sm text-slate-500 dark:text-slate-400">暂无候选或分钟确认记录。</div>
                        )}
                      </>
                    ) : selectedOrders.length === 0 && selectedTrades.length === 0 ? (
                      <div className="text-sm text-slate-500 dark:text-slate-400">暂无订单或成交。</div>
                    ) : (
                      <>
                        {selectedOrders.slice(0, 10).map(item => (
                          <div key={item.order_id} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                            <div className="font-medium text-slate-900 dark:text-slate-100">{toChineseDirection(item.side)} · {toChineseOrderStatus(item.status)}</div>
                            <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDate(item.signal_date)} → {formatDate(item.execute_date)} · {item.reason}</div>
                          </div>
                        ))}
                        {selectedTrades.slice(0, 10).map(item => (
                          <div key={item.trade_id} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                            <div className="font-medium text-slate-900 dark:text-slate-100">{toChineseDirection(item.direction)} · {item.quantity} 股</div>
                            <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDateTime(item.timestamp)} · {item.price.toFixed(2)} · {item.reason}</div>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                </SectionCard>
                <SectionCard title={strategyType === 'selection' ? '筛选快照' : '持仓与快照'} subtitle={strategyType === 'selection' ? '适合看入选时的因子向量、排序特征和未来标签。' : '适合看仓位与快照归因'}>
                  <div className="space-y-3">
                    {strategyType !== 'selection' && selectedPositions.slice(0, 8).map((item, index) => (
                      <div key={`${item.symbol}_${item.date}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                        <div className="font-medium text-slate-900 dark:text-slate-100">{formatDate(item.date)} · 持仓 {item.quantity} 股</div>
                        <div className="mt-1 text-slate-500 dark:text-slate-400">均价 {item.avg_price.toFixed(2)} · 收盘 {item.close.toFixed(2)} · 市值 {formatAmount(item.market_value)}</div>
                      </div>
                    ))}
                    {selectedSnapshots.slice(0, 8).map((item, index) => (
                      <div key={`${item.trade_id}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                        <div className="font-medium text-slate-900 dark:text-slate-100">{formatDateTime(item.timestamp)} · {toChineseDirection(item.side)}</div>
                        <div className="mt-1 text-slate-500 dark:text-slate-400">{item.entry_reason || item.exit_reason || '无原因说明'}</div>
                      </div>
                    ))}
                    {((strategyType !== 'selection' && selectedPositions.length === 0 && selectedSnapshots.length === 0) || (strategyType === 'selection' && selectedSnapshots.length === 0)) && (
                      <div className="text-sm text-slate-500 dark:text-slate-400">{strategyType === 'selection' ? '暂无筛选快照。' : '暂无持仓或快照。'}</div>
                    )}
                  </div>
                </SectionCard>
                <SectionCard title={strategyType === 'selection' ? '当前单票入选诊断' : '当前单票诊断'} subtitle={strategyType === 'selection' ? '汇总最新候选、信号、分钟确认与快照原因。' : '汇总最新信号、订单、成交与快照原因'}>
                  <div className="space-y-4 text-sm">
                    {strategyType === 'selection' && (
                      <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                        <div className="text-xs text-slate-400">最新候选 / 分钟确认</div>
                        {(selectedWatchlists[0] || selectedMinuteConfirmations[0]) ? (
                          <div className="mt-2 space-y-2">
                            {selectedWatchlists[0] && (
                              <div>
                                <div className="font-medium text-slate-900 dark:text-slate-100">候选池 · 排名 {selectedWatchlists[0].rank}</div>
                                <div className="text-slate-500 dark:text-slate-400">{formatDate(selectedWatchlists[0].date)} · 因子分 {selectedWatchlists[0].factor_score.toFixed(3)}</div>
                              </div>
                            )}
                            {selectedMinuteConfirmations[0] && (
                              <div>
                                <div className="font-medium text-slate-900 dark:text-slate-100">分钟确认 · {selectedMinuteConfirmations[0].confirmed ? '通过' : '未通过'}</div>
                                <div className="text-slate-500 dark:text-slate-400">{toChineseTimeframe(selectedMinuteConfirmations[0].timeframe)} · {formatDateTime(selectedMinuteConfirmations[0].bar_end || selectedMinuteConfirmations[0].date)}</div>
                              </div>
                            )}
                          </div>
                        ) : <div className="mt-2 text-slate-400">暂无候选或分钟确认。</div>}
                      </div>
                    )}
                    <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                      <div className="text-xs text-slate-400">{strategyType === 'selection' ? '最新筛选信号' : '最新信号'}</div>
                      {latestSelectedSignal ? (
                        <div className="mt-2 space-y-1">
                          <div className="font-medium text-slate-900 dark:text-slate-100">
                            {toChineseDirection(latestSelectedSignal.side)} · {formatDateTime(latestSelectedSignal.date)}
                          </div>
                          <div className="text-slate-500 dark:text-slate-400">{latestSelectedSignal.reason || '无信号原因'}</div>
                          <div className="text-xs text-slate-400">因子分 {latestSelectedSignal.factor_score?.toFixed(3) ?? '--'}</div>
                        </div>
                      ) : <div className="mt-2 text-slate-400">暂无信号。</div>}
                    </div>
                    {strategyType !== 'selection' && (
                      <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                      <div className="text-xs text-slate-400">最新订单 / 成交</div>
                      {latestSelectedOrder || latestSelectedTrade ? (
                        <div className="mt-2 space-y-2">
                          {latestSelectedOrder && (
                            <div>
                              <div className="font-medium text-slate-900 dark:text-slate-100">
                                订单 · {toChineseDirection(latestSelectedOrder.side)} · {toChineseOrderStatus(latestSelectedOrder.status)}
                              </div>
                              <div className="text-slate-500 dark:text-slate-400">{latestSelectedOrder.reason || '无订单原因'}</div>
                              {latestSelectedOrder.reject_reason && (
                                <div className="text-amber-600 dark:text-amber-300">拒绝：{latestSelectedOrder.reject_reason}</div>
                              )}
                            </div>
                          )}
                          {latestSelectedTrade && (
                            <div>
                              <div className="font-medium text-slate-900 dark:text-slate-100">
                                成交 · {toChineseDirection(latestSelectedTrade.direction)} {latestSelectedTrade.quantity} 股 @ {latestSelectedTrade.price.toFixed(2)}
                              </div>
                              <div className="text-slate-500 dark:text-slate-400">{latestSelectedTrade.reason || '无成交原因'}</div>
                            </div>
                          )}
                        </div>
                      ) : <div className="mt-2 text-slate-400">暂无订单或成交。</div>}
                      </div>
                    )}
                    <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                      <div className="text-xs text-slate-400">最新快照归因</div>
                      {latestSelectedSnapshot ? (
                        <div className="mt-2 space-y-3">
                          <div className="font-medium text-slate-900 dark:text-slate-100">
                            {toChineseDirection(latestSelectedSnapshot.side)} · {formatDateTime(latestSelectedSnapshot.timestamp)}
                          </div>
                          <div className="text-slate-500 dark:text-slate-400">
                            {latestSelectedSnapshot.entry_reason || latestSelectedSnapshot.exit_reason || '无快照原因'}
                          </div>
                          <div>
                            <div className="mb-1 text-xs text-slate-400">因子向量</div>
                            <pre className="overflow-auto rounded-lg bg-slate-900/95 p-3 text-xs text-slate-100 dark:bg-slate-950">{JSON.stringify(latestSelectedSnapshot.factor_vector || {}, null, 2)}</pre>
                          </div>
                          <div>
                            <div className="mb-1 text-xs text-slate-400">排序特征 / 未来标签</div>
                            <pre className="overflow-auto rounded-lg bg-slate-900/95 p-3 text-xs text-slate-100 dark:bg-slate-950">{JSON.stringify({
                              ...(latestSelectedSnapshot.rank_features || {}),
                              ...(latestSelectedSnapshot.future_return_labels || {}),
                            }, null, 2)}</pre>
                          </div>
                        </div>
                      ) : <div className="mt-2 text-slate-400">暂无快照。</div>}
                    </div>
                  </div>
                </SectionCard>
              </div>
            </div>
          </div>
        )}

        {viewMode === 'dates' && (
          <div className="grid gap-6 xl:grid-cols-[320px_1fr]">
            <SectionCard title={strategyType === 'selection' ? '选股日期列表' : '交易日列表'} subtitle={strategyType === 'selection' ? '先选某一天，再看当天全市场候选池与分钟确认。' : '先选某一天，再看那天全市场发生了什么'}>
              <div className="max-h-[920px] space-y-3 overflow-y-auto pr-1">
                {dateCards.length === 0 ? (
                  <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">暂无日期结果。</div>
                ) : dateCards.map(item => {
                  const active = item.date === selectedDate
                  return (
                    <button
                      key={item.date}
                      onClick={() => setSelectedDate(item.date)}
                      className={`w-full rounded-xl border p-4 text-left ${active ? 'border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-500/10' : 'border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900'}`}
                    >
                      <div className="font-medium text-slate-900 dark:text-slate-100">{item.date}</div>
                      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        候选 {item.watchlistCount} / 确认 {item.minuteCount} / 信号 {item.signalCount} / 订单 {item.orderCount} / 成交 {item.tradeCount}
                      </div>
                    </button>
                  )
                })}
              </div>
            </SectionCard>

            <div className="space-y-6">
              <SectionCard title={selectedDate ? `${selectedDate} 当日总览` : '当日总览'} subtitle={strategyType === 'selection' ? '优先排查当天的候选池覆盖、分钟确认和筛选命中。' : '适合排查某天从候选池到成交的全链路'}>
                {!selectedDate ? (
                  <div className="text-sm text-slate-500 dark:text-slate-400">请选择一个交易日。</div>
                ) : (
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
                    <MetricCard title="候选池数" value={String(selectedDateWatchlists.length)} />
                    <MetricCard title="分钟确认数" value={String(selectedDateMinuteConfirmations.length)} />
                    <MetricCard title={strategyType === 'selection' ? '筛选信号数' : '信号数'} value={String(selectedDateSignals.length)} />
                    <MetricCard title={strategyType === 'selection' ? '订单数' : '订单数'} value={String(selectedDateOrders.length)} />
                    <MetricCard title={strategyType === 'selection' ? '成交数' : '成交数'} value={String(selectedDateTrades.length)} />
                    <MetricCard title={strategyType === 'selection' ? '持仓/快照数' : '持仓快照数'} value={String(selectedDatePositions.length)} />
                  </div>
                )}
              </SectionCard>

              <div className="grid gap-6 xl:grid-cols-2">
                <SectionCard title="当日候选与确认" subtitle={strategyType === 'selection' ? '这是选股策略最核心的日级视角。' : '先看候选池，再看分钟确认是否通过'}>
                  <div className="space-y-3">
                    {selectedDateWatchlists.slice(0, 20).map((item, index) => (
                      <div key={`${item.symbol}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                        <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 候选池</div>
                        <div className="mt-1 text-slate-500 dark:text-slate-400">因子分 {item.factor_score.toFixed(3)} · 排名 {item.rank}</div>
                      </div>
                    ))}
                    {selectedDateMinuteConfirmations.slice(0, 20).map((item, index) => (
                      <div key={`${item.symbol}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                        <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 分钟确认</div>
                        <div className="mt-1 text-slate-500 dark:text-slate-400">{toChineseTimeframe(item.timeframe)} · {item.confirmed ? '通过' : '未通过'} · {formatDateTime(item.bar_end || item.date)}</div>
                      </div>
                    ))}
                    {selectedDateWatchlists.length === 0 && selectedDateMinuteConfirmations.length === 0 && (
                      <div className="text-sm text-slate-500 dark:text-slate-400">当天没有候选或分钟确认记录。</div>
                    )}
                  </div>
                </SectionCard>

                <SectionCard title={strategyType === 'selection' ? '当日筛选信号与执行' : '当日信号与执行'} subtitle={strategyType === 'selection' ? '先看筛选信号，订单和成交仅在交易型模式下重点关注。' : '再看信号、订单和成交是否落地'}>
                  <div className="space-y-3">
                    {selectedDateSignals.slice(0, 20).map((item, index) => (
                      <div key={`${item.symbol}_${item.side}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                        <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 信号</div>
                        <div className="mt-1 text-slate-500 dark:text-slate-400">{toChineseDirection(item.side)} · {item.reason}</div>
                      </div>
                    ))}
                    {selectedDateOrders.slice(0, 20).map(item => (
                      <div key={item.order_id} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                        <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 订单</div>
                        <div className="mt-1 text-slate-500 dark:text-slate-400">{toChineseDirection(item.side)} · {toChineseOrderStatus(item.status)} · {item.reason}</div>
                      </div>
                    ))}
                    {selectedDateTrades.slice(0, 20).map(item => (
                      <div key={item.trade_id} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                        <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 成交</div>
                        <div className="mt-1 text-slate-500 dark:text-slate-400">{toChineseDirection(item.direction)} {item.quantity} 股 @ {item.price.toFixed(2)}</div>
                      </div>
                    ))}
                    {selectedDateSignals.length === 0 && selectedDateOrders.length === 0 && selectedDateTrades.length === 0 && (
                      <div className="text-sm text-slate-500 dark:text-slate-400">当天没有信号、订单或成交记录。</div>
                    )}
                  </div>
                </SectionCard>
              </div>
            </div>
          </div>
        )}

        {viewMode === 'flows' && (
          <div className="grid gap-6 xl:grid-cols-2">
            <SectionCard title={strategyType === 'selection' ? '候选池、分钟确认与筛选信号' : '候选池与分钟确认'} subtitle={strategyType === 'selection' ? '选股策略优先查看候选池、分钟确认和筛选信号流水。' : '保留原来的流水视角，适合做排查'}>
              <div className="space-y-3">
                {watchlists.slice(0, 20).map((item, index) => (
                  <div key={`${item.symbol}_${item.date}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                    <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 候选池</div>
                    <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDate(item.date)} · 分数 {item.factor_score.toFixed(3)} · 排名 {item.rank}</div>
                  </div>
                ))}
                {minuteConfirmations.slice(0, 20).map((item, index) => (
                  <div key={`${item.symbol}_${item.date}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                    <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 分钟确认</div>
                    <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDateTime(item.bar_end || item.date)} · {toChineseTimeframe(item.timeframe)} · {item.confirmed ? '通过' : '未通过'}</div>
                  </div>
                ))}
                {strategyType === 'selection' && signals.slice(0, 20).map((item, index) => (
                  <div key={`${item.symbol}_${item.date}_${index}_signal`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                    <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 筛选信号</div>
                    <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDate(item.date)} · {toChineseDirection(item.side)} · {item.reason}</div>
                  </div>
                ))}
                {watchlists.length === 0 && minuteConfirmations.length === 0 && (strategyType !== 'selection' || signals.length === 0) && (
                  <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">暂无候选、分钟确认或筛选信号流水。</div>
                )}
              </div>
            </SectionCard>
            {strategyType === 'selection' ? (
              <SectionCard title="执行结果（如有）" subtitle="只有在选股策略以交易型模式运行时，这里才会出现真实订单和成交。">
                {hasSelectionExecutionData ? (
                  <details className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-950">
                    <summary className="cursor-pointer list-none font-medium text-slate-700 dark:text-slate-200">展开查看订单与成交流水</summary>
                    <div className="mt-3 space-y-3">
                      {orders.slice(0, 20).map(item => (
                        <div key={item.order_id} className="rounded-xl bg-white p-3 text-sm dark:bg-slate-900">
                          <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 订单</div>
                          <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDate(item.execute_date)} · {toChineseDirection(item.side)} · {toChineseOrderStatus(item.status)}</div>
                        </div>
                      ))}
                      {trades.slice(0, 20).map(item => (
                        <div key={item.trade_id} className="rounded-xl bg-white p-3 text-sm dark:bg-slate-900">
                          <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 成交</div>
                          <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDateTime(item.timestamp)} · {toChineseDirection(item.direction)} {item.quantity} 股 @ {item.price.toFixed(2)}</div>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : (
                  <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">当前没有真实执行数据；这说明本次更偏向候选池 / 选股链路验证。</div>
                )}
              </SectionCard>
            ) : (
              <SectionCard title="信号、订单、成交" subtitle="按流水看策略执行过程">
                <div className="space-y-3">
                  {signals.slice(0, 20).map((item, index) => (
                    <div key={`${item.symbol}_${item.date}_${index}`} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                      <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 信号</div>
                      <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDate(item.date)} · {toChineseDirection(item.side)} · {item.reason}</div>
                    </div>
                  ))}
                  {orders.slice(0, 20).map(item => (
                    <div key={item.order_id} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                      <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 订单</div>
                      <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDate(item.execute_date)} · {toChineseDirection(item.side)} · {toChineseOrderStatus(item.status)}</div>
                    </div>
                  ))}
                  {trades.slice(0, 20).map(item => (
                    <div key={item.trade_id} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-950">
                      <div className="font-medium text-slate-900 dark:text-slate-100">{item.symbol} · 成交</div>
                      <div className="mt-1 text-slate-500 dark:text-slate-400">{formatDateTime(item.timestamp)} · {toChineseDirection(item.direction)} {item.quantity} 股 @ {item.price.toFixed(2)}</div>
                    </div>
                  ))}
                </div>
              </SectionCard>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
