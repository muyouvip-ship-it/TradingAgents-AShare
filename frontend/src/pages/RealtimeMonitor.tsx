import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, Bot, Play, Plus, Power, RefreshCw, TimerReset, Trash2, Waves, X } from 'lucide-react'

import { api } from '@/services/api'
import type {
  RealtimeEvent,
  RealtimeMonitor,
  RealtimeMonitorPositionsResponse,
  StrategyDefinition,
  VirtualWarehouseOverviewResponse,
} from '@/types'

type ControlAction = 'start' | 'pause' | 'stop' | 'resume' | 'fuse-reset'

function formatDateTime(value?: string | null) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function formatNumber(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '--'
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatPercent(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '--'
  return `${(value * 100).toFixed(2)}%`
}

function formatPrice(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '--'
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatCurrency(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '--'
  const amount = Math.abs(value)
  const prefix = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${prefix}¥${formatPrice(amount)}`
}

function pnlTone(value?: number | null) {
  if (value == null || Number.isNaN(value) || value === 0) return 'text-slate-600 dark:text-slate-300'
  return value > 0 ? 'text-rose-600 dark:text-rose-300' : 'text-emerald-600 dark:text-emerald-300'
}

function parseSseBlock(block: string): { event: string; data: Record<string, unknown> } | null {
  const lines = block.split('\n')
  let event = 'message'
  const dataLines: string[] = []
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.replace('event:', '').trim()
    if (line.startsWith('data:')) dataLines.push(line.replace('data:', '').trim())
  }
  if (!dataLines.length) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) as Record<string, unknown> }
  } catch {
    return null
  }
}

function statusLabel(status: string) {
  return {
    draft: '草稿',
    ready: '就绪',
    running: '运行中',
    paused: '已暂停',
    halted: '已停机',
    fused: '已熔断',
    error: '异常',
  }[status] || status
}

function statusTone(status: string) {
  return {
    running: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
    ready: 'bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300',
    paused: 'bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
    halted: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
    fused: 'bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
    error: 'bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
  }[status] || 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
}

function eventLabel(eventType: string) {
  return {
    monitor_created: '实例已创建',
    monitor_started: '实例已启动',
    monitor_paused: '实例已暂停',
    monitor_stopped: '实例已停机',
    monitor_resumed: '实例已恢复',
    monitor_fused: '实例已熔断',
    cycle_started: '开始新一轮扫描',
    cycle_skipped: '本轮已跳过',
    market_snapshot: '行情快照',
    minute_features: '分钟特征',
    signal_generated: '生成交易信号',
    order_intent: '生成委托意图',
    order_submitted: '委托已提交',
    order_snapshot_refreshed: '委托快照刷新',
    order_status_changed: '委托状态变化',
    order_cancel_requested: '触发自动撤单',
    order_cancelled: '撤单已确认',
    order_cancel_error: '撤单异常',
    order_replace_requested: '触发自动补单',
    order_rejected: '委托被拒绝',
    order_error: '委托执行异常',
    trade_confirmed: '成交已确认',
    position_changed: '持仓变化',
    execution_tracker_initialized: '执行追踪已初始化',
    approval_created: '进入人工确认',
    approval_executed: '人工确认后执行',
    approval_rejected: '人工确认已拒绝',
    no_signal: '本轮无信号',
    fuse_reset: '熔断已解除',
    live_readonly_guard: '实盘只读保护',
  }[eventType] || eventType
}

function timeframeLabel(value?: string | null) {
  if (!value) return '--'
  const normalized = String(value).toLowerCase()
  return {
    '1m': '1 分钟',
    '5m': '5 分钟',
    '15m': '15 分钟',
    '30m': '30 分钟',
    '60m': '60 分钟',
    '1d': '日线',
    '1w': '周线',
  }[normalized] || value
}

function eventTone(eventType: string) {
  if (['monitor_fused', 'order_error', 'order_rejected', 'order_cancel_error'].includes(eventType)) {
    return 'border-rose-200 bg-rose-50/70 dark:border-rose-500/30 dark:bg-rose-500/10'
  }
  if (['signal_generated', 'approval_executed', 'trade_confirmed', 'order_submitted'].includes(eventType)) {
    return 'border-emerald-200 bg-emerald-50/70 dark:border-emerald-500/30 dark:bg-emerald-500/10'
  }
  if (['minute_features', 'minute_capture', 'market_snapshot', 'cycle_started'].includes(eventType)) {
    return 'border-blue-200 bg-blue-50/70 dark:border-blue-500/30 dark:bg-blue-500/10'
  }
  if (['no_signal', 'cycle_skipped'].includes(eventType)) {
    return 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-950'
  }
  return 'border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900'
}

function eventTagLabel(eventType: string) {
  if (['minute_features', 'minute_capture', 'market_snapshot'].includes(eventType)) return '分钟判定'
  if (['signal_generated', 'order_intent', 'order_submitted', 'trade_confirmed'].includes(eventType)) return '交易执行'
  if (['monitor_fused', 'order_error', 'order_rejected', 'order_cancel_error'].includes(eventType)) return '风险异常'
  if (['position_changed', 'execution_tracker_initialized'].includes(eventType)) return '账户跟踪'
  return '运行事件'
}

function signalSideLabel(value?: string | null) {
  if (!value) return '--'
  const normalized = String(value).toLowerCase()
  return {
    buy: '买入',
    sell: '卖出',
    hold: '继续观察',
  }[normalized] || value
}

function eventSide(item: RealtimeEvent) {
  return String(item.order_payload?.side || item.signal_payload?.side || item.payload?.side || '').toLowerCase()
}

function eventSideTone(item: RealtimeEvent) {
  const side = eventSide(item)
  if (side === 'buy') return 'bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300'
  if (side === 'sell') return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'
  if (item.event_type === 'monitor_fused' || item.event_type === 'order_error' || item.event_type === 'order_rejected') {
    return 'bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300'
  }
  return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
}

function eventSideLabel(item: RealtimeEvent) {
  const side = eventSide(item)
  if (side === 'buy') return '买入'
  if (side === 'sell') return '卖出'
  if (item.event_type === 'trade_confirmed') return '成交'
  if (item.event_type === 'order_rejected' || item.event_type === 'order_error') return '异常'
  return '跟踪'
}

function eventAccent(item: RealtimeEvent) {
  const side = eventSide(item)
  if (side === 'buy') return 'border-l-rose-500'
  if (side === 'sell') return 'border-l-emerald-500'
  if (['monitor_fused', 'order_error', 'order_rejected', 'order_cancel_error'].includes(item.event_type)) return 'border-l-amber-500'
  return 'border-l-blue-500'
}

function eventMetricLine(item: RealtimeEvent) {
  const quantity = Number(item.order_payload?.quantity || item.broker_result?.quantity || item.payload?.quantity || NaN)
  const price = Number(item.order_payload?.price || item.broker_result?.price || item.payload?.price || NaN)
  const priceType = String(item.order_payload?.price_type || item.payload?.price_type || '').trim()
  const fields: string[] = []
  if (Number.isFinite(quantity)) fields.push(`${formatNumber(quantity)} 股`)
  if (Number.isFinite(price)) fields.push(`¥${formatPrice(price)}`)
  if (priceType) fields.push(priceType)
  return fields.join(' / ')
}

function getEventSummary(item: RealtimeEvent) {
  const payload = item.payload || {}
  if (item.event_type === 'minute_capture') {
    const success = Boolean(payload.success)
    const rows = Number(payload.rows || 0)
    const source = String(payload.source || '--')
    return success
      ? `已抓取真实分钟线 ${formatNumber(rows)} 条，来源 ${source}`
      : `分钟线抓取失败：${String(payload.message || '未知原因')}`
  }

  if (item.event_type === 'minute_features') {
    const timeframe = timeframeLabel(String(payload.timeframe || ''))
    const source = String(payload.source || '--')
    const first = Array.isArray(payload.items) ? payload.items[0] as Record<string, unknown> | undefined : undefined
    if (!first) return `${timeframe} 特征已更新，来源 ${source}`
    const signal = signalSideLabel(String(first.signal || 'hold'))
    const crossAbove = Boolean(first.cross_above)
    const crossBelow = Boolean(first.cross_below)
    const crossText = crossAbove ? '金叉成立' : crossBelow ? '死叉成立' : '尚未交叉'
    return `${timeframe} 波段判定：${signal}（${crossText}）`
  }

  if (item.event_type === 'signal_generated') {
    const side = signalSideLabel(String(item.signal_payload?.side || ''))
    const reason = String(item.signal_payload?.reason || item.payload?.reason || '--')
    return `产生${side}信号，原因：${reason}`
  }

  if (item.event_type === 'no_signal') {
    return '本轮未满足买卖条件'
  }

  if (item.event_type === 'order_submitted') {
    return `委托已发出：${signalSideLabel(String(item.order_payload?.side || ''))} ${formatNumber(Number(item.order_payload?.quantity || 0))} 股`
  }

  if (item.event_type === 'position_changed') {
    const current = item.payload?.current as Record<string, unknown> | undefined
    if (current) {
      return `持仓变动：${String(current.name || item.symbol || '--')}，持仓 ${formatNumber(Number(current.current_position || 0))} 股`
    }
  }

  if (item.event_type === 'monitor_fused') {
    return `实例熔断：${String(item.error_payload?.reason || item.payload?.reason || '--')}`
  }

  return ''
}

function renderEventDetail(item: RealtimeEvent) {
  const payload = item.payload || {}

  if (item.event_type === 'minute_features') {
    const first = Array.isArray(payload.items) ? payload.items[0] as Record<string, unknown> | undefined : undefined
    if (!first) return null
    return (
      <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-950 dark:text-slate-300">
        <div>周期：{timeframeLabel(String(payload.timeframe || ''))} ｜ 数据源：{String(payload.source || '--')}</div>
        <div className="mt-1">
          波段：{formatPrice(Number(first.first_day_band || NaN))} ｜ B1：{formatPrice(Number(first.first_day_band_b1 || NaN))}
        </div>
        <div className="mt-1">
          判定：{signalSideLabel(String(first.signal || 'hold'))}
          {Boolean(first.cross_above) ? '（金叉）' : Boolean(first.cross_below) ? '（死叉）' : '（未交叉）'}
        </div>
        <div className="mt-1">
          K 线：{formatPrice(Number(first.open || NaN))} / {formatPrice(Number(first.high || NaN))} / {formatPrice(Number(first.low || NaN))} / {formatPrice(Number(first.close || NaN))}
        </div>
      </div>
    )
  }

  if (item.event_type === 'minute_capture') {
    return (
      <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-950 dark:text-slate-300">
        <div>交易日：{String(payload.trade_date || '--')} ｜ 数据源：{String(payload.source || '--')}</div>
        <div className="mt-1">写入条数：{formatNumber(Number(payload.rows || 0))}</div>
      </div>
    )
  }

  if (item.event_type === 'signal_generated') {
    return (
      <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-950 dark:text-slate-300">
        <div>方向：{signalSideLabel(String(item.signal_payload?.side || ''))}</div>
        <div className="mt-1">原因：{String(item.signal_payload?.reason || '--')}</div>
        <div className="mt-1">目标仓位：{formatPercent(Number(item.signal_payload?.target_position_pct ?? NaN))}</div>
      </div>
    )
  }

  return null
}

export default function RealtimeMonitorPage() {
  const [strategies, setStrategies] = useState<StrategyDefinition[]>([])
  const [warehouse, setWarehouse] = useState<VirtualWarehouseOverviewResponse | null>(null)
  const [monitors, setMonitors] = useState<RealtimeMonitor[]>([])
  const [selectedMonitorId, setSelectedMonitorId] = useState<string | null>(null)
  const [selectedMonitor, setSelectedMonitor] = useState<RealtimeMonitor | null>(null)
  const [events, setEvents] = useState<RealtimeEvent[]>([])
  const [positionsPayload, setPositionsPayload] = useState<RealtimeMonitorPositionsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [actioning, setActioning] = useState<ControlAction | null>(null)
  const [runningOnce, setRunningOnce] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [streamStatus, setStreamStatus] = useState('未连接')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<RealtimeMonitor | null>(null)
  const streamAbortRef = useRef<AbortController | null>(null)

  const [form, setForm] = useState({
    name: '',
    strategy_id: '',
    account_key: 'paper_sim',
    execution_mode: 'auto',
    manual_symbols: '',
    poll_interval_seconds: 20,
    max_signals_per_cycle: 3,
  })

  const accountOptions = warehouse?.accounts || []
  const selectedAccountRole = useMemo(
    () => accountOptions.find(item => item.account_key === form.account_key)?.role || 'paper',
    [accountOptions, form.account_key],
  )

  const loadMonitors = useCallback(async () => {
    const response = await api.getRealtimeMonitors()
    setMonitors(response.items || [])
    setSelectedMonitorId(current => current || response.items?.[0]?.id || null)
  }, [])

  const loadDetail = useCallback(async (monitorId: string) => {
    const [monitor, eventRes, positionRes] = await Promise.all([
      api.getRealtimeMonitor(monitorId),
      api.getRealtimeMonitorEvents(monitorId, { limit: 100 }),
      api.getRealtimeMonitorPositions(monitorId),
    ])
    setSelectedMonitor(monitor)
    setEvents(eventRes.items || [])
    setPositionsPayload(positionRes)
  }, [])

  const loadPage = useCallback(async (silent = false, preferredMonitorId?: string | null) => {
    try {
      if (silent) setRefreshing(true)
      else setLoading(true)
      const [strategyRes, warehouseRes, monitorRes] = await Promise.all([
        api.getStrategyPlatformList(),
        api.getQmtVirtualWarehouseOverview(),
        api.getRealtimeMonitors(),
      ])
      setStrategies(strategyRes.strategies || [])
      setWarehouse(warehouseRes)
      setMonitors(monitorRes.items || [])

      const nextMonitorId =
        preferredMonitorId === undefined
          ? (selectedMonitorId || monitorRes.items?.[0]?.id || null)
          : (preferredMonitorId || monitorRes.items?.[0]?.id || null)
      if (!form.strategy_id && strategyRes.strategies?.[0]?.id) {
        setForm(current => ({ ...current, strategy_id: strategyRes.strategies[0].id }))
      }
      if (!form.account_key && warehouseRes.accounts?.[0]?.account_key) {
        setForm(current => ({ ...current, account_key: warehouseRes.accounts[0].account_key }))
      }
      setSelectedMonitorId(nextMonitorId)
      if (nextMonitorId) await loadDetail(nextMonitorId)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '实时监控页加载失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [form.account_key, form.strategy_id, loadDetail, selectedMonitorId])

  useEffect(() => {
    void loadPage()
  }, [loadPage])

  useEffect(() => {
    if (!selectedMonitorId) return
    void loadDetail(selectedMonitorId)
  }, [loadDetail, selectedMonitorId])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadMonitors()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [loadMonitors])

  useEffect(() => {
    if (!selectedMonitorId) {
      streamAbortRef.current?.abort()
      setStreamStatus('未连接')
      return
    }
    const controller = new AbortController()
    streamAbortRef.current?.abort()
    streamAbortRef.current = controller
    setStreamStatus('连接中...')

    const startStream = async () => {
      try {
        const response = await api.streamRealtimeMonitor(selectedMonitorId, {
          initial_limit: 20,
          signal: controller.signal,
        })
        if (!response.body) throw new Error('实时监控流不可用')
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        setStreamStatus('实时追踪中')

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const blocks = buffer.split('\n\n')
          buffer = blocks.pop() || ''
          for (const block of blocks) {
            const parsed = parseSseBlock(block)
            if (!parsed) continue
            if (parsed.event === 'ready') {
              setStreamStatus('实时追踪中')
              continue
            }
            if (parsed.event === 'state') {
              const monitor = parsed.data.monitor as RealtimeMonitor | undefined
              if (monitor?.id) {
                setSelectedMonitor(monitor)
                setMonitors(current => current.map(item => (item.id === monitor.id ? monitor : item)))
              }
              continue
            }
            if (parsed.event === 'event') {
              const item = parsed.data.item as RealtimeEvent | undefined
              if (!item?.id) continue
              setEvents(current => {
                const merged = [...current.filter(row => row.id !== item.id), item]
                return merged.sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || ''))).slice(-200)
              })
              if ([
                'order_submitted',
                'order_rejected',
                'order_error',
                'order_status_changed',
                'order_cancel_requested',
                'order_cancelled',
                'order_cancel_error',
                'order_replace_requested',
                'trade_confirmed',
                'position_changed',
                'approval_created',
                'approval_executed',
                'approval_rejected',
              ].includes(item.event_type)) {
                void loadDetail(selectedMonitorId)
              }
            }
          }
        }
        if (!controller.signal.aborted) setStreamStatus('连接已断开')
      } catch (err) {
        if (controller.signal.aborted) return
        setStreamStatus('连接失败')
        setError(err instanceof Error ? err.message : '实时流连接失败')
      }
    }

    void startStream()
    return () => controller.abort()
  }, [loadDetail, selectedMonitorId])

  const handleCreate = useCallback(async () => {
    if (!form.strategy_id) {
      setError('请先选择策略')
      return
    }
    setSubmitting(true)
    setMessage(null)
    try {
      const manualSymbols = form.manual_symbols
        .split(/[\s,，;；]+/)
        .map(item => item.trim().toUpperCase())
        .filter(Boolean)
      const payload = await api.createRealtimeMonitor({
        name: form.name || undefined,
        strategy_id: form.strategy_id,
        account_key: form.account_key,
        execution_mode: selectedAccountRole === 'live' ? 'monitor_only' : (form.execution_mode as 'auto' | 'monitor_only'),
        live_trading_enabled: false,
        live_confirmed: false,
        monitor_pool: {
          mode: 'strategy_positions_watchlist',
          manual_symbols: manualSymbols,
          symbols: manualSymbols,
        },
        config: {
          poll_interval_seconds: Number(form.poll_interval_seconds),
          max_signals_per_cycle: Number(form.max_signals_per_cycle),
        },
      })
      setSelectedMonitorId(payload.id)
      setMessage('实时监控实例已创建')
      setShowCreateModal(false)
      await loadPage(true, payload.id)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建实时监控失败')
    } finally {
      setSubmitting(false)
    }
  }, [form, loadPage, selectedAccountRole])

  const handleControl = useCallback(async (action: ControlAction, monitorId?: string) => {
    const currentMonitorId = monitorId || selectedMonitorId
    if (!currentMonitorId) return
    setActioning(action)
    setMessage(null)
    try {
      let result: RealtimeMonitor
      if (action === 'start') result = await api.startRealtimeMonitor(currentMonitorId)
      else if (action === 'pause') result = await api.pauseRealtimeMonitor(currentMonitorId)
      else if (action === 'stop') result = await api.stopRealtimeMonitor(currentMonitorId)
      else if (action === 'resume') result = await api.resumeRealtimeMonitor(currentMonitorId)
      else result = await api.resetRealtimeMonitorFuse(currentMonitorId)
      if (selectedMonitorId === currentMonitorId) {
        setSelectedMonitor(result)
      }
      setMonitors(current => current.map(item => (item.id === result.id ? result : item)))
      if (selectedMonitorId === currentMonitorId) {
        await loadDetail(currentMonitorId)
      }
      setMessage(`监控实例已${statusLabel(result.status)}`)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setActioning(null)
    }
  }, [loadDetail, selectedMonitorId])

  const handleRunOnce = useCallback(async () => {
    if (!selectedMonitorId) return
    setRunningOnce(true)
    setMessage(null)
    try {
      const result = await api.runRealtimeMonitorOnce(selectedMonitorId)
      setSelectedMonitor(result.monitor)
      setMonitors(current => current.map(item => (item.id === result.monitor.id ? result.monitor : item)))
      setEvents(result.events || [])
      await loadDetail(selectedMonitorId)
      setMessage('已手动执行一轮实时监控')
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '手动执行监控失败')
    } finally {
      setRunningOnce(false)
    }
  }, [loadDetail, selectedMonitorId])

  const handleDeleteMonitor = useCallback(async () => {
    if (!deleteTarget) return
    setSubmitting(true)
    setMessage(null)
    try {
      const deletedId = deleteTarget.id
      const result = await api.deleteRealtimeMonitor(deletedId)
      setDeleteTarget(null)
      setSelectedMonitorId(current => (current === deletedId ? null : current))
      if (selectedMonitorId === deletedId) {
        setSelectedMonitor(null)
        setEvents([])
        setPositionsPayload(null)
      }
      await loadPage(true, null)
      setMessage(result.message)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除监控实例失败')
    } finally {
      setSubmitting(false)
    }
  }, [deleteTarget, loadPage, selectedMonitorId])

  const selectedStrategy = useMemo(
    () => strategies.find(item => item.id === form.strategy_id) || null,
    [form.strategy_id, strategies],
  )
  const strategyMap = useMemo(
    () => new Map(strategies.map(item => [item.id, item])),
    [strategies],
  )
  const accountSummaryMap = useMemo(
    () => new Map((warehouse?.accounts || []).map(item => [item.account_key, item.account || null])),
    [warehouse?.accounts],
  )

  const getMonitorAccount = useCallback((monitor: RealtimeMonitor) => {
    return accountSummaryMap.get(monitor.account_key) || null
  }, [accountSummaryMap])

  const getMonitorStrategy = useCallback((monitor: RealtimeMonitor) => {
    return strategyMap.get(monitor.strategy_id) || null
  }, [strategyMap])

  const getMonitorTodayPct = useCallback((monitor: RealtimeMonitor) => {
    const account = getMonitorAccount(monitor)
    if (!account) return null
    const base = Number(account.total_asset || 0) - Number(account.today_pnl || 0)
    if (!Number.isFinite(base) || base <= 0) return null
    return Number(account.today_pnl || 0) / base
  }, [getMonitorAccount])

  const getMonitorDrawdown = useCallback((monitor: RealtimeMonitor) => {
    const strategy = getMonitorStrategy(monitor)
    const strategyDrawdown = strategy?.performance?.max_drawdown
    if (typeof strategyDrawdown === 'number' && !Number.isNaN(strategyDrawdown)) return strategyDrawdown
    const riskDrawdown = Number(monitor.risk_config?.max_drawdown_pct ?? NaN)
    if (Number.isFinite(riskDrawdown)) return -Math.abs(riskDrawdown)
    return null
  }, [getMonitorStrategy])

  const strategyPositions = useMemo(
    () => (positionsPayload?.positions || []).slice().sort((a, b) => Number(b.market_value || 0) - Number(a.market_value || 0)),
    [positionsPayload?.positions],
  )

  const eventFlowItems = useMemo(() => {
    const tradeEventTypes = new Set([
      'signal_generated',
      'order_intent',
      'order_submitted',
      'order_status_changed',
      'order_cancel_requested',
      'order_cancelled',
      'order_rejected',
      'order_error',
      'trade_confirmed',
      'position_changed',
      'monitor_fused',
    ])
    return [...events]
      .reverse()
      .filter(item => tradeEventTypes.has(item.event_type))
      .slice(0, 40)
  }, [events])

  if (loading) {
    return <div className="rounded-2xl border border-slate-200 bg-white p-8 text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-900">实时监控模块加载中...</div>
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">
              <Waves className="h-4 w-4" />
              QMT 实时监控与自动交易
            </div>
            <h1 className="mt-3 text-2xl font-bold text-slate-900 dark:text-white">实时监控总控台</h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              先跑通虚拟仓全自动，实盘默认只监控；所有信号、风控、委托、成交都保留事件回放。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => void loadPage(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
              刷新
            </button>
            <div className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              <span className={`h-2 w-2 rounded-full ${streamStatus === '实时追踪中' ? 'bg-emerald-500' : streamStatus === '连接中...' ? 'bg-amber-500' : 'bg-slate-400'}`} />
              流状态：{streamStatus}
            </div>
          </div>
        </div>
        {error ? (
          <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
            {error}
          </div>
        ) : null}
        {message ? (
          <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
            {message}
          </div>
        ) : null}
      </section>

      <div className="space-y-4">
        <section className="space-y-4">
          <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <div className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-white">
                    <Activity className="h-5 w-5 text-emerald-500" />
                    监控实例列表
                  </div>
                  <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">选择实例后，下方查看策略持仓和股票交易事件流动。</div>
                </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => setShowCreateModal(true)} className="rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300"><Plus className="mr-1 inline h-4 w-4" />新建监控</button>
                <button onClick={() => void handleRunOnce()} disabled={!selectedMonitorId || runningOnce} className="rounded-xl bg-indigo-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"><Activity className="mr-1 inline h-4 w-4" />{runningOnce ? '执行中' : '立即跑一轮'}</button>
                <button onClick={() => void handleControl('fuse-reset')} disabled={!selectedMonitorId || !!actioning} className="rounded-xl bg-rose-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"><TimerReset className="mr-1 inline h-4 w-4" />解除熔断</button>
              </div>
            </div>

            <div className="mt-4 grid gap-3 2xl:grid-cols-2">
              {monitors.length ? monitors.map(item => (
                <div
                  key={item.id}
                  onClick={() => setSelectedMonitorId(item.id)}
                  className={`cursor-pointer rounded-2xl border p-4 text-left transition ${
                    item.id === selectedMonitorId
                      ? 'border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-500/10'
                      : 'border-slate-200 bg-slate-50 hover:bg-white dark:border-slate-700 dark:bg-slate-950 dark:hover:bg-slate-900'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-900 dark:text-white">{item.name}</div>
                      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        账户：{item.account_key} ｜ 模式：{item.execution_mode === 'auto' ? '自动交易' : '仅监控'}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        {item.account_role === 'paper' ? '虚拟仓' : '实盘'}
                      </span>
                      <span className={`rounded-full px-2 py-1 text-[11px] ${statusTone(item.status)}`}>{statusLabel(item.status)}</span>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-2xl bg-white/80 px-3 py-3 dark:bg-slate-900/70">
                      <div className="text-[11px] tracking-[0.16em] text-slate-400">今日收益</div>
                      <div className={`mt-2 text-sm font-semibold ${pnlTone(getMonitorAccount(item)?.today_pnl)}`}>
                        {formatPercent(getMonitorTodayPct(item))} ｜ {formatCurrency(getMonitorAccount(item)?.today_pnl)}
                      </div>
                    </div>
                    <div className="rounded-2xl bg-white/80 px-3 py-3 dark:bg-slate-900/70">
                      <div className="text-[11px] tracking-[0.16em] text-slate-400">累计收益</div>
                      <div className={`mt-2 text-sm font-semibold ${pnlTone(getMonitorAccount(item)?.total_pnl)}`}>
                        {formatPercent((getMonitorAccount(item)?.total_pnl_pct ?? null) != null ? Number(getMonitorAccount(item)?.total_pnl_pct) / 100 : null)} ｜ {formatCurrency(getMonitorAccount(item)?.total_pnl)}
                      </div>
                    </div>
                    <div className="rounded-2xl bg-white/80 px-3 py-3 dark:bg-slate-900/70">
                      <div className="text-[11px] tracking-[0.16em] text-slate-400">最大回撤</div>
                      <div className="mt-2 text-sm font-semibold text-slate-900 dark:text-white">
                        {formatPercent(getMonitorDrawdown(item))}
                      </div>
                    </div>
                    <div className="rounded-2xl bg-white/80 px-3 py-3 dark:bg-slate-900/70">
                      <div className="text-[11px] tracking-[0.16em] text-slate-400">持仓数量</div>
                      <div className="mt-2 text-sm font-semibold text-slate-900 dark:text-white">
                        {formatNumber(getMonitorAccount(item)?.position_count)}
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      最后心跳：{formatDateTime(item.last_heartbeat_at)}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={event => {
                          event.stopPropagation()
                          void handleControl('start', item.id)
                        }}
                        disabled={!!actioning || item.status === 'running' || item.status === 'fused'}
                        className="rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-60"
                      >
                        <Play className="mr-1 inline h-3.5 w-3.5" />
                        启动
                      </button>
                      <button
                        onClick={event => {
                          event.stopPropagation()
                          void handleControl('stop', item.id)
                        }}
                        disabled={!!actioning || item.status === 'halted'}
                        className="rounded-xl bg-slate-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-60"
                      >
                        <Power className="mr-1 inline h-3.5 w-3.5" />
                        停止
                      </button>
                      <button
                        onClick={event => {
                          event.stopPropagation()
                          setDeleteTarget(item)
                        }}
                        className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300"
                      >
                        <Trash2 className="mr-1 inline h-3.5 w-3.5" />
                        删除
                      </button>
                    </div>
                  </div>
                  {item.fused_reason ? <div className="mt-2 text-xs text-rose-600 dark:text-rose-300">熔断原因：{item.fused_reason}</div> : null}
                </div>
              )) : (
                <div className="rounded-2xl bg-slate-50 px-4 py-8 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">还没有实时监控实例，先点右上角新建一个。</div>
              )}
            </div>
          </div>

          {selectedMonitor ? (
            <>
              <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
                <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                  <div className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-white">
                    <Activity className="h-5 w-5 text-emerald-500" />
                    策略持仓
                  </div>
                  <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    账户：{positionsPayload?.account?.account_name || selectedMonitor.account_key} ｜ 显示当前监控账户的股票持仓列表
                  </div>
                  <div className="mt-4 space-y-3">
                    {strategyPositions.length ? strategyPositions.map(position => (
                      <div key={`${position.symbol}-${position.account_id}`} className="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold text-slate-900 dark:text-white">{position.name || position.symbol}</div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{position.symbol}</div>
                          </div>
                          <div className={`text-right text-sm font-semibold ${pnlTone(position.total_pnl)}`}>
                            {formatCurrency(position.total_pnl)}
                            <div className="mt-1 text-xs font-normal">
                              {formatPercent((position.total_pnl_pct ?? null) != null ? Number(position.total_pnl_pct) / 100 : null)}
                            </div>
                          </div>
                        </div>
                        <div className="mt-3 grid gap-2 text-xs text-slate-500 dark:text-slate-400 md:grid-cols-2">
                          <div>持仓：{formatNumber(position.current_position)} 股</div>
                          <div>可用：{formatNumber(position.available_position)} 股</div>
                          <div>成本：¥{formatPrice(position.average_cost)}</div>
                          <div>现价：¥{formatPrice(position.current_price)}</div>
                        </div>
                      </div>
                    )) : (
                      <div className="rounded-2xl bg-slate-50 px-4 py-8 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">当前策略暂无持仓股票。</div>
                    )}
                  </div>
                </div>

                <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                  <div className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-white">
                    <Activity className="h-5 w-5 text-blue-500" />
                    事件流动
                  </div>
                  <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">显示股票交易相关的信号、委托、成交与风险事件。</div>
                  <div className="mt-4 max-h-[980px] space-y-3 overflow-auto pr-1">
                    {eventFlowItems.length ? eventFlowItems.map(item => (
                      <div key={item.id} className={`rounded-2xl border border-l-4 p-4 ${eventTone(item.event_type)} ${eventAccent(item)}`}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${eventSideTone(item)}`}>
                                {eventSideLabel(item)}
                              </span>
                              <span className="rounded-full bg-white/80 px-2 py-1 text-[11px] font-medium text-slate-500 shadow-sm dark:bg-slate-900/70 dark:text-slate-300">
                                {item.symbol || String(item.order_payload?.symbol || item.signal_payload?.symbol || '--')}
                              </span>
                              <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                                {eventLabel(item.event_type)}
                              </span>
                            </div>
                            <div className="mt-2 text-sm font-medium text-slate-800 dark:text-slate-100">
                              {getEventSummary(item) || '事件已记录'}
                            </div>
                            {eventMetricLine(item) ? (
                              <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                                {eventMetricLine(item)}
                              </div>
                            ) : null}
                          </div>
                          <div className="shrink-0 text-right">
                            <div className="text-xs text-slate-400 dark:text-slate-500">{formatDateTime(item.created_at)}</div>
                            {item.request_id ? (
                              <div className="mt-2 text-[11px] text-slate-400 dark:text-slate-500">请求 {item.request_id.slice(0, 8)}</div>
                            ) : null}
                          </div>
                        </div>
                        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
                          <span className="rounded-full bg-slate-100 px-2 py-1 dark:bg-slate-800">
                            {eventTagLabel(item.event_type)}
                          </span>
                          {item.risk_payload?.reason ? (
                            <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                              风控：{String(item.risk_payload.reason)}
                            </span>
                          ) : null}
                        </div>
                        {renderEventDetail(item)}
                        {Object.keys(item.signal_payload || {}).length ? (
                          <div className="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-950 dark:text-slate-300">
                            信号：{JSON.stringify(item.signal_payload)}
                          </div>
                        ) : null}
                        {Object.keys(item.error_payload || {}).length ? (
                          <div className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
                            异常：{JSON.stringify(item.error_payload)}
                          </div>
                        ) : null}
                      </div>
                    )) : (
                      <div className="rounded-2xl bg-slate-50 px-4 py-8 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">当前还没有股票交易事件，运行后这里会持续刷新。</div>
                    )}
                  </div>
                </div>
              </div>
            </>
          ) : null}
        </section>
      </div>

      {showCreateModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-3xl bg-white shadow-2xl dark:bg-slate-900">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-5 dark:border-slate-800">
              <div>
                <div className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-white">
                  <Bot className="h-5 w-5 text-blue-500" />
                  新建监控实例
                </div>
                <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">在弹窗里配置策略、账户和监控池，主页面专注看盘和执行。</div>
              </div>
              <button
                onClick={() => setShowCreateModal(false)}
                className="rounded-xl border border-slate-200 p-2 text-slate-500 dark:border-slate-700 dark:text-slate-300"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[calc(90vh-88px)] overflow-auto p-5">
              <div className="space-y-4">
                <label className="block">
                  <div className="text-sm text-slate-500 dark:text-slate-400">实例名称</div>
                  <input
                    value={form.name}
                    onChange={event => setForm(current => ({ ...current, name: event.target.value }))}
                    placeholder="例如：首日波段-虚拟盘自动化"
                    className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                </label>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="block">
                    <div className="text-sm text-slate-500 dark:text-slate-400">策略</div>
                    <select
                      value={form.strategy_id}
                      onChange={event => setForm(current => ({ ...current, strategy_id: event.target.value }))}
                      className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    >
                      <option value="">请选择策略</option>
                      {strategies.map(strategy => (
                        <option key={strategy.id} value={strategy.id}>
                          {strategy.name}（{strategy.strategy_type}）
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="block">
                    <div className="text-sm text-slate-500 dark:text-slate-400">QMT 账户</div>
                    <select
                      value={form.account_key}
                      onChange={event => setForm(current => ({ ...current, account_key: event.target.value }))}
                      className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    >
                      {accountOptions.map(item => (
                        <option key={item.account_key} value={item.account_key}>
                          {(item.account?.account_name || item.connection.account_name)} / {item.account_key} / {item.role === 'paper' ? '虚拟仓' : '实盘只读'}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="block">
                    <div className="text-sm text-slate-500 dark:text-slate-400">执行模式</div>
                    <select
                      value={selectedAccountRole === 'live' ? 'monitor_only' : form.execution_mode}
                      onChange={event => setForm(current => ({ ...current, execution_mode: event.target.value }))}
                      disabled={selectedAccountRole === 'live'}
                      className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    >
                      <option value="auto">自动交易（仅虚拟仓）</option>
                      <option value="monitor_only">仅监控不下单</option>
                    </select>
                  </label>

                  <label className="block">
                    <div className="text-sm text-slate-500 dark:text-slate-400">手动补充股票池</div>
                    <textarea
                      value={form.manual_symbols}
                      onChange={event => setForm(current => ({ ...current, manual_symbols: event.target.value }))}
                      rows={2}
                      placeholder="可选，输入 000001.SZ,600519.SH"
                      className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    />
                  </label>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="block">
                    <div className="text-sm text-slate-500 dark:text-slate-400">轮询秒数</div>
                    <input
                      type="number"
                      min={5}
                      value={form.poll_interval_seconds}
                      onChange={event => setForm(current => ({ ...current, poll_interval_seconds: Number(event.target.value) || 20 }))}
                      className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    />
                  </label>
                  <label className="block">
                    <div className="text-sm text-slate-500 dark:text-slate-400">单轮最大信号数</div>
                    <input
                      type="number"
                      min={1}
                      value={form.max_signals_per_cycle}
                      onChange={event => setForm(current => ({ ...current, max_signals_per_cycle: Number(event.target.value) || 3 }))}
                      className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    />
                  </label>
                </div>

                <div className="rounded-2xl bg-slate-50 p-4 text-xs leading-6 text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  <div>当前策略：{selectedStrategy?.name || '未选择'}</div>
                  <div>实盘默认仅监控，自动交易白名单暂未在页面开放。</div>
                  <div>默认监控池：策略股票池 + 当前持仓 + 自选股 + 手动补充。</div>
                </div>

                <div className="flex flex-col-reverse gap-3 border-t border-slate-200 pt-4 sm:flex-row sm:justify-end dark:border-slate-800">
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200"
                  >
                    取消
                  </button>
                  <button
                    onClick={() => void handleCreate()}
                    disabled={submitting}
                    className="inline-flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                  >
                    <Play className="h-4 w-4" />
                    {submitting ? '创建中...' : '创建实时监控实例'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {deleteTarget ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/70 p-4">
          <div className="w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl dark:bg-slate-900">
            <div className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-white">
              <Trash2 className="h-5 w-5 text-rose-500" />
              删除监控实例
            </div>
            <div className="mt-3 text-sm leading-6 text-slate-500 dark:text-slate-400">
              确认删除 <span className="font-semibold text-slate-900 dark:text-white">{deleteTarget.name}</span> 吗？
              删除后该实例的事件、审批与运行记录会一起移除，不能恢复。
            </div>
            <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button
                onClick={() => setDeleteTarget(null)}
                className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200"
              >
                取消
              </button>
              <button
                onClick={() => void handleDeleteMonitor()}
                disabled={submitting}
                className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {submitting ? '删除中...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
