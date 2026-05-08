import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, Bot, Pause, Play, Plus, Power, RefreshCw, TimerReset, Trash2, Waves, X } from 'lucide-react'

import DataSourceGovernanceCard, { type DataSourceGovernanceItem } from '@/components/DataSourceGovernanceCard'
import VirtualList from '@/components/VirtualList'
import { usePolling } from '@/hooks/usePolling'
import { api } from '@/services/api'
import type {
  RealtimeEvent,
  RealtimeMonitor,
  RealtimeMonitorPositionsResponse,
  StrategyDefinition,
  VirtualWarehouseOverviewResponse,
} from '@/types'

type ControlAction = 'start' | 'pause' | 'stop' | 'resume' | 'fuse-reset'
type EventFlowTab = 'trading' | 'diagnostics'
const REALTIME_EVENT_LIMIT = 1000
const REALTIME_INITIAL_EVENT_LIMIT = 500
const DIAGNOSTIC_EVENT_TYPES = new Set([
  'cycle_started',
  'cycle_skipped',
  'execution_tracker_initialized',
  'fuse_reset',
  'manual_cycle_requested',
  'market_snapshot',
  'minute_capture',
  'minute_features',
  'monitor_fused',
  'monitor_paused',
  'monitor_resumed',
  'monitor_started',
  'monitor_stopped',
  'no_signal',
  'signal_deduplicated',
  'signal_evaluation_skipped',
])

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

function normalizeSymbol(value?: string | null) {
  return String(value || '').trim().toUpperCase()
}

function parseFiniteNumber(value: unknown) {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : null
}

function displaySecurityName(name?: string | null, symbol?: string | null) {
  const trimmedName = String(name || '').trim()
  const trimmedSymbol = String(symbol || '').trim().toUpperCase()
  if (!trimmedName) return ''
  if (trimmedName.toUpperCase() === trimmedSymbol) return ''
  return trimmedName
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

function mergeRealtimeEvents(current: RealtimeEvent[], incoming: RealtimeEvent[]) {
  let merged = current.slice()
  const indexById = new Map(merged.map((row, index) => [row.id, index]))
  let needsSort = false
  for (const item of incoming) {
    const index = indexById.get(item.id)
    if (typeof index === 'number') merged[index] = item
    else {
      const last = merged[merged.length - 1]
      if (last && String(item.created_at || '') < String(last.created_at || '')) needsSort = true
      indexById.set(item.id, merged.length)
      merged.push(item)
    }
  }
  if (needsSort) {
    merged = merged.sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
  }
  return merged.slice(-REALTIME_EVENT_LIMIT)
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

function strategyLifecycleLabel(status?: string | null) {
  return {
    active: '已启用',
    paused: '已暂停',
    draft: '草稿',
    archived: '已归档',
    candidate: '候选',
  }[String(status || '')] || '--'
}

function strategyLifecycleTone(status?: string | null) {
  return {
    active: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
    paused: 'bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
    draft: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
    archived: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
    candidate: 'bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300',
  }[String(status || '')] || 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
}

function strategyRuntimeLabel(strategy: StrategyDefinition | null, monitor: RealtimeMonitor | null) {
  if (monitor) return statusLabel(monitor.status)
  if (!strategy) return '未绑定'
  if (strategy.status === 'active') return '未启动'
  return strategyLifecycleLabel(strategy.status)
}

function strategyRuntimeTone(strategy: StrategyDefinition | null, monitor: RealtimeMonitor | null) {
  if (monitor) return statusTone(monitor.status)
  if (!strategy) return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
  if (strategy.status === 'active') return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
  return strategyLifecycleTone(strategy.status)
}

function canRunMonitorOnce(status?: string | null) {
  return ['ready', 'paused', 'running'].includes(String(status || ''))
}

function canStopMonitor(status?: string | null) {
  return ['ready', 'running', 'paused', 'error'].includes(String(status || ''))
}

function primaryControlMeta(status?: string | null) {
  const normalized = String(status || '')
  if (normalized === 'running') {
    return {
      action: 'pause' as ControlAction,
      label: '暂停',
      icon: Pause,
      className: 'bg-amber-500 text-white',
    }
  }
  if (normalized === 'paused') {
    return {
      action: 'resume' as ControlAction,
      label: '恢复',
      icon: Play,
      className: 'bg-blue-600 text-white',
    }
  }
  if (normalized === 'fused') {
    return {
      action: 'fuse-reset' as ControlAction,
      label: '解除熔断',
      icon: TimerReset,
      className: 'bg-rose-600 text-white',
    }
  }
  if (normalized === 'error') {
    return {
      action: 'start' as ControlAction,
      label: '重新启动',
      icon: RefreshCw,
      className: 'bg-rose-600 text-white',
    }
  }
  return {
    action: 'start' as ControlAction,
    label: '启动',
    icon: Play,
    className: 'bg-emerald-600 text-white',
  }
}

function controlSuccessMessage(action: ControlAction) {
  return {
    start: '监控实例已启动',
    pause: '监控实例已暂停',
    stop: '监控实例已停止',
    resume: '监控实例已恢复运行',
    'fuse-reset': '熔断已解除，实例已切回暂停',
  }[action]
}

function monitorDisplaySymbols(monitor: RealtimeMonitor | null | undefined) {
  if (!monitor) return []
  const candidates = [
    ...(monitor.display_symbols || []),
    ...(monitor.resolved_symbols || []),
    ...(monitor.manual_symbols || []),
  ]
  return Array.from(new Set(candidates.map(item => normalizeSymbol(item)).filter(Boolean)))
}

function filterMonitorPositions(
  monitor: RealtimeMonitor | null | undefined,
  positions: RealtimeMonitorPositionsResponse['positions'] | undefined,
) {
  const items = positions || []
  const symbols = monitorDisplaySymbols(monitor)
  if (!symbols.length) return items
  const symbolSet = new Set(symbols)
  return items.filter(position => symbolSet.has(normalizeSymbol(position.symbol)))
}

function buildMonitorPerformance(
  monitor: RealtimeMonitor | null | undefined,
  payload: RealtimeMonitorPositionsResponse | null | undefined,
) {
  const positions = filterMonitorPositions(monitor, payload?.positions)
  const totalPnl = positions.reduce((sum, position) => sum + Number(position.total_pnl || 0), 0)
  const todayPnl = positions.reduce((sum, position) => sum + Number(position.today_pnl || 0), 0)
  const totalCost = positions.reduce(
    (sum, position) => sum + Number(position.average_cost || 0) * Number(position.current_position || 0),
    0,
  )
  const previousCloseValue = positions.reduce((sum, position) => {
    const quantity = Number(position.current_position || 0)
    if (!quantity) return sum
    const previousClose = Number(position.previous_close || NaN)
    if (Number.isFinite(previousClose) && previousClose > 0) {
      return sum + previousClose * quantity
    }
    const marketValue = Number(position.market_value || 0)
    const todayProfit = Number(position.today_pnl || 0)
    return sum + Math.max(marketValue - todayProfit, 0)
  }, 0)
  return {
    positions,
    positionCount: positions.length,
    totalPnl,
    totalPnlPct: totalCost > 0 ? totalPnl / totalCost : null,
    todayPnl,
    todayPnlPct: previousCloseValue > 0 ? todayPnl / previousCloseValue : null,
  }
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
  return String(item.order_payload?.side || item.broker_result?.side || item.signal_payload?.side || item.payload?.side || '').toLowerCase()
}

function eventMetricLine(item: RealtimeEvent) {
  const quantity = eventQuantity(item)
  const filledQuantity =
    parseFiniteNumber(item.payload?.filled_quantity) ??
    parseFiniteNumber(item.order_payload?.filled_quantity) ??
    parseFiniteNumber(item.broker_result?.filled_quantity)
  const price = Number(item.order_payload?.price || item.broker_result?.price || item.payload?.price || NaN)
  const priceType = String(item.order_payload?.price_type || item.payload?.price_type || '').trim()
  const state = eventExecutionState(item)
  const fields: string[] = []
  if (quantity != null) fields.push(`委托 ${formatNumber(quantity)} 股`)
  if (Number.isFinite(price)) fields.push(`价格 ¥${formatPrice(price)}`)
  if (priceType) fields.push(`方式 ${priceType}`)
  if (filledQuantity != null && filledQuantity > 0) fields.push(`已成交 ${formatNumber(filledQuantity)} 股`)
  if (state && !['已成交', '未成交'].includes(state)) fields.push(`状态 ${state}`)
  return fields.join(' / ')
}

function eventSymbol(item: RealtimeEvent) {
  return String(item.symbol || item.order_payload?.symbol || item.broker_result?.symbol || item.signal_payload?.symbol || '').trim().toUpperCase()
}

function eventActionLabel(item: RealtimeEvent) {
  const side = eventSide(item)
  if (side === 'buy') return '买入'
  if (side === 'sell') return '卖出'
  return '调仓'
}

function eventQuantity(item: RealtimeEvent) {
  return (
    parseFiniteNumber(item.order_payload?.quantity) ??
    parseFiniteNumber(item.broker_result?.quantity) ??
    parseFiniteNumber((item.broker_result?.raw as Record<string, unknown> | undefined)?.traded_volume) ??
    parseFiniteNumber(item.broker_result?.filled_quantity) ??
    parseFiniteNumber(item.payload?.quantity) ??
    parseFiniteNumber(item.payload?.filled_quantity)
  )
}

function eventCurrentPosition(item: RealtimeEvent, positionMap: Map<string, number>) {
  const payloadCurrent = item.payload?.current as Record<string, unknown> | undefined
  const payloadPrevious = item.payload?.previous as Record<string, unknown> | undefined
  const currentMissing = Object.prototype.hasOwnProperty.call(item.payload || {}, 'current') && payloadCurrent == null
  const currentPosition =
    (currentMissing ? 0 : null) ??
    parseFiniteNumber(payloadCurrent?.current_position) ??
    parseFiniteNumber(payloadPrevious?.current_position) ??
    positionMap.get(eventSymbol(item))
  return currentPosition ?? null
}

function eventSecurityName(item: RealtimeEvent, positionNameMap: Map<string, string>) {
  const payloadCurrent = item.payload?.current as Record<string, unknown> | undefined
  const payloadPrevious = item.payload?.previous as Record<string, unknown> | undefined
  const symbol = eventSymbol(item)
  return (
    displaySecurityName(String(payloadCurrent?.name || ''), symbol) ||
    displaySecurityName(String(payloadPrevious?.name || ''), symbol) ||
    displaySecurityName(String(item.order_payload?.name || ''), symbol) ||
    displaySecurityName(String(item.broker_result?.name || ''), symbol) ||
    displaySecurityName(String(item.broker_result?.security_name || item.broker_result?.stockName || ''), symbol) ||
    positionNameMap.get(symbol) ||
    ''
  )
}

function eventPositionChange(item: RealtimeEvent) {
  const payloadCurrent = item.payload?.current as Record<string, unknown> | undefined
  const payloadPrevious = item.payload?.previous as Record<string, unknown> | undefined
  const hasCurrent = Object.prototype.hasOwnProperty.call(item.payload || {}, 'current')
  const hasPrevious = Object.prototype.hasOwnProperty.call(item.payload || {}, 'previous')
  const currentPosition = payloadCurrent == null && hasCurrent ? 0 : parseFiniteNumber(payloadCurrent?.current_position)
  const previousPosition = payloadPrevious == null && hasPrevious ? 0 : parseFiniteNumber(payloadPrevious?.current_position)
  if (currentPosition == null || previousPosition == null) return null
  return currentPosition - previousPosition
}

function isTradingFlowEvent(item: RealtimeEvent) {
  if (
    [
      'signal_generated',
      'order_intent',
      'signal_blocked',
      'approval_created',
      'approval_executed',
      'approval_rejected',
      'order_submitted',
      'order_status_changed',
      'order_snapshot_refreshed',
      'trade_confirmed',
      'order_cancel_requested',
      'order_cancelled',
      'order_cancel_error',
      'order_replace_requested',
      'order_rejected',
      'order_error',
      'live_readonly_guard',
    ].includes(item.event_type)
  ) {
    return true
  }
  if (item.event_type === 'position_changed') {
    const change = eventPositionChange(item)
    return change != null && change !== 0
  }
  return false
}

function isDiagnosticFlowEvent(item: RealtimeEvent) {
  if (DIAGNOSTIC_EVENT_TYPES.has(item.event_type)) return true
  return item.event_type === 'position_changed'
}

function buildTradeFlowItems(events: RealtimeEvent[]) {
  return events
    .filter(isTradingFlowEvent)
    .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
}

function buildDiagnosticFlowItems(events: RealtimeEvent[]) {
  return events
    .filter(isDiagnosticFlowEvent)
    .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
}

function eventExecutionState(item: RealtimeEvent) {
  if (item.event_type === 'trade_confirmed') return '已成交'
  if (item.event_type === 'order_submitted') return '未成交'
  if (item.event_type === 'order_rejected') return '已拒单'
  if (item.event_type === 'signal_blocked') return '已拦截'
  if (item.event_type === 'order_error') return '执行异常'
  if (item.event_type === 'order_cancel_requested' || item.event_type === 'order_replace_requested') return '处理中'
  if (item.event_type === 'order_cancelled') return '已撤单'
  if (item.event_type === 'position_changed') {
    const change = eventPositionChange(item)
    if (change == null) return '持仓已刷新'
    return change === 0 ? '未成交' : '已成交'
  }
  if (item.event_type === 'order_status_changed') {
    const quantity = eventQuantity(item)
    const filledQuantity =
      parseFiniteNumber(item.payload?.filled_quantity) ??
      parseFiniteNumber(item.order_payload?.filled_quantity) ??
      parseFiniteNumber(item.broker_result?.filled_quantity)
    const statusText = String(item.payload?.current_status || item.order_payload?.status || item.broker_result?.status || '').toLowerCase()
    if (filledQuantity != null && quantity != null && filledQuantity >= quantity && quantity > 0) return '已成交'
    if (filledQuantity != null && filledQuantity > 0) return '部分成交'
    if (statusText.includes('cancel')) return '已撤单'
    if (statusText.includes('reject') || statusText.includes('invalid')) return '已拒单'
    if (statusText.includes('error') || statusText.includes('fail')) return '执行异常'
    if (statusText.includes('pending') || statusText.includes('queue') || statusText.includes('submit') || statusText.includes('new')) return '处理中'
    return '未成交'
  }
  return ''
}

function eventStatusKind(item: RealtimeEvent) {
  const state = eventExecutionState(item)
  if (item.event_type === 'monitor_fused') return 'risk'
  if (state === '执行异常') return 'error'
  if (state === '已拒单') return 'rejected'
  if (state === '已拦截') return 'risk'
  if (state === '已撤单') return 'cancelled'
  if (state === '部分成交') return 'partial'
  if (state === '已成交') return 'filled'
  if (state === '处理中') return 'pending_action'
  if (item.event_type === 'signal_generated' || item.event_type === 'order_intent') return 'pending_action'
  const side = eventSide(item)
  if (side === 'buy') return 'buy'
  if (side === 'sell') return 'sell'
  return 'info'
}

function eventTone(item: RealtimeEvent) {
  return {
    buy: 'border-rose-200 bg-rose-50/70 dark:border-rose-500/30 dark:bg-rose-500/10',
    sell: 'border-emerald-200 bg-emerald-50/70 dark:border-emerald-500/30 dark:bg-emerald-500/10',
    filled: 'border-sky-200 bg-sky-50/70 dark:border-sky-500/30 dark:bg-sky-500/10',
    partial: 'border-amber-200 bg-amber-50/80 dark:border-amber-500/30 dark:bg-amber-500/10',
    cancelled: 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-950',
    rejected: 'border-rose-200 bg-rose-50/70 dark:border-rose-500/30 dark:bg-rose-500/10',
    error: 'border-rose-200 bg-rose-50/70 dark:border-rose-500/30 dark:bg-rose-500/10',
    risk: 'border-amber-200 bg-amber-50/80 dark:border-amber-500/30 dark:bg-amber-500/10',
    pending_action: 'border-indigo-200 bg-indigo-50/70 dark:border-indigo-500/30 dark:bg-indigo-500/10',
    info: 'border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900',
  }[eventStatusKind(item)]
}

function eventTagLabel(item: RealtimeEvent) {
  if (['minute_features', 'minute_capture', 'market_snapshot', 'cycle_started', 'cycle_skipped', 'no_signal'].includes(item.event_type)) {
    return '分钟判定'
  }
  if (['monitor_created', 'monitor_started', 'monitor_resumed', 'monitor_paused', 'monitor_stopped', 'manual_cycle_requested', 'fuse_reset'].includes(item.event_type)) {
    return '运行状态'
  }
  if (['signal_generated', 'order_intent'].includes(item.event_type)) return '交易信号'
  if (item.event_type === 'signal_blocked') return '信号拦截'
  if (['order_submitted', 'order_status_changed', 'order_snapshot_refreshed'].includes(item.event_type)) return '委托跟踪'
  if (['trade_confirmed'].includes(item.event_type)) return '成交回报'
  if (['order_cancel_requested', 'order_cancelled', 'order_replace_requested'].includes(item.event_type)) return '撤补流程'
  if (['monitor_fused', 'order_error', 'order_rejected', 'order_cancel_error', 'live_readonly_guard'].includes(item.event_type)) {
    return '风险异常'
  }
  if (['position_changed', 'execution_tracker_initialized', 'approval_created', 'approval_executed', 'approval_rejected'].includes(item.event_type)) {
    return '账户跟踪'
  }
  return '运行事件'
}

function eventSideTone(item: RealtimeEvent) {
  return {
    buy: 'bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
    sell: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
    filled: 'bg-sky-100 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300',
    partial: 'bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
    cancelled: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
    rejected: 'bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
    error: 'bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
    risk: 'bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
    pending_action: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300',
    info: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  }[eventStatusKind(item)]
}

function eventSideLabel(item: RealtimeEvent) {
  return {
    buy: '买入委托',
    sell: '卖出委托',
    filled: '已成交',
    partial: '部分成交',
    cancelled: '已撤单',
    rejected: '已拒单',
    error: '执行异常',
    risk: '熔断',
    pending_action: '处理中',
    info: '跟踪中',
  }[eventStatusKind(item)]
}

function eventAccent(item: RealtimeEvent) {
  return {
    buy: 'border-l-rose-500',
    sell: 'border-l-emerald-500',
    filled: 'border-l-sky-500',
    partial: 'border-l-amber-500',
    cancelled: 'border-l-slate-400',
    rejected: 'border-l-rose-500',
    error: 'border-l-rose-500',
    risk: 'border-l-amber-500',
    pending_action: 'border-l-indigo-500',
    info: 'border-l-blue-500',
  }[eventStatusKind(item)]
}

function getEventSummary(item: RealtimeEvent, positionMap: Map<string, number>) {
  const payload = item.payload || {}
  if (item.event_type === 'monitor_created') {
    return '监控实例已创建，等待启动'
  }

  if (item.event_type === 'monitor_started') {
    return '策略监控已开始运行'
  }

  if (item.event_type === 'monitor_resumed') {
    return '策略监控已恢复运行'
  }

  if (item.event_type === 'monitor_paused') {
    return '策略监控已暂停'
  }

  if (item.event_type === 'monitor_stopped') {
    return '策略监控已停止'
  }

  if (item.event_type === 'fuse_reset') {
    return '熔断已解除，等待重新运行'
  }

  if (item.event_type === 'manual_cycle_requested') {
    return '手动触发一轮实时监控'
  }

  if (item.event_type === 'cycle_started') {
    return `开始执行本轮监控，覆盖 ${formatNumber(Number(payload.symbol_count || 0))} 只股票`
  }

  if (item.event_type === 'market_snapshot') {
    const quoteCount = Object.keys(payload.quotes || {}).length
    return `已获取 QMT 实时行情快照，样本 ${formatNumber(quoteCount)} 只`
  }

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

  if (item.event_type === 'order_intent') {
    const side = signalSideLabel(String(item.order_payload?.side || item.payload?.side || ''))
    return `生成${side}委托意图，等待执行检查`
  }

  if (item.event_type === 'cycle_skipped') {
    const reason = String(payload.reason || '')
    if (reason === 'outside_trading_session') {
      return `当前不在 A 股交易时段，已跳过本轮检测。仅在工作日 09:30-11:30、13:00-15:00 执行`
    }
    if (reason === 'empty_universe') {
      return '当前监控池为空，已跳过本轮检测'
    }
  }

  if (item.event_type === 'signal_blocked') {
    const side = signalSideLabel(String(item.signal_payload?.side || ''))
    const available = parseFiniteNumber(item.payload?.available_position)
    const lotSize = parseFiniteNumber(item.payload?.lot_size)
    const currentPosition = eventCurrentPosition(item, positionMap)
    return `产生${side}信号，但可卖 ${formatNumber(available ?? 0)} 股不足一手 ${formatNumber(lotSize ?? 0)} 股，当前持仓 ${formatNumber(currentPosition ?? 0)} 股，未下单`
  }

  if (item.event_type === 'no_signal') {
    return '本轮未满足买卖条件'
  }

  if (item.event_type === 'order_submitted') {
    const quantity = eventQuantity(item)
    const currentPosition = eventCurrentPosition(item, positionMap)
    return `${eventActionLabel(item)} ${formatNumber(quantity ?? 0)} 股，未成交，当前持仓 ${formatNumber(currentPosition ?? 0)} 股，未变化`
  }

  if (item.event_type === 'order_status_changed') {
    const quantity = eventQuantity(item)
    const currentPosition = eventCurrentPosition(item, positionMap)
    return `${eventActionLabel(item)} ${formatNumber(quantity ?? 0)} 股，${eventExecutionState(item)}，当前持仓 ${formatNumber(currentPosition ?? 0)} 股`
  }

  if (item.event_type === 'trade_confirmed') {
    const quantity = eventQuantity(item)
    const currentPosition = eventCurrentPosition(item, positionMap)
    return `${eventActionLabel(item)} ${formatNumber(quantity ?? 0)} 股，已成交，当前持仓 ${formatNumber(currentPosition ?? 0)} 股`
  }

  if (item.event_type === 'order_cancel_requested') {
    const quantity = eventQuantity(item)
    const currentPosition = eventCurrentPosition(item, positionMap)
    return `${eventActionLabel(item)} ${formatNumber(quantity ?? 0)} 股，处理中，当前持仓 ${formatNumber(currentPosition ?? 0)} 股，未变化`
  }

  if (item.event_type === 'order_cancelled') {
    const quantity = eventQuantity(item)
    const currentPosition = eventCurrentPosition(item, positionMap)
    return `${eventActionLabel(item)} ${formatNumber(quantity ?? 0)} 股，已撤单，当前持仓 ${formatNumber(currentPosition ?? 0)} 股，未变化`
  }

  if (item.event_type === 'order_replace_requested') {
    const quantity = eventQuantity(item)
    const currentPosition = eventCurrentPosition(item, positionMap)
    return `${eventActionLabel(item)} ${formatNumber(quantity ?? 0)} 股，处理中，当前持仓 ${formatNumber(currentPosition ?? 0)} 股，未变化`
  }

  if (item.event_type === 'order_rejected' || item.event_type === 'order_error') {
    const quantity = eventQuantity(item)
    const currentPosition = eventCurrentPosition(item, positionMap)
    return `${eventActionLabel(item)} ${formatNumber(quantity ?? 0)} 股，${eventExecutionState(item)}，当前持仓 ${formatNumber(currentPosition ?? 0)} 股，未变化`
  }

  if (item.event_type === 'position_changed') {
    const current = item.payload?.current as Record<string, unknown> | undefined
    const change = eventPositionChange(item)
    const currentPosition = eventCurrentPosition(item, positionMap)
    if (change == null) {
      return `当前持仓 ${formatNumber(currentPosition ?? 0)} 股`
    }
    if (change > 0) {
      return `买入 ${formatNumber(change)} 股，已成交，当前持仓 ${formatNumber(currentPosition ?? 0)} 股`
    }
    if (change < 0) {
      return `卖出 ${formatNumber(Math.abs(change))} 股，已成交，当前持仓 ${formatNumber(currentPosition ?? 0)} 股`
    }
    if (current) {
      return `当前持仓 ${formatNumber(currentPosition ?? 0)} 股，未变化`
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
    const features = Array.isArray(payload.items) ? payload.items as Record<string, unknown>[] : []
    const first = features[0]
    const missingSymbols = Array.isArray(payload.missing_symbols) ? payload.missing_symbols.map(String).filter(Boolean) : []
    const staleSymbols = Array.isArray(payload.stale_symbols) ? payload.stale_symbols.map(String).filter(Boolean) : []
    return (
      <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-950 dark:text-slate-300">
        <div>周期：{timeframeLabel(String(payload.timeframe || ''))} ｜ 数据源：{String(payload.source || '--')}</div>
        <div className="mt-1">最新闭合 K 线：{String(payload.latest_closed_bar_end || '--')}</div>
        {features.length ? (
          <div className="mt-1">
            已判定：{features.slice(0, 4).map(row => `${String(row.symbol || '--')} ${signalSideLabel(String(row.signal || 'hold'))}`).join('；')}
          </div>
        ) : null}
        {missingSymbols.length || staleSymbols.length ? (
          <div className="mt-1 text-amber-700 dark:text-amber-300">
            {staleSymbols.length ? `分钟线滞后：${staleSymbols.slice(0, 8).join('、')}` : ''}
            {staleSymbols.length && missingSymbols.length ? ' ｜ ' : ''}
            {missingSymbols.length ? `本轮缺失：${missingSymbols.slice(0, 8).join('、')}` : ''}
          </div>
        ) : null}
        {first ? (
          <>
            <div className="mt-1">
              波段：{formatPrice(Number(first.first_day_band || NaN))} ｜ B1：{formatPrice(Number(first.first_day_band_b1 || NaN))}
            </div>
            <div className="mt-1">
              K 线：{formatPrice(Number(first.open || NaN))} / {formatPrice(Number(first.high || NaN))} / {formatPrice(Number(first.low || NaN))} / {formatPrice(Number(first.close || NaN))}
            </div>
          </>
        ) : null}
      </div>
    )
  }

  if (item.event_type === 'minute_capture') {
    const rowsBySymbol = payload.symbol_rows && typeof payload.symbol_rows === 'object'
      ? payload.symbol_rows as Record<string, unknown>
      : {}
    const latestBySymbol = payload.symbol_latest_trade_times && typeof payload.symbol_latest_trade_times === 'object'
      ? payload.symbol_latest_trade_times as Record<string, unknown>
      : {}
    const symbolRows = Object.entries(rowsBySymbol).slice(0, 8)
    return (
      <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-950 dark:text-slate-300">
        <div>交易日：{String(payload.trade_date || '--')} ｜ 数据源：{String(payload.source || '--')}</div>
        <div className="mt-1">写入条数：{formatNumber(Number(payload.rows || 0))}</div>
        {symbolRows.length ? (
          <div className="mt-1">
            分票：{symbolRows.map(([symbol, rows]) => `${symbol} ${formatNumber(Number(rows || 0))}条 / ${String(latestBySymbol[symbol] || '--')}`).join('；')}
          </div>
        ) : null}
      </div>
    )
  }

  if (item.event_type === 'cycle_skipped') {
    return (
      <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-950 dark:text-slate-300">
        <div>原因：{String(payload.reason || '--')}</div>
        {payload.reason === 'outside_trading_session' ? (
          <div className="mt-1">执行时段：{String(payload.session || '09:30-11:30,13:00-15:00')}</div>
        ) : null}
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

  if (item.event_type === 'signal_blocked') {
    return (
      <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-950 dark:text-slate-300">
        <div>方向：{signalSideLabel(String(item.signal_payload?.side || ''))}</div>
        <div className="mt-1">处理：{String(item.payload?.message || '当前信号已拦截')}</div>
        <div className="mt-1">
          可卖：{formatNumber(parseFiniteNumber(item.payload?.available_position))} 股 ｜ 当前持仓：
          {formatNumber(parseFiniteNumber(item.payload?.current_position))} 股
        </div>
        <div className="mt-1">最小交易单位：{formatNumber(parseFiniteNumber(item.payload?.lot_size))} 股</div>
      </div>
    )
  }

  return null
}

export default function RealtimeMonitorPage() {
  const [strategies, setStrategies] = useState<StrategyDefinition[]>([])
  const [warehouse, setWarehouse] = useState<VirtualWarehouseOverviewResponse | null>(null)
  const [monitors, setMonitors] = useState<RealtimeMonitor[]>([])
  const [monitorPositionsMap, setMonitorPositionsMap] = useState<Record<string, RealtimeMonitorPositionsResponse>>({})
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
  const [eventFlowTab, setEventFlowTab] = useState<EventFlowTab>('trading')
  const streamAbortRef = useRef<AbortController | null>(null)
  const snapshotRefreshTimerRef = useRef<number | null>(null)

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

  const loadMonitorPositionMap = useCallback(async (items: RealtimeMonitor[]) => {
    if (!items.length) {
      setMonitorPositionsMap({})
      return
    }
    const entries = await Promise.all(
      items.map(async item => {
        try {
          const payload = await api.getRealtimeMonitorPositions(item.id)
          return [item.id, payload] as const
        } catch {
          return null
        }
      }),
    )
    setMonitorPositionsMap(() => {
      const next: Record<string, RealtimeMonitorPositionsResponse> = {}
      for (const entry of entries) {
        if (entry) next[entry[0]] = entry[1]
      }
      return next
    })
  }, [])

  const loadMonitors = useCallback(async () => {
    const response = await api.getRealtimeMonitors()
    const items = response.items || []
    setMonitors(items)
    setSelectedMonitorId(current => current || items?.[0]?.id || null)
    await loadMonitorPositionMap(items)
  }, [loadMonitorPositionMap])

  const loadDetail = useCallback(async (monitorId: string) => {
    const [monitor, eventRes, positionRes] = await Promise.all([
      api.getRealtimeMonitor(monitorId),
      api.getRealtimeMonitorEvents(monitorId, { limit: REALTIME_INITIAL_EVENT_LIMIT }),
      api.getRealtimeMonitorPositions(monitorId),
    ])
    setSelectedMonitor(monitor)
    setEvents(eventRes.items || [])
    setPositionsPayload(positionRes)
    setMonitorPositionsMap(current => ({ ...current, [monitorId]: positionRes }))
  }, [])

  const loadMonitorSnapshot = useCallback(async (monitorId: string) => {
    const [monitor, positionRes] = await Promise.all([
      api.getRealtimeMonitor(monitorId),
      api.getRealtimeMonitorPositions(monitorId),
    ])
    setSelectedMonitor(monitor)
    setPositionsPayload(positionRes)
    setMonitorPositionsMap(current => ({ ...current, [monitorId]: positionRes }))
  }, [])

  const scheduleMonitorSnapshotRefresh = useCallback((monitorId: string) => {
    if (snapshotRefreshTimerRef.current != null) return
    snapshotRefreshTimerRef.current = window.setTimeout(() => {
      snapshotRefreshTimerRef.current = null
      void loadMonitorSnapshot(monitorId)
    }, 600)
  }, [loadMonitorSnapshot])

  const loadPage = useCallback(async (silent = false, preferredMonitorId?: string | null) => {
    try {
      if (silent) setRefreshing(true)
      else setLoading(true)
      const [strategyRes, warehouseRes, monitorRes] = await Promise.all([
        api.getStrategyPlatformList(),
        api.getQmtVirtualWarehouseOverview(undefined, undefined, true),
        api.getRealtimeMonitors(),
      ])
      setStrategies(strategyRes.strategies || [])
      setWarehouse(warehouseRes)
      const monitorItems = monitorRes.items || []
      setMonitors(monitorItems)
      await loadMonitorPositionMap(monitorItems)

      const nextMonitorId =
        preferredMonitorId === undefined
          ? (selectedMonitorId || monitorItems?.[0]?.id || null)
          : (preferredMonitorId || monitorItems?.[0]?.id || null)
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
  }, [form.account_key, form.strategy_id, loadDetail, loadMonitorPositionMap, selectedMonitorId])

  useEffect(() => {
    void loadPage()
  }, [loadPage])

  useEffect(() => {
    return () => {
      if (snapshotRefreshTimerRef.current != null) {
        window.clearTimeout(snapshotRefreshTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    if (!selectedMonitorId) return
    setEvents([])
    void loadDetail(selectedMonitorId)
  }, [loadDetail, selectedMonitorId])

  usePolling(loadMonitors, { intervalMs: 5000, runImmediately: false })

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
          initial_limit: REALTIME_INITIAL_EVENT_LIMIT,
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
                return mergeRealtimeEvents(current, [item])
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
                scheduleMonitorSnapshotRefresh(selectedMonitorId)
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
  }, [scheduleMonitorSnapshotRefresh, selectedMonitorId])

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
      setMessage(controlSuccessMessage(action))
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
      setEvents(current => mergeRealtimeEvents(current, result.events || []))
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
  const getMonitorStrategy = useCallback((monitor: RealtimeMonitor) => {
    return strategyMap.get(monitor.strategy_id) || null
  }, [strategyMap])

  const getMonitorPerformance = useCallback((monitor: RealtimeMonitor) => {
    return buildMonitorPerformance(monitor, monitorPositionsMap[monitor.id] || null)
  }, [monitorPositionsMap])

  const getMonitorDrawdown = useCallback((monitor: RealtimeMonitor) => {
    const strategy = getMonitorStrategy(monitor)
    const strategyDrawdown = strategy?.performance?.max_drawdown
    if (typeof strategyDrawdown === 'number' && !Number.isNaN(strategyDrawdown)) return strategyDrawdown
    const riskDrawdown = Number(monitor.risk_config?.max_drawdown_pct ?? NaN)
    if (Number.isFinite(riskDrawdown)) return -Math.abs(riskDrawdown)
    return null
  }, [getMonitorStrategy])

  const strategyPerformance = useMemo(
    () => buildMonitorPerformance(selectedMonitor, positionsPayload),
    [positionsPayload, selectedMonitor],
  )

  const strategyPositions = useMemo(
    () => strategyPerformance.positions.slice().sort((a, b) => Number(b.market_value || 0) - Number(a.market_value || 0)),
    [strategyPerformance.positions],
  )

  const strategyPositionMap = useMemo(
    () => new Map(strategyPositions.map(position => [String(position.symbol || '').trim().toUpperCase(), Number(position.current_position || 0)])),
    [strategyPositions],
  )

  const strategyPositionNameMap = useMemo(
    () => new Map(
      strategyPositions.map(position => [
        String(position.symbol || '').trim().toUpperCase(),
        displaySecurityName(position.name, position.symbol),
      ]),
    ),
    [strategyPositions],
  )

  const eventFlowItems = useMemo(() => buildTradeFlowItems(events), [events])
  const diagnosticFlowItems = useMemo(() => buildDiagnosticFlowItems(events), [events])
  const activeEventFlowItems = eventFlowTab === 'trading' ? eventFlowItems : diagnosticFlowItems
  const activeEventFlowEmptyText = eventFlowTab === 'trading'
    ? '当前还没有交易相关事件，触发信号或委托后这里会持续刷新。'
    : '当前还没有运行诊断事件，下一轮监控循环后这里会展示分钟线、无信号和持仓快照变化。'
  const selectedMonitorPrimaryControl = useMemo(
    () => (selectedMonitor ? primaryControlMeta(selectedMonitor.status) : null),
    [selectedMonitor],
  )
  const latestMarketDataSource = useMemo(() => {
    const minuteEvent = [...events].reverse().find(item =>
      ['minute_capture', 'minute_features', 'market_snapshot'].includes(item.event_type) && item.payload?.source,
    )
    return String(minuteEvent?.payload?.source || selectedMonitor?.quote_source || '--')
  }, [events, selectedMonitor?.quote_source])
  const backendGovernanceItems = useMemo<DataSourceGovernanceItem[]>(() => {
    const items = [
      ...(selectedMonitor?.data_governance?.items || []),
      ...(positionsPayload?.data_governance?.items || []),
    ]
    const seen = new Set<string>()
    return items.filter(item => {
      const key = `${item.label}-${item.value}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [positionsPayload?.data_governance?.items, selectedMonitor?.data_governance?.items])
  const governanceItems = useMemo<DataSourceGovernanceItem[]>(() => {
    const fallbackItems: DataSourceGovernanceItem[] = [
      {
        label: '监控数据源',
        value: selectedMonitor?.quote_source || '--',
        detail: '这是监控实例声明的主行情源，不等同于页面缓存或账户快照来源',
        tone: selectedMonitor ? 'good' : 'neutral',
      },
      {
        label: '分钟线判定源',
        value: latestMarketDataSource,
        detail: '最近一次分钟捕获 / 特征计算里记录的数据源',
        tone: latestMarketDataSource.includes('synthetic') ? 'warn' : latestMarketDataSource === '--' ? 'neutral' : 'info',
      },
      {
        label: '持仓快照',
        value: positionsPayload?.connection?.provider || '--',
        detail: positionsPayload?.fetched_at ? `快照时间 ${formatDateTime(positionsPayload.fetched_at)}` : '当前尚未拉到持仓快照',
        tone: positionsPayload?.fetched_at ? 'good' : 'warn',
      },
      {
        label: '事件流状态',
        value: streamStatus,
        detail: selectedMonitor?.state?.last_updated_at ? `最近监控循环 ${formatDateTime(selectedMonitor.state.last_updated_at)}` : '等待下一轮监控状态上报',
        tone: streamStatus === '实时追踪中' ? 'good' : streamStatus === '连接中...' ? 'info' : streamStatus === '连接失败' ? 'bad' : 'warn',
      },
    ]
    return [
      ...(backendGovernanceItems.length ? backendGovernanceItems : fallbackItems),
      {
        label: '收益口径',
        value: '策略股票汇总',
        detail: `当前按监控策略覆盖股票 ${strategyPerformance.positionCount} 只汇总今日/累计收益`,
        tone: 'info',
      },
    ]
  }, [backendGovernanceItems, latestMarketDataSource, positionsPayload?.connection?.provider, positionsPayload?.fetched_at, selectedMonitor, streamStatus, strategyPerformance.positionCount])
  const governanceWarnings = useMemo(() => {
    const merged = [
      ...(selectedMonitor?.data_governance?.warnings || []),
      ...(positionsPayload?.data_governance?.warnings || []),
    ]
    if (merged.length) {
      if (!selectedMonitor && !merged.includes('当前还没有选中监控实例，页面无法判断策略层分钟线与账户持仓是否同步。')) {
        merged.push('当前还没有选中监控实例，页面无法判断策略层分钟线与账户持仓是否同步。')
      }
      if (streamStatus === '连接失败' && !merged.includes('事件流连接失败时，页面上的实例状态可能会滞后于后端实际运行状态。')) {
        merged.push('事件流连接失败时，页面上的实例状态可能会滞后于后端实际运行状态。')
      }
      if (error && !merged.includes(error)) merged.push(error)
      return merged
    }
    const warnings: string[] = []
    if (!selectedMonitor) warnings.push('当前还没有选中监控实例，页面无法判断策略层分钟线与账户持仓是否同步。')
    if (selectedMonitor?.status === 'fused' && selectedMonitor.fused_reason) warnings.push(`当前实例已熔断：${selectedMonitor.fused_reason}`)
    if (streamStatus === '连接失败') warnings.push('事件流连接失败时，页面上的实例状态可能会滞后于后端实际运行状态。')
    if (error) warnings.push(error)
    return warnings
  }, [error, positionsPayload?.data_governance?.warnings, selectedMonitor, selectedMonitor?.data_governance?.warnings, streamStatus])

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

      <DataSourceGovernanceCard
        title="数据源治理"
        description={selectedMonitor?.data_governance?.description || positionsPayload?.data_governance?.description || '实时监控同时依赖分钟线、账户快照和事件流状态，三者必须分开看。'}
        items={governanceItems}
        warnings={governanceWarnings}
      />

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
                {selectedMonitorPrimaryControl ? (
                  <button
                    onClick={() => void handleControl(selectedMonitorPrimaryControl.action)}
                    disabled={!selectedMonitorId || !!actioning}
                    className={`rounded-xl px-3 py-2 text-sm font-semibold disabled:opacity-60 ${selectedMonitorPrimaryControl.className}`}
                  >
                    <selectedMonitorPrimaryControl.icon className={`mr-1 inline h-4 w-4 ${actioning === selectedMonitorPrimaryControl.action ? 'animate-spin' : ''}`} />
                    {selectedMonitorPrimaryControl.label}
                  </button>
                ) : null}
                <button
                  onClick={() => void handleRunOnce()}
                  disabled={!selectedMonitorId || runningOnce || !canRunMonitorOnce(selectedMonitor?.status)}
                  className="rounded-xl bg-indigo-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
                >
                  <Activity className="mr-1 inline h-4 w-4" />
                  {runningOnce ? '执行中' : '立即跑一轮'}
                </button>
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
                  {(() => {
                    const strategy = getMonitorStrategy(item)
                    const primaryControl = primaryControlMeta(item.status)
                    return (
                      <>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-900 dark:text-white">{item.name}</div>
                      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        策略：{strategy?.name || item.strategy_id} ｜ 账户：{item.account_key} ｜ 模式：{item.execution_mode === 'auto' ? '自动交易' : '仅监控'}
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className={`rounded-full px-2 py-1 text-[11px] ${strategyRuntimeTone(strategy, item)}`}>
                          策略状态：{strategyRuntimeLabel(strategy, item)}
                        </span>
                        {strategy ? (
                          <span className={`rounded-full px-2 py-1 text-[11px] ${strategyLifecycleTone(strategy.status)}`}>
                            生命周期：{strategyLifecycleLabel(strategy.status)}
                          </span>
                        ) : null}
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
                    {(() => {
                      const performance = getMonitorPerformance(item)
                      return (
                        <>
                    <div className="rounded-2xl bg-white/80 px-3 py-3 dark:bg-slate-900/70">
                      <div className="text-[11px] tracking-[0.16em] text-slate-400">今日收益</div>
                      <div className={`mt-2 text-sm font-semibold ${pnlTone(performance.todayPnl)}`}>
                        {formatCurrency(performance.todayPnl)}
                        {performance.todayPnlPct != null ? ` ｜ ${formatPercent(performance.todayPnlPct)}` : ''}
                      </div>
                    </div>
                    <div className="rounded-2xl bg-white/80 px-3 py-3 dark:bg-slate-900/70">
                      <div className="text-[11px] tracking-[0.16em] text-slate-400">累计收益</div>
                      <div className={`mt-2 text-sm font-semibold ${pnlTone(performance.totalPnl)}`}>
                        {formatCurrency(performance.totalPnl)}
                        {performance.totalPnlPct != null ? ` ｜ ${formatPercent(performance.totalPnlPct)}` : ''}
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
                        {formatNumber(performance.positionCount)}
                      </div>
                    </div>
                        </>
                      )
                    })()}
                  </div>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      最后心跳：{formatDateTime(item.last_heartbeat_at)}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={event => {
                          event.stopPropagation()
                          void handleControl(primaryControl.action, item.id)
                        }}
                        disabled={!!actioning}
                        className={`rounded-xl px-3 py-2 text-xs font-semibold disabled:opacity-60 ${primaryControl.className}`}
                      >
                        <primaryControl.icon className={`mr-1 inline h-3.5 w-3.5 ${actioning === primaryControl.action ? 'animate-spin' : ''}`} />
                        {primaryControl.label}
                      </button>
                      <button
                        onClick={event => {
                          event.stopPropagation()
                          void handleControl('stop', item.id)
                        }}
                        disabled={!!actioning || !canStopMonitor(item.status)}
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
                      </>
                    )
                  })()}
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
                    账户：{positionsPayload?.account?.account_name || selectedMonitor.account_key} ｜ 显示当前监控策略覆盖股票的持仓列表
                  </div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    监控池：实际解析 {selectedMonitor.display_symbol_count ?? selectedMonitor.resolved_symbol_count ?? 0} 只
                    {typeof selectedMonitor.manual_symbol_count === 'number' ? ` ｜ 手动配置 ${selectedMonitor.manual_symbol_count} 只` : ''}
                  </div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    策略收益口径：当前持仓 {strategyPerformance.positionCount} 只 ｜ 今日 {formatCurrency(strategyPerformance.todayPnl)} ｜ 累计 {formatCurrency(strategyPerformance.totalPnl)}
                  </div>
                  <div className="mt-4">
                    <VirtualList
                      items={strategyPositions}
                      height={560}
                      estimateSize={136}
                      gap={12}
                      overscan={4}
                      className="pr-1"
                      empty={<div className="rounded-2xl bg-slate-50 px-4 py-8 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">当前策略暂无持仓股票。</div>}
                      itemKey={(position) => `${position.symbol}-${position.account_id}`}
                      renderItem={(position) => (
                        <div>
                          <div className="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
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
                        </div>
                      )}
                    />
                  </div>
                </div>

                <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                  <div className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-white">
                    <Activity className="h-5 w-5 text-blue-500" />
                    事件流动
                  </div>
                  <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    {eventFlowTab === 'trading'
                      ? '交易执行只显示信号、委托、成交、撤补、拒单、风控拦截和真实持仓数量变化。'
                      : '运行诊断显示每轮监控、分钟线采集、无信号、重复信号跳过和持仓快照刷新。'}
                  </div>
                  <div className="mt-4 flex w-full rounded-xl bg-slate-100 p-1 text-xs font-semibold dark:bg-slate-950">
                    {[
                      { key: 'trading' as const, label: '交易执行', count: eventFlowItems.length },
                      { key: 'diagnostics' as const, label: '运行诊断', count: diagnosticFlowItems.length },
                    ].map(tab => (
                      <button
                        key={tab.key}
                        type="button"
                        onClick={() => setEventFlowTab(tab.key)}
                        className={`flex-1 rounded-lg px-3 py-2 transition ${
                          eventFlowTab === tab.key
                            ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white'
                            : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                        }`}
                      >
                        {tab.label} {tab.count}
                      </button>
                    ))}
                  </div>
                  <div className="mt-4 pr-1">
                    <VirtualList
                      items={activeEventFlowItems}
                      height={980}
                      estimateSize={172}
                      gap={12}
                      overscan={5}
                      empty={<div className="rounded-2xl bg-slate-50 px-4 py-8 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">{activeEventFlowEmptyText}</div>}
                      itemKey={(item) => item.id}
                      renderItem={(item) => (
                        <div>
                          <div className={`rounded-2xl border border-l-4 p-4 ${eventTone(item)} ${eventAccent(item)}`}>
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${eventSideTone(item)}`}>
                                    {eventSideLabel(item)}
                                  </span>
                                  {(() => {
                                    const symbol = eventSymbol(item)
                                    const name = eventSecurityName(item, strategyPositionNameMap)
                                    if (!symbol && !name) {
                                      return (
                                        <span className="rounded-full bg-white/80 px-2 py-1 text-[11px] font-medium text-slate-500 shadow-sm dark:bg-slate-900/70 dark:text-slate-300">
                                          --
                                        </span>
                                      )
                                    }
                                    return (
                                      <>
                                        {symbol ? (
                                          <span className="rounded-full bg-white/80 px-2 py-1 text-[11px] font-medium text-slate-500 shadow-sm dark:bg-slate-900/70 dark:text-slate-300">
                                            {symbol}
                                          </span>
                                        ) : null}
                                        {name ? (
                                          <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                                            {name}
                                          </span>
                                        ) : null}
                                      </>
                                    )
                                  })()}
                                </div>
                                <div className="mt-2 text-sm font-medium text-slate-800 dark:text-slate-100">
                                  {getEventSummary(item, strategyPositionMap) || '事件已记录'}
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
                                {eventTagLabel(item)}
                              </span>
                              {item.risk_payload?.reason ? (
                                <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                                  风控：{String(item.risk_payload.reason)}
                                </span>
                              ) : null}
                            </div>
                            {renderEventDetail(item)}
                            {Object.keys(item.error_payload || {}).length ? (
                              <div className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
                                异常：{JSON.stringify(item.error_payload)}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      )}
                    />
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
                    <div className="mt-1 text-xs text-slate-400 dark:text-slate-500">
                      行情采样频率；交易指令会按监控 K 线去重，同一 K 线内同一信号只触发一次。
                    </div>
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
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className={`rounded-full px-2 py-1 text-[11px] ${strategyRuntimeTone(selectedStrategy, null)}`}>
                      策略状态：{strategyRuntimeLabel(selectedStrategy, null)}
                    </span>
                    {selectedStrategy ? (
                      <span className={`rounded-full px-2 py-1 text-[11px] ${strategyLifecycleTone(selectedStrategy.status)}`}>
                        生命周期：{strategyLifecycleLabel(selectedStrategy.status)}
                      </span>
                    ) : null}
                  </div>
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
