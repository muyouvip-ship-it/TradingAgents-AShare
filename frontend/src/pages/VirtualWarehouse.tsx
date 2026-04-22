import { useCallback, useEffect, useMemo, useState } from 'react'
import { Database, Landmark, RefreshCw, Send, Wifi, WifiOff, XCircle } from 'lucide-react'

import { api } from '@/services/api'
import type { PaperAccount, StrategyDefinition, VirtualWarehouseDiagnosticsResponse, VirtualWarehouseOverviewResponse, VirtualWarehousePosition, VirtualWarehouseOrder, VirtualWarehouseTrade } from '@/types'

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
  if (value > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (value < 0) return 'text-rose-600 dark:text-rose-400'
  return 'text-slate-500'
}

function displaySecurityName(name?: string | null, symbol?: string | null) {
  const trimmedName = String(name || '').trim()
  const trimmedSymbol = String(symbol || '').trim().toUpperCase()
  if (!trimmedName) return '名称待更新'
  if (trimmedName.toUpperCase() === trimmedSymbol) return '名称待更新'
  return trimmedName
}

function MetricCard({ label, value, subValue }: { label: string; value: string; subValue?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs tracking-[0.16em] text-slate-400">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{value}</p>
      {subValue ? <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{subValue}</p> : null}
    </div>
  )
}

interface WarehousePageProps {
  roleFilter?: 'paper' | 'live'
  pageTitle?: string
  pageDescription?: string
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
  const [strategies, setStrategies] = useState<StrategyDefinition[]>([])
  const [paperAccounts, setPaperAccounts] = useState<PaperAccount[]>([])
  const [selectedStrategyId, setSelectedStrategyId] = useState('')
  const [selectedPaperAccountId, setSelectedPaperAccountId] = useState('')
  const [paperRunning, setPaperRunning] = useState(false)
  const [submittingOrder, setSubmittingOrder] = useState(false)
  const [cancellingOrderId, setCancellingOrderId] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [orderForm, setOrderForm] = useState({
    symbol: '',
    side: 'buy',
    quantity: 100,
    priceType: 'limit',
    price: '',
    strategyName: 'TradingAgents',
    remark: '',
  })
  const account = payload?.account
  const connection = payload?.connection

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

  const loadMeta = useCallback(async () => {
    try {
      if (roleFilter !== 'paper') {
        setStrategies([])
        setPaperAccounts([])
        return
      }
      const [strategyResponse, paperResponse] = await Promise.all([
        api.getStrategyPlatformList({ status: 'active' }),
        api.listPaperAccounts(),
      ])
      setStrategies(strategyResponse.strategies || [])
      setPaperAccounts(paperResponse.items || [])
      if (!selectedStrategyId && strategyResponse.strategies?.[0]?.id) setSelectedStrategyId(strategyResponse.strategies[0].id)
      if (!selectedPaperAccountId && paperResponse.items?.[0]?.id) setSelectedPaperAccountId(paperResponse.items[0].id)
    } catch (err) {
      console.error(`加载${pageTitle}扩展数据失败`, err)
    }
  }, [pageTitle, roleFilter, selectedPaperAccountId, selectedStrategyId])

  useEffect(() => {
    void load(false, selectedAccountKey)
    void loadMeta()
  }, [load, loadMeta, selectedAccountKey])

  useEffect(() => {
    const intervalSeconds = payload?.refresh_interval_seconds || 10
    const timer = window.setInterval(() => { void load(true, selectedAccountKey) }, intervalSeconds * 1000)
    return () => window.clearInterval(timer)
  }, [load, payload?.refresh_interval_seconds, selectedAccountKey])

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

  const handleRunPaperStrategy = useCallback(async () => {
    if (!selectedPaperAccountId || !selectedStrategyId) return
    setPaperRunning(true)
    try {
      await api.runStrategyOnPaperAccount(selectedPaperAccountId, selectedStrategyId)
      await loadMeta()
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '纸交易执行失败')
    } finally {
      setPaperRunning(false)
    }
  }, [loadMeta, selectedPaperAccountId, selectedStrategyId])

  const handleCreatePaperAccount = useCallback(async () => {
    try {
      const key = payload?.active_account_key || selectedAccountKey || 'paper_sim'
      const created = await api.createPaperAccount({
        id: `paper-${key}`,
        name: `${connection?.account_name || '虚拟仓'}纸交易账户`,
        initial_capital: account?.total_asset || 1_000_000,
      })
      await loadMeta()
      setSelectedPaperAccountId(created.id)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建纸交易账户失败')
    }
  }, [account?.total_asset, connection?.account_name, loadMeta, payload?.active_account_key, selectedAccountKey])

  const handleSubmitOrder = useCallback(async () => {
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
      setPayload(response.overview)
      setSelectedAccountKey(response.overview.active_account_key || selectedAccountKey)
      setActionMessage(`委托已提交，订单号 ${response.order_result.order_id || '--'}`)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'QMT 委托提交失败')
    } finally {
      setSubmittingOrder(false)
    }
  }, [orderForm, payload?.active_account_key, selectedAccountKey])

  const handleCancelOrder = useCallback(async (orderId: string) => {
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
  }, [payload?.active_account_key, selectedAccountKey])

  const positions = payload?.positions || []
  const orders = payload?.orders || []
  const trades = payload?.trades || []
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
        <MetricCard label="总盈亏" value={formatMoney(account?.total_pnl)} subValue={formatPercent(account?.total_pnl_pct)} />
        <MetricCard label="当日盈亏" value={formatMoney(account?.today_pnl)} subValue={lastQuoteTime ? `最近行情 ${lastQuoteTime}` : '等待行情刷新'} />
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
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">策略纸交易入口</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">把已激活策略快速下发到纸交易账户，联动模拟仓调试执行链路。</p>
          <div className="mt-4 space-y-3">
            <div>
              <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">纸交易账户</label>
              <select value={selectedPaperAccountId} onChange={e => setSelectedPaperAccountId(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950">
                <option value="">请选择</option>
                {paperAccounts.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">激活策略</label>
              <select value={selectedStrategyId} onChange={e => setSelectedStrategyId(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950">
                <option value="">请选择</option>
                {strategies.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </div>
            <div className="flex flex-wrap gap-3">
              <button type="button" onClick={() => void handleRunPaperStrategy()} disabled={!selectedPaperAccountId || !selectedStrategyId || paperRunning} className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900">
                {paperRunning ? '执行中...' : '运行到纸交易'}
              </button>
              <button type="button" onClick={() => void handleCreatePaperAccount()} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 dark:border-slate-700 dark:text-slate-200">
                新建纸交易账户
              </button>
            </div>
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
            <div>当前页面支持：实时查询、下单、撤单、委托/成交查看</div>
          </div>
        </div>
        )}
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">QMT 交易控制台</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">直接向当前 QMT 账户提交买卖委托，支持提交后立即回显到最近委托。</p>
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
                <div>总盈亏：{formatMoney(item.summary.total_pnl)}</div>
                <div>当日盈亏：{formatMoney(item.summary.today_pnl)}</div>
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
            <p className="text-sm text-slate-500 dark:text-slate-400">展示 QMT 虚拟仓持仓快照，持股天数按首次同步时间持续跟踪。</p>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-300">
            共 {positions.length} 只
          </span>
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
                  <tr key={item.symbol} className="border-t border-slate-100 dark:border-slate-800">
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
              <p className="text-sm text-slate-500 dark:text-slate-400">展示桥接返回的最近委托状态，便于验证链路已打通。</p>
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
                  <div key={`${item.order_id}-${item.symbol}`} className="rounded-2xl border border-slate-100 p-4 dark:border-slate-800">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium text-slate-900 dark:text-white">{displaySecurityName(item.name, item.symbol)}</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">{item.symbol} · 委托号 {item.order_id || '--'}</div>
                      </div>
                      <div className="flex items-center gap-2">
                        {item.can_cancel ? (
                          <button
                            type="button"
                            onClick={() => void handleCancelOrder(item.order_id)}
                            disabled={cancellingOrderId === item.order_id}
                            className="inline-flex items-center gap-1 rounded-lg border border-rose-200 px-2.5 py-1 text-xs text-rose-600 disabled:opacity-50 dark:border-rose-900 dark:text-rose-300"
                          >
                            <XCircle className="h-3.5 w-3.5" />
                            {cancellingOrderId === item.order_id ? '撤单中...' : '撤单'}
                          </button>
                        ) : null}
                        <span className="text-xs text-slate-500 dark:text-slate-400">{item.order_time || '--'}</span>
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
              <p className="text-sm text-slate-500 dark:text-slate-400">展示桥接返回的最近成交记录，验证资产 / 持仓 / 成交链路。</p>
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
                  <div key={`${item.trade_id}-${item.symbol}`} className="rounded-2xl border border-slate-100 p-4 dark:border-slate-800">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium text-slate-900 dark:text-white">{displaySecurityName(item.name, item.symbol)}</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">{item.symbol} · 成交号 {item.trade_id || '--'}</div>
                      </div>
                      <span className="text-xs text-slate-500 dark:text-slate-400">{item.trade_time || '--'}</span>
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
