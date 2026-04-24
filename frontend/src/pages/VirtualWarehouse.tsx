import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Database, Landmark, RefreshCw, Send, Wifi, WifiOff, XCircle } from 'lucide-react'

import { api } from '@/services/api'
import type { QmtBulkSellTask, VirtualWarehouseDiagnosticsResponse, VirtualWarehouseOverviewResponse, VirtualWarehousePosition, VirtualWarehouseOrder, VirtualWarehouseTrade } from '@/types'

function formatMoney(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '--'
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 2 }).format(value)
}

function formatPercent(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '--'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

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

function tone(value?: number | null) {
  if (value == null) return 'text-slate-500'
  if (value > 0) return 'text-rose-600 dark:text-rose-400'
  if (value < 0) return 'text-emerald-600 dark:text-emerald-400'
  return 'text-slate-500'
}

function normalizeTimeValue(value?: string | null) {
  if (!value) return null
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) return parsed

  const digits = value.replace(/[^\d]/g, '')
  if (digits.length === 14) {
    const year = Number(digits.slice(0, 4))
    const month = Number(digits.slice(4, 6)) - 1
    const day = Number(digits.slice(6, 8))
    const hour = Number(digits.slice(8, 10))
    const minute = Number(digits.slice(10, 12))
    const second = Number(digits.slice(12, 14))
    const fallback = new Date(year, month, day, hour, minute, second)
    if (!Number.isNaN(fallback.getTime())) return fallback
  }

  if (digits.length === 8) {
    const year = Number(digits.slice(0, 4))
    const month = Number(digits.slice(4, 6)) - 1
    const day = Number(digits.slice(6, 8))
    const fallback = new Date(year, month, day)
    if (!Number.isNaN(fallback.getTime())) return fallback
  }

  return null
}

function isSameLocalDate(value?: string | null, target = new Date()) {
  const date = normalizeTimeValue(value)
  if (!date) return false
  return (
    date.getFullYear() === target.getFullYear()
    && date.getMonth() === target.getMonth()
    && date.getDate() === target.getDate()
  )
}

function displaySecurityName(name?: string | null, symbol?: string | null) {
  const trimmedName = String(name || '').trim()
  const trimmedSymbol = String(symbol || '').trim().toUpperCase()
  if (!trimmedName) return '名称待更新'
  if (trimmedName.toUpperCase() === trimmedSymbol) return '名称待更新'
  return trimmedName
}

function normalizeOrderQuantity(value?: number | null) {
  const quantity = Math.max(Number(value || 0), 0)
  return Math.floor(quantity / 100) * 100
}

function MetricCard({
  label,
  value,
  subValue,
  valueClassName,
  subValueClassName,
}: {
  label: string
  value: string
  subValue?: string
  valueClassName?: string
  subValueClassName?: string
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs tracking-[0.16em] text-slate-400">{label}</p>
      <p className={`mt-2 text-2xl font-semibold ${valueClassName || 'text-slate-900 dark:text-white'}`}>{value}</p>
      {subValue ? <p className={`mt-1 text-sm ${subValueClassName || 'text-slate-500 dark:text-slate-400'}`}>{subValue}</p> : null}
    </div>
  )
}

interface WarehousePageProps {
  roleFilter?: 'paper' | 'live'
  pageTitle?: string
  pageDescription?: string
}

function parseSseBlock(block: string): { event: string; data: Record<string, unknown> } | null {
  const lines = block.split('\n').map(line => line.trim()).filter(Boolean)
  if (!lines.length) return null
  let event = 'message'
  let dataLine = ''
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.replace('event:', '').trim()
    if (line.startsWith('data:')) dataLine = line.replace('data:', '').trim()
  }
  if (!dataLine) return null
  try {
    return { event, data: JSON.parse(dataLine) as Record<string, unknown> }
  } catch {
    return null
  }
}

function isBulkSellTaskActive(status?: string | null) {
  return ['pending', 'running'].includes(String(status || '').trim().toLowerCase())
}

export function WarehousePage({
  roleFilter = 'paper',
  pageTitle = '虚拟仓',
  pageDescription = '对接 QMT 模拟账户，展示资产总览与实时持仓。',
}: WarehousePageProps) {
  const [payload, setPayload] = useState<VirtualWarehouseOverviewResponse | null>(null)
  const [selectedAccountKey, setSelectedAccountKey] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [diagnosing, setDiagnosing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [diagnostics, setDiagnostics] = useState<VirtualWarehouseDiagnosticsResponse | null>(null)
  const [submittingOrder, setSubmittingOrder] = useState(false)
  const [bulkSelling, setBulkSelling] = useState(false)
  const [bulkSellTask, setBulkSellTask] = useState<QmtBulkSellTask | null>(null)
  const [cancellingOrderId, setCancellingOrderId] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [selectedPositionSymbol, setSelectedPositionSymbol] = useState<string | null>(null)
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null)
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null)
  const [orderForm, setOrderForm] = useState({
    symbol: '',
    side: 'buy',
    quantity: 100,
    priceType: 'limit',
    price: '',
    strategyName: 'TradingAgents',
    remark: '',
  })
  const bulkSellStreamAbortRef = useRef<AbortController | null>(null)
  const account = payload?.account
  const connection = payload?.connection
  const positions = payload?.positions || []
  const orders = useMemo(
    () => [...(payload?.orders || [])]
      .filter(item => isSameLocalDate(item.order_time))
      .sort((left, right) => {
        const rightTime = normalizeTimeValue(right.order_time)?.getTime() || 0
        const leftTime = normalizeTimeValue(left.order_time)?.getTime() || 0
        return rightTime - leftTime
      }),
    [payload?.orders],
  )
  const trades = useMemo(
    () => [...(payload?.trades || [])]
      .filter(item => isSameLocalDate(item.trade_time))
      .sort((left, right) => {
        const rightTime = normalizeTimeValue(right.trade_time)?.getTime() || 0
        const leftTime = normalizeTimeValue(left.trade_time)?.getTime() || 0
        return rightTime - leftTime
      }),
    [payload?.trades],
  )

  const handleFillOrderFromPosition = useCallback((position: VirtualWarehousePosition) => {
    const sellableQuantity = normalizeOrderQuantity(position.available_position || position.current_position)
    setSelectedPositionSymbol(position.symbol)
    setSelectedOrderId(null)
    setSelectedTradeId(null)
    setOrderForm(prev => ({
      ...prev,
      symbol: position.symbol,
      side: 'sell',
      quantity: sellableQuantity > 0 ? sellableQuantity : prev.quantity,
      priceType: 'latest',
      price: '',
      remark: `持仓带入 ${displaySecurityName(position.name, position.symbol)} ${position.symbol}`,
    }))
    setActionMessage(
      `已带入 ${displaySecurityName(position.name, position.symbol)}，默认按最新价卖出 ${sellableQuantity || position.available_position || position.current_position || 0} 股。`,
    )
    setError(null)
  }, [])

  const handleFillOrderFromRecentOrder = useCallback((order: VirtualWarehouseOrder) => {
    const quantity = normalizeOrderQuantity((order.quantity || 0) - (order.filled_quantity || 0)) || normalizeOrderQuantity(order.quantity)
    setSelectedOrderId(order.order_id)
    setSelectedTradeId(null)
    setSelectedPositionSymbol(order.symbol)
    setOrderForm(prev => ({
      ...prev,
      symbol: order.symbol,
      side: String(order.side || prev.side).toLowerCase(),
      quantity: quantity > 0 ? quantity : prev.quantity,
      priceType: order.price != null ? 'limit' : 'latest',
      price: order.price != null ? String(order.price) : '',
      remark: `最近委托带入 ${displaySecurityName(order.name, order.symbol)} ${order.order_id}`,
    }))
    setActionMessage(`已带入最近委托 ${order.order_id || '--'}，可继续提交同股票委托${order.can_cancel ? '或直接点击撤单' : ''}。`)
    setError(null)
  }, [])

  const handleFillOrderFromTrade = useCallback((trade: VirtualWarehouseTrade) => {
    const quantity = normalizeOrderQuantity(trade.quantity)
    setSelectedTradeId(trade.trade_id)
    setSelectedOrderId(null)
    setSelectedPositionSymbol(trade.symbol)
    setOrderForm(prev => ({
      ...prev,
      symbol: trade.symbol,
      side: String(trade.side || '').toLowerCase() === 'buy' ? 'sell' : 'buy',
      quantity: quantity > 0 ? quantity : prev.quantity,
      priceType: 'latest',
      price: '',
      remark: `最近成交带入 ${displaySecurityName(trade.name, trade.symbol)} ${trade.trade_id}`,
    }))
    setActionMessage(`已切换到成交股票 ${displaySecurityName(trade.name, trade.symbol)}，默认按最新价准备${String(trade.side || '').toLowerCase() === 'buy' ? '卖出' : '买入'}。`)
    setError(null)
  }, [])

  const load = useCallback(async (silent = false, accountKey?: string | null) => {
    try {
      if (silent) setRefreshing(true)
      else setLoading(true)
      let response = await api.getQmtVirtualWarehouseOverview(accountKey || undefined)
      if (!accountKey) {
        const active = response.accounts?.find(item => item.account_key === response.active_account_key)
        const firstMatch = response.accounts?.find(item => item.role === roleFilter)
        if (firstMatch && active?.role !== roleFilter) {
          response = await api.getQmtVirtualWarehouseOverview(firstMatch.account_key)
        }
      }
      setPayload(response)
      setSelectedAccountKey(response.active_account_key || accountKey || null)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : `${pageTitle}加载失败`)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [pageTitle, roleFilter])

  const bulkSellStorageKey = useMemo(
    () => `qmt-bulk-sell-task:${roleFilter}:${selectedAccountKey || payload?.active_account_key || 'default'}`,
    [payload?.active_account_key, roleFilter, selectedAccountKey],
  )

  const stopBulkSellStream = useCallback(() => {
    bulkSellStreamAbortRef.current?.abort()
    bulkSellStreamAbortRef.current = null
  }, [])

  const handleBulkSellTaskState = useCallback(async (task: QmtBulkSellTask) => {
    setBulkSellTask(task)
    const active = isBulkSellTaskActive(task.status)
    setBulkSelling(active)
    if (typeof window !== 'undefined') {
      if (active) window.localStorage.setItem(bulkSellStorageKey, task.id)
      else window.localStorage.removeItem(bulkSellStorageKey)
    }
    if (!active) {
      stopBulkSellStream()
      if (task.overview) {
        setPayload(task.overview)
        setSelectedAccountKey(task.overview.active_account_key || task.account_key)
      } else {
        await load(true, task.account_key)
      }
      setActionMessage(
        task.failure_count > 0
          ? `一键卖出已完成：成功 ${task.success_count} 笔，失败 ${task.failure_count} 笔。`
          : `一键卖出已完成：成功 ${task.success_count} 笔。`,
      )
      setError(task.failure_count > 0 ? `部分失败：${(task.recent_failures || []).slice(0, 3).join('；')}` : null)
    }
  }, [bulkSellStorageKey, load, stopBulkSellStream])

  const connectBulkSellStream = useCallback(async (taskId: string) => {
    stopBulkSellStream()
    const controller = new AbortController()
    bulkSellStreamAbortRef.current = controller
    try {
      const response = await api.streamQmtBulkSellTask(taskId, controller.signal)
      const reader = response.body?.getReader()
      if (!reader) throw new Error('清仓任务流不可用')
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''
        for (const block of blocks) {
          const parsed = parseSseBlock(block)
          if (!parsed) continue
          if (parsed.event === 'state' || parsed.event === 'done') {
            const task = parsed.data?.task as QmtBulkSellTask | undefined
            if (task) await handleBulkSellTaskState(task)
          } else if (parsed.event === 'error') {
            const message = String(parsed.data?.message || '清仓任务流异常')
            setError(message)
          }
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return
      setError(err instanceof Error ? err.message : '清仓任务流连接失败')
    } finally {
      if (bulkSellStreamAbortRef.current === controller) {
        bulkSellStreamAbortRef.current = null
      }
    }
  }, [handleBulkSellTaskState, stopBulkSellStream])

  useEffect(() => {
    void load(false, selectedAccountKey)
  }, [load, selectedAccountKey])

  useEffect(() => {
    if (bulkSellTask && isBulkSellTaskActive(bulkSellTask.status)) return undefined
    const intervalSeconds = payload?.refresh_interval_seconds || 10
    const timer = window.setInterval(() => { void load(true, selectedAccountKey) }, intervalSeconds * 1000)
    return () => window.clearInterval(timer)
  }, [bulkSellTask, load, payload?.refresh_interval_seconds, selectedAccountKey])

  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const taskId = window.localStorage.getItem(bulkSellStorageKey)
    if (!taskId) return undefined
    let cancelled = false
    ;(async () => {
      try {
        const response = await api.getQmtBulkSellTask(taskId)
        if (cancelled) return
        const task = response.task
        setBulkSellTask(task)
        setBulkSelling(isBulkSellTaskActive(task.status))
        if (isBulkSellTaskActive(task.status)) {
          await connectBulkSellStream(task.id)
        } else {
          window.localStorage.removeItem(bulkSellStorageKey)
        }
      } catch {
        window.localStorage.removeItem(bulkSellStorageKey)
      }
    })()
    return () => { cancelled = true }
  }, [bulkSellStorageKey, connectBulkSellStream])

  useEffect(() => () => stopBulkSellStream(), [stopBulkSellStream])

  const handleDiagnose = useCallback(async (runConnectTest = true) => {
    setDiagnosing(true)
    try {
      const response = await api.getQmtVirtualWarehouseDiagnostics(selectedAccountKey || undefined, runConnectTest)
      setDiagnostics(response)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '诊断失败')
    } finally {
      setDiagnosing(false)
    }
  }, [selectedAccountKey])

  const handleSubmitOrder = useCallback(async () => {
    if (roleFilter !== 'paper') {
      setError('实盘仓已只读锁定：禁止从本系统提交 QMT 委托，请切换到虚拟仓。')
      return
    }
    setSubmittingOrder(true)
    setActionMessage(null)
    try {
      const response = await api.submitQmtOrder({
        account_key: payload?.active_account_key || selectedAccountKey || undefined,
        symbol: orderForm.symbol.trim().toUpperCase(),
        side: orderForm.side,
        quantity: Number(orderForm.quantity),
        price_type: orderForm.priceType,
        price: orderForm.priceType === 'limit' ? Number(orderForm.price) : undefined,
        strategy_name: orderForm.strategyName.trim() || undefined,
        order_remark: orderForm.remark.trim() || undefined,
      })
      if (response.overview) {
        setPayload(response.overview)
        setSelectedAccountKey(response.overview.active_account_key || selectedAccountKey)
      }
      setActionMessage(`委托已提交，订单号 ${response.order_result.order_id || '--'}`)
      setError(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'QMT 委托提交失败'
      setActionMessage(null)
      setError(`${message}；已自动刷新账户快照，请核对最近委托和成交。`)
      await load(true, payload?.active_account_key || selectedAccountKey)
    } finally {
      setSubmittingOrder(false)
    }
  }, [load, orderForm, payload?.active_account_key, roleFilter, selectedAccountKey])

  const handleCancelOrder = useCallback(async (orderId: string) => {
    if (roleFilter !== 'paper') {
      setError('实盘仓已只读锁定：禁止从本系统撤销 QMT 委托，请切换到虚拟仓。')
      return
    }
    setCancellingOrderId(orderId)
    setActionMessage(null)
    try {
      const response = await api.cancelQmtOrder(orderId, payload?.active_account_key || selectedAccountKey || undefined)
      setPayload(response.overview)
      setSelectedAccountKey(response.overview.active_account_key || selectedAccountKey)
      setActionMessage(`撤单请求已提交，订单号 ${response.cancel_result.order_id || orderId}`)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'QMT 撤单失败')
    } finally {
      setCancellingOrderId(null)
    }
  }, [payload?.active_account_key, roleFilter, selectedAccountKey])

  const sellablePositions = useMemo(
    () => positions.filter(item => normalizeOrderQuantity(item.available_position || item.current_position) > 0),
    [positions],
  )

  const handleSellAllPositions = useCallback(async () => {
    if (roleFilter !== 'paper') {
      setError('实盘仓已只读锁定：禁止从本系统提交 QMT 委托，请切换到虚拟仓。')
      return
    }
    if (!sellablePositions.length) {
      setError('当前没有可卖出的持仓。')
      return
    }
    const totalQuantity = sellablePositions.reduce(
      (sum, item) => sum + normalizeOrderQuantity(item.available_position || item.current_position),
      0,
    )
    const confirmed = typeof window === 'undefined'
      ? true
      : window.confirm(`确认一键卖出全部持仓吗？\n股票数：${sellablePositions.length} 只\n可卖总股数：${totalQuantity} 股`)
    if (!confirmed) return

    setActionMessage(null)
    setError(null)
    try {
      const response = await api.startQmtBulkSell({
        account_key: payload?.active_account_key || selectedAccountKey || undefined,
        strategy_name: orderForm.strategyName.trim() || 'TradingAgents',
      })
      setBulkSellTask(response.task)
      setBulkSelling(true)
      if (typeof window !== 'undefined') window.localStorage.setItem(bulkSellStorageKey, response.task.id)
      setActionMessage(`一键卖出任务已启动：共 ${response.task.total} 只股票，正在逐笔提交。`)
      await connectBulkSellStream(response.task.id)
    } catch (err) {
      setBulkSelling(false)
      setError(err instanceof Error ? err.message : '一键卖出任务启动失败')
    }
  }, [bulkSellStorageKey, connectBulkSellStream, orderForm.strategyName, payload?.active_account_key, roleFilter, selectedAccountKey, sellablePositions])

  const accountCards = useMemo(() => (payload?.accounts || []).filter(item => item.role === roleFilter), [payload?.accounts, roleFilter])
  const lastQuoteTime = useMemo(() => {
    const quoteTime = positions.find(item => item.quote_time)?.quote_time
    return quoteTime || payload?.fetched_at || null
  }, [payload?.fetched_at, positions])
  const lastSyncTime = payload?.last_synced_at || null

  if (loading) {
    return <div className="rounded-2xl border border-slate-200 bg-white p-8 text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-900">{pageTitle}加载中...</div>
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-indigo-50 p-3 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300">
                <Landmark className="h-6 w-6" />
              </div>
              <div>
                <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">{pageTitle}</h1>
                <p className="text-sm text-slate-500 dark:text-slate-400">{pageDescription}</p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 ${connection?.connected ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300'}`}>
                {connection?.connected ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />}
                {connection?.connected ? '已连接' : '未连接'}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                地址 {connection?.host}:{connection?.port}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                账号 {account?.account_id || connection?.account_id || '--'}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {account?.mode || '极简模式 / Python 策略端'}
              </span>
              <span className="rounded-full bg-indigo-50 px-3 py-1 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
                与跟踪看板独立
              </span>
              <span className={`rounded-full px-3 py-1 ${payload?.is_stale ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'}`}>
                {payload?.is_stale ? '缓存快照' : '实时数据'}
              </span>
            </div>
            {accountCards.length > 1 ? (
              <div className="flex flex-wrap gap-2">
                {accountCards.map(item => {
                  const active = (payload?.active_account_key || selectedAccountKey) === item.account_key
                  return (
                    <button
                      key={item.account_key}
                      type="button"
                      onClick={() => {
                        setSelectedAccountKey(item.account_key)
                        void load(false, item.account_key)
                      }}
                      className={`rounded-xl px-3 py-2 text-sm transition ${
                        active
                          ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                      }`}
                    >
                      {item.account?.account_name || item.connection.account_name}
                      <span className="ml-2 text-xs opacity-80">[{item.role === 'paper' ? '模拟' : '实盘'}]</span>
                    </button>
                  )
                })}
              </div>
            ) : null}
            {connection?.message ? (
              <p className={`text-sm ${connection.connected ? 'text-slate-500 dark:text-slate-400' : 'text-amber-600 dark:text-amber-300'}`}>{connection.message}</p>
            ) : null}
            {actionMessage ? <p className="text-sm text-emerald-600 dark:text-emerald-300">{actionMessage}</p> : null}
            {error ? <p className="text-sm text-rose-600 dark:text-rose-300">{error}</p> : null}
            {bulkSellTask ? (
              <div className="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-500/10 dark:text-amber-200">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <span>清仓进度 {bulkSellTask.processed}/{bulkSellTask.total}</span>
                  <span>成功 {bulkSellTask.success_count}</span>
                  <span>失败 {bulkSellTask.failure_count}</span>
                  <span>状态 {bulkSellTask.status === 'running' ? '执行中' : bulkSellTask.status === 'completed' ? '已完成' : bulkSellTask.status === 'completed_with_errors' ? '部分完成' : bulkSellTask.status === 'failed' ? '失败' : '待执行'}</span>
                  {bulkSellTask.current_symbol ? (
                    <span>
                      当前：{bulkSellTask.current_name || '名称待更新'} {bulkSellTask.current_symbol}
                    </span>
                  ) : null}
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-amber-100 dark:bg-amber-950/60">
                  <div
                    className="h-full rounded-full bg-amber-500 transition-all"
                    style={{ width: `${bulkSellTask.total ? Math.min(100, (bulkSellTask.processed / bulkSellTask.total) * 100) : 0}%` }}
                  />
                </div>
                {bulkSellTask.recent_failures.length ? (
                  <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
                    最近失败：{bulkSellTask.recent_failures.join('；')}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void load(true)}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
              刷新
            </button>
            <button
              type="button"
              onClick={() => void handleDiagnose(true)}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <Database className={`h-4 w-4 ${diagnosing ? 'animate-spin' : ''}`} />
              {diagnosing ? '诊断中...' : '连接诊断'}
            </button>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <MetricCard label="证券账户名称" value={account?.security_account_name || connection?.account_name || '--'} subValue={account?.account_id ? `证券账号 ${account.account_id}` : '待连接 QMT 账户'} />
        <MetricCard label="总资产" value={formatMoney(account?.total_asset)} subValue={`总市值 ${formatMoney(account?.market_value)}`} />
        <MetricCard
          label="总盈亏"
          value={formatMoney(account?.total_pnl)}
          subValue={formatPercent(account?.total_pnl_pct)}
          valueClassName={tone(account?.total_pnl)}
          subValueClassName={tone(account?.total_pnl_pct)}
        />
        <MetricCard
          label="当日盈亏"
          value={formatMoney(account?.today_pnl)}
          subValue={lastQuoteTime ? `最近行情 ${lastQuoteTime}` : '等待行情刷新'}
          valueClassName={tone(account?.today_pnl)}
        />
        <MetricCard label="可用资金" value={formatMoney(account?.available_cash)} subValue={`持仓数量 ${account?.position_count || 0} 只`} />
        <MetricCard label="数据同步时间" value={formatDateTime(lastSyncTime)} subValue={payload?.is_stale ? '当前展示最近一次成功同步的缓存快照' : '当前展示最新成功同步数据'} />
        <MetricCard label="数据源" value={connection?.provider || 'xtquant'} subValue={connection?.userdata_path ? `用户目录 ${connection.userdata_path}` : '请在后端配置 QMT_USERDATA_PATH'} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        {roleFilter === 'paper' ? (
        <>
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">仓位隔离说明</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">当前页面只展示 QMT 仓位，不会自动写入跟踪看板，也不会覆盖跟踪看板原有仓位。</p>
          <div className="mt-4 space-y-2 text-sm text-slate-600 dark:text-slate-300">
            <div>仓位用途：{roleFilter === 'paper' ? '模拟测试 / 策略联调' : 'QMT 实盘账户映射'}</div>
            <div>跟踪看板：保持独立，不从当前仓位自动同步</div>
            <div>分析上下文：默认仍读取跟踪看板持仓，不读取当前仓位</div>
            <div>最近行情：{lastQuoteTime || '暂无'}</div>
            <div>最近同步：{formatDateTime(lastSyncTime)}</div>
          </div>
        </div>
        </>
        ) : (
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">实盘账户说明</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">实盘仓只负责映射 QMT 实盘资产与交易，不会改写跟踪看板。跟踪看板继续按原逻辑独立维护。</p>
          <div className="mt-4 space-y-2 text-sm text-slate-600 dark:text-slate-300">
            <div>推荐用途：核对 QMT 实盘资产、持仓、委托、成交</div>
            <div>桥接方式：单独 bridge 进程 + 单独端口</div>
            <div>当前页面支持：实时查询、委托/成交查看</div>
            <div className="text-amber-600 dark:text-amber-300">安全锁：实盘仓只读，页面与后端均禁止下单和撤单</div>
          </div>
        </div>
        )}
        {roleFilter === 'paper' ? (
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">QMT 交易控制台</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">直接向当前 QMT 账户提交买卖委托，支持提交后立即回显到最近委托。点击上方持仓行可自动带入股票、数量和价格模式。</p>
          {selectedPositionSymbol ? (
            <div className="mt-3 rounded-2xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-950 dark:text-slate-300">
              当前已带入：{selectedPositionSymbol}，默认使用“卖出 + 最新价”。
            </div>
          ) : null}
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">股票代码</label>
              <input
                value={orderForm.symbol}
                onChange={e => setOrderForm(prev => ({ ...prev, symbol: e.target.value }))}
                placeholder="如 000001.SZ"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">买卖方向</label>
              <select
                value={orderForm.side}
                onChange={e => setOrderForm(prev => ({ ...prev, side: e.target.value }))}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              >
                <option value="buy">买入</option>
                <option value="sell">卖出</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">委托数量</label>
              <input
                type="number"
                min={1}
                step={100}
                value={orderForm.quantity}
                onChange={e => setOrderForm(prev => ({ ...prev, quantity: Number(e.target.value || 0) }))}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">价格模式</label>
              <select
                value={orderForm.priceType}
                onChange={e => setOrderForm(prev => ({ ...prev, priceType: e.target.value }))}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              >
                <option value="limit">限价</option>
                <option value="latest">最新价</option>
                <option value="opponent">对手价</option>
                <option value="self_best">本方最优</option>
                <option value="best5_cancel">最优五档剩撤</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">委托价格</label>
              <input
                type="number"
                min={0}
                step="0.001"
                value={orderForm.price}
                onChange={e => setOrderForm(prev => ({ ...prev, price: e.target.value }))}
                disabled={orderForm.priceType !== 'limit'}
                placeholder={orderForm.priceType === 'limit' ? '请输入价格' : '非限价可留空'}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">策略名</label>
              <input
                value={orderForm.strategyName}
                onChange={e => setOrderForm(prev => ({ ...prev, strategyName: e.target.value }))}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <div className="md:col-span-2">
              <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">备注</label>
              <input
                value={orderForm.remark}
                onChange={e => setOrderForm(prev => ({ ...prev, remark: e.target.value }))}
                placeholder="可填写策略版本、用途等"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void handleSubmitOrder()}
              disabled={submittingOrder || !orderForm.symbol.trim() || !orderForm.quantity || (orderForm.priceType === 'limit' && !orderForm.price)}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              <Send className="h-4 w-4" />
              {submittingOrder ? '提交中...' : '提交 QMT 委托'}
            </button>
            <div className="text-xs text-slate-500 dark:text-slate-400">
              当前账户：{account?.account_name || connection?.account_name || '--'} · 账号 {account?.account_id || connection?.account_id || '--'}
            </div>
          </div>
        </div>
        ) : (
        <div className="rounded-3xl border border-amber-200 bg-amber-50 p-6 shadow-sm dark:border-amber-900/60 dark:bg-amber-950/20">
          <h2 className="text-lg font-semibold text-amber-900 dark:text-amber-100">实盘交易已锁定</h2>
          <p className="mt-1 text-sm text-amber-700 dark:text-amber-200">
            实盘仓仅用于资产、持仓、委托和成交核对。为避免开盘期间误操作，本页面不提供实盘下单或撤单入口。
          </p>
          <div className="mt-4 space-y-2 text-sm text-amber-700 dark:text-amber-200">
            <div>允许：刷新资产、查看持仓、查看最近委托、查看最近成交</div>
            <div>禁止：提交委托、撤单、策略自动交易</div>
            <div>如需联调交易，请切换到虚拟仓模拟账户。</div>
          </div>
        </div>
        )}
      </section>

      {accountCards.length > 0 ? (
        <section className="grid gap-4 lg:grid-cols-2">
          {accountCards.map(item => (
            <button
              key={item.account_key}
              type="button"
              onClick={() => {
                setSelectedAccountKey(item.account_key)
                void load(false, item.account_key)
              }}
              className={`rounded-2xl border p-4 text-left shadow-sm transition ${
                (payload?.active_account_key || selectedAccountKey) === item.account_key
                  ? 'border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900'
                  : 'border-slate-200 bg-white text-slate-800 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100'
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-base font-semibold">{item.account?.account_name || item.connection.account_name}</div>
                  <div className="mt-1 text-xs opacity-80">Key: {item.account_key} · {item.role === 'paper' ? '模拟仓' : '实盘仓'}</div>
                </div>
                <span className={`rounded-full px-2 py-1 text-xs ${
                  item.connection.connected
                    ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300'
                    : 'bg-amber-500/15 text-amber-600 dark:text-amber-300'
                }`}>
                  {item.connection.connected ? '在线' : '未连通'}
                </span>
              </div>
              <div className="mt-3 grid gap-2 text-sm md:grid-cols-2">
                <div>账号：{item.connection.account_id || '--'}</div>
                <div>总资产：{formatMoney(item.summary.total_asset)}</div>
                <div className={tone(item.summary.total_pnl)}>总盈亏：{formatMoney(item.summary.total_pnl)}</div>
                <div className={tone(item.summary.today_pnl)}>当日盈亏：{formatMoney(item.summary.today_pnl)}</div>
              </div>
            </button>
          ))}
        </section>
      ) : null}

      {diagnostics ? (
        <section className="rounded-3xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">连接诊断</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              已检查 {diagnostics.summary.total} 个账户，配置就绪 {diagnostics.summary.ready} 个，连通成功 {diagnostics.summary.connected} 个。
            </p>
          </div>
          <div className="space-y-4 p-6">
            {diagnostics.items.map(item => (
              <div key={item.account_key} className="rounded-2xl border border-slate-200 p-4 dark:border-slate-800">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-base font-semibold text-slate-900 dark:text-white">
                      {item.account_name} <span className="text-xs text-slate-400">({item.account_key})</span>
                    </div>
                    <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                      {item.role === 'paper' ? '模拟仓' : '实盘仓'} · {item.host}:{item.port} · 账号 {item.account_id || '--'}
                    </div>
                  </div>
                  <span className={`rounded-full px-3 py-1 text-xs ${
                    item.connect_test.connected
                      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'
                      : item.ready
                        ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300'
                        : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
                  }`}>
                    {item.connect_test.connected ? '已连通' : item.ready ? '可测试' : '待配置'}
                  </span>
                </div>
                <div className="mt-3 grid gap-2 text-sm md:grid-cols-2 xl:grid-cols-3">
                  <div>启用：{item.checks.enabled ? '是' : '否'}</div>
                  <div>账号配置：{item.checks.account_id_configured ? '已配置' : '缺失'}</div>
                  <div>目录配置：{item.checks.userdata_path_configured ? '已配置' : '缺失'}</div>
                  <div>目录存在：{item.checks.userdata_path_exists ? '是' : '否'}</div>
                  <div>xtquant：{item.checks.xtquant_installed ? '已安装' : '未安装'}</div>
                  <div>端口探测：{item.tcp_probe.message}</div>
                  <div>桥接探测：{item.bridge_probe.message}</div>
                  <div>连接测试：{item.connect_test.message}</div>
                </div>
                <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                  <div>userdata：{item.userdata_path || '--'}</div>
                  <div>{item.xtquant_message}</div>
                  {item.warnings.length ? <div className="mt-1 text-amber-600 dark:text-amber-300">告警：{item.warnings.join('；')}</div> : null}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-3xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">持仓列表</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">展示 QMT 仓位快照，持股天数按首次同步时间持续跟踪。</p>
          </div>
          <div className="flex items-center gap-3">
            {roleFilter === 'paper' ? (
              <button
                type="button"
                onClick={() => void handleSellAllPositions()}
                disabled={bulkSelling || !sellablePositions.length}
                className="inline-flex items-center gap-2 rounded-xl border border-rose-200 px-3 py-2 text-xs font-medium text-rose-600 disabled:opacity-50 dark:border-rose-900 dark:text-rose-300"
              >
                <Send className="h-3.5 w-3.5" />
                {bulkSelling ? '清仓提交中...' : '一键卖出全部持仓'}
              </button>
            ) : null}
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-300">
              共 {positions.length} 只
            </span>
          </div>
        </div>
        {!positions.length ? (
          <div className="px-6 py-10 text-sm text-slate-500 dark:text-slate-400">当前暂无可展示的 QMT 持仓。请确认 QMT 账户已配置且已成功连接。</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-500 dark:bg-slate-950/50 dark:text-slate-400">
                <tr>
                  <th className="px-4 py-3 font-medium">股票名称 / 代码</th>
                  <th className="px-4 py-3 font-medium">盈亏金额 / 比例</th>
                  <th className="px-4 py-3 font-medium">持仓 / 可用</th>
                  <th className="px-4 py-3 font-medium">成本 / 现价</th>
                  <th className="px-4 py-3 font-medium">当日盈亏</th>
                  <th className="px-4 py-3 font-medium">持股天数</th>
                  <th className="px-4 py-3 font-medium">回本涨幅</th>
                  <th className="px-4 py-3 font-medium">市值占比</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((item: VirtualWarehousePosition) => (
                  <tr
                    key={item.symbol}
                    className={`border-t border-slate-100 dark:border-slate-800 ${
                      roleFilter === 'paper' ? 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-950/50' : ''
                    } ${selectedPositionSymbol === item.symbol ? 'bg-slate-50 dark:bg-slate-950/50' : ''}`}
                    onClick={roleFilter === 'paper' ? () => handleFillOrderFromPosition(item) : undefined}
                    title={roleFilter === 'paper' ? '点击带入交易控制台' : undefined}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900 dark:text-white">{displaySecurityName(item.name, item.symbol)}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">{item.symbol}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className={tone(item.total_pnl)}>{formatMoney(item.total_pnl)}</div>
                      <div className={`text-xs ${tone(item.total_pnl_pct)}`}>{formatPercent(item.total_pnl_pct)}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-200">
                      <div>{item.current_position}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">可用 {item.available_position}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-200">
                      <div>成本 {item.average_cost?.toFixed(3) ?? '--'}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">现价 {item.current_price?.toFixed(3) ?? '--'}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className={tone(item.today_pnl)}>{formatMoney(item.today_pnl)}</div>
                      <div className={`text-xs ${tone(item.today_pnl_pct)}`}>{formatPercent(item.today_pnl_pct)}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-200">{item.holding_days} 天</td>
                    <td className={`px-4 py-3 ${tone(item.break_even_rise_pct)}`}>{formatPercent(item.break_even_rise_pct)}</td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-200">
                      <div>{formatMoney(item.market_value)}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">{formatPercent(item.position_pct)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-3xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-800">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">最近委托</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">仅展示当日委托，按时间倒序排列，便于核对最新状态。</p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-300">
              {orders.length} 条
            </span>
          </div>
          <div className="max-h-[360px] overflow-auto px-6 py-4">
            {!orders.length ? (
              <div className="text-sm text-slate-500 dark:text-slate-400">当前没有可展示的委托数据。</div>
            ) : (
              <div className="space-y-3">
                {orders.map((item: VirtualWarehouseOrder) => (
                  <div
                    key={`${item.order_id}-${item.symbol}`}
                    className={`rounded-2xl border border-slate-100 p-4 dark:border-slate-800 ${roleFilter === 'paper' ? 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-950/50' : ''} ${selectedOrderId === item.order_id ? 'bg-slate-50 dark:bg-slate-950/50' : ''}`}
                    onClick={roleFilter === 'paper' ? () => handleFillOrderFromRecentOrder(item) : undefined}
                    title={roleFilter === 'paper' ? '点击带入交易控制台' : undefined}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium text-slate-900 dark:text-white">{displaySecurityName(item.name, item.symbol)}</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">{item.symbol} · 委托号 {item.order_id || '--'}</div>
                      </div>
                      <div className="flex items-center gap-2">
                        {roleFilter === 'paper' && item.can_cancel ? (
                          <button
                            type="button"
                            onClick={event => {
                              event.stopPropagation()
                              void handleCancelOrder(item.order_id)
                            }}
                            disabled={cancellingOrderId === item.order_id}
                            className="inline-flex items-center gap-1 rounded-lg border border-rose-200 px-2.5 py-1 text-xs text-rose-600 disabled:opacity-50 dark:border-rose-900 dark:text-rose-300"
                          >
                            <XCircle className="h-3.5 w-3.5" />
                            {cancellingOrderId === item.order_id ? '撤单中...' : '撤单'}
                          </button>
                        ) : null}
                        <span className="text-xs text-slate-500 dark:text-slate-400">{formatDateTime(item.order_time)}</span>
                      </div>
                    </div>
                    <div className="mt-3 grid gap-2 text-sm md:grid-cols-2">
                      <div>方向：{item.side}</div>
                      <div>状态：{item.status}</div>
                      <div>价格：{item.price != null ? item.price.toFixed(3) : '--'}</div>
                      <div>数量：{item.quantity ?? '--'} / 已成 {item.filled_quantity ?? '--'}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-800">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">最近成交</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">仅展示当日成交，按时间倒序排列，便于核对最新回报。</p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-300">
              {trades.length} 条
            </span>
          </div>
          <div className="max-h-[360px] overflow-auto px-6 py-4">
            {!trades.length ? (
              <div className="text-sm text-slate-500 dark:text-slate-400">当前没有可展示的成交数据。</div>
            ) : (
              <div className="space-y-3">
                {trades.map((item: VirtualWarehouseTrade) => (
                  <div
                    key={`${item.trade_id}-${item.symbol}`}
                    className={`rounded-2xl border border-slate-100 p-4 dark:border-slate-800 ${roleFilter === 'paper' ? 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-950/50' : ''} ${selectedTradeId === item.trade_id ? 'bg-slate-50 dark:bg-slate-950/50' : ''}`}
                    onClick={roleFilter === 'paper' ? () => handleFillOrderFromTrade(item) : undefined}
                    title={roleFilter === 'paper' ? '点击切换到该股票' : undefined}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium text-slate-900 dark:text-white">{displaySecurityName(item.name, item.symbol)}</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">{item.symbol} · 成交号 {item.trade_id || '--'}</div>
                      </div>
                      <span className="text-xs text-slate-500 dark:text-slate-400">{formatDateTime(item.trade_time)}</span>
                    </div>
                    <div className="mt-3 grid gap-2 text-sm md:grid-cols-2">
                      <div>方向：{item.side}</div>
                      <div>价格：{item.price != null ? item.price.toFixed(3) : '--'}</div>
                      <div>数量：{item.quantity ?? '--'}</div>
                      <div>金额：{formatMoney(item.amount)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}

export default function VirtualWarehouse() {
  return <WarehousePage />
}
