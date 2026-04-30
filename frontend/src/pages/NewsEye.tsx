import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, Loader2, RefreshCw, Search, Zap } from 'lucide-react'

import { api } from '@/services/api'
import type { NewsEyeItem } from '@/types'

function formatDateTime(value?: string | null) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function sentimentLabel(sentiment: string) {
  if (sentiment === 'positive') return '利好'
  if (sentiment === 'negative') return '利空'
  return '中性'
}

export default function NewsEye() {
  const [items, setItems] = useState<NewsEyeItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [backgroundMeta, setBackgroundMeta] = useState<{
    interval_seconds?: number
    status?: string
    active_sources?: string[]
    tracked_symbols?: string[]
    last_success_at?: string | null
    last_error?: string | null
  } | null>(null)
  const [filters, setFilters] = useState({
    source: '',
    sentiment: 'all',
    symbol: '',
    sector: '',
  })

  const loadItems = useCallback(async () => {
    try {
      const response = await api.getNewsEyeItems({
        limit: 80,
        source: filters.source || undefined,
        sentiment: filters.sentiment === 'all' ? undefined : filters.sentiment,
        symbol: filters.symbol || undefined,
        sector: filters.sector || undefined,
      })
      setItems(response.items || [])
      setUpdatedAt(response.updated_at)
      setBackgroundMeta(response.background || null)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载资讯失败')
    } finally {
      setLoading(false)
    }
  }, [filters.sector, filters.sentiment, filters.source, filters.symbol])

  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    try {
      await api.refreshNewsEye(80)
      await loadItems()
    } catch (err) {
      setError(err instanceof Error ? err.message : '刷新资讯失败')
    } finally {
      setRefreshing(false)
    }
  }, [loadItems])

  useEffect(() => {
    setLoading(true)
    void loadItems()
  }, [loadItems])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadItems()
    }, 20000)
    return () => window.clearInterval(timer)
  }, [loadItems])

  const sourceOptions = useMemo(() => {
    return Array.from(new Set([
      ...items.map(item => item.source).filter(Boolean),
      ...(backgroundMeta?.active_sources || []).map(source => source.split(':')[0]).filter(Boolean),
    ]))
  }, [backgroundMeta?.active_sources, items])

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">资讯之眼</h1>
          <p className="mt-1 text-slate-500 dark:text-slate-400">
            后台常驻采集多源市场快讯，这里展示的是服务端缓存与情绪映射结果。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          <span>最近更新：{formatDateTime(updatedAt)}</span>
          {backgroundMeta?.interval_seconds ? <span>后台轮询：{backgroundMeta.interval_seconds}s</span> : null}
          {backgroundMeta?.active_sources?.length ? <span>活跃源：{backgroundMeta.active_sources.length}</span> : null}
          <button
            type="button"
            onClick={() => void handleRefresh()}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            立即刷新
          </button>
        </div>
      </div>

      <div className="card space-y-4">
        {backgroundMeta && (
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              状态：{backgroundMeta.status || 'unknown'}
            </span>
            {backgroundMeta.last_success_at ? (
              <span className="rounded-full bg-emerald-50 px-3 py-1 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
                最近成功：{formatDateTime(backgroundMeta.last_success_at)}
              </span>
            ) : null}
            {(backgroundMeta.active_sources || []).slice(0, 8).map(source => (
              <span key={source} className="rounded-full bg-blue-50 px-3 py-1 text-blue-700 dark:bg-blue-950/30 dark:text-blue-300">
                {source}
              </span>
            ))}
            {(backgroundMeta.tracked_symbols || []).slice(0, 6).map(symbol => (
              <span key={symbol} className="rounded-full bg-amber-50 px-3 py-1 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
                关注 {symbol}
              </span>
            ))}
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div>
            <div className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">来源</div>
            <select
              value={filters.source}
              onChange={(e) => setFilters(prev => ({ ...prev, source: e.target.value }))}
              className="input w-full"
            >
              <option value="">全部来源</option>
              {sourceOptions.map(source => (
                <option key={source} value={source}>{source}</option>
              ))}
            </select>
          </div>
          <div>
            <div className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">情绪</div>
            <select
              value={filters.sentiment}
              onChange={(e) => setFilters(prev => ({ ...prev, sentiment: e.target.value }))}
              className="input w-full"
            >
              <option value="all">全部</option>
              <option value="positive">利好</option>
              <option value="negative">利空</option>
              <option value="neutral">中性</option>
            </select>
          </div>
          <div>
            <div className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">关联股票</div>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={filters.symbol}
                onChange={(e) => setFilters(prev => ({ ...prev, symbol: e.target.value.trim().toUpperCase() }))}
                placeholder="如 300750.SZ"
                className="input w-full pl-10"
              />
            </div>
          </div>
          <div>
            <div className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">板块关键词</div>
            <input
              value={filters.sector}
              onChange={(e) => setFilters(prev => ({ ...prev, sector: e.target.value }))}
              placeholder="如 算力"
              className="input w-full"
            />
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4" />
            {error}
          </div>
          {backgroundMeta?.last_error ? (
            <div className="mt-2 text-xs opacity-80">后台最近异常：{backgroundMeta.last_error}</div>
          ) : null}
        </div>
      )}

      <div className="space-y-4">
        {loading ? (
          <div className="card flex min-h-[260px] items-center justify-center text-slate-500 dark:text-slate-400">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            正在加载市场资讯...
          </div>
        ) : items.length === 0 ? (
          <div className="card min-h-[220px] text-center text-slate-500 dark:text-slate-400">
            <div className="flex h-full min-h-[220px] flex-col items-center justify-center gap-3">
              <Zap className="h-10 w-10 opacity-40" />
              <div>当前没有可展示的市场消息</div>
              <button
                type="button"
                onClick={() => void handleRefresh()}
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                现在拉取一次
              </button>
            </div>
          </div>
        ) : (
          items.map((item) => {
            const isPositive = item.sentiment === 'positive'
            const isNegative = item.sentiment === 'negative'
            return (
              <div key={item.id} className="card space-y-3">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="flex-1">
                    <div className="text-base font-semibold leading-7 text-slate-900 dark:text-slate-100">
                      {item.content}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-500 dark:text-slate-400">
                      <span>{formatDateTime(item.published_at)}</span>
                      <span>来源：{item.source}</span>
                      <span>入库：{formatDateTime(item.fetched_at)}</span>
                    </div>
                  </div>
                  <div className={`rounded-full px-3 py-1 text-xs font-semibold ${
                    isPositive
                      ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
                      : isNegative
                        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                        : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
                  }`}>
                    {sentimentLabel(item.sentiment)}
                  </div>
                </div>

                <div className="grid gap-3 xl:grid-cols-2">
                  <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900/50">
                    <div className="text-xs font-medium text-slate-500 dark:text-slate-400">利好 / 利空板块</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {item.positive_sectors.map(sector => (
                        <span key={`p-${sector}`} className="rounded-full bg-red-100 px-2.5 py-1 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-300">
                          利好 {sector}
                        </span>
                      ))}
                      {item.negative_sectors.map(sector => (
                        <span key={`n-${sector}`} className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                          利空 {sector}
                        </span>
                      ))}
                      {item.positive_sectors.length === 0 && item.negative_sectors.length === 0 && (
                        <span className="text-xs text-slate-400 dark:text-slate-500">未识别到明确板块</span>
                      )}
                    </div>
                  </div>

                  <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900/50">
                    <div className="text-xs font-medium text-slate-500 dark:text-slate-400">利好 / 利空个股</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {item.positive_symbols.map(symbol => (
                        <span key={`ps-${symbol.symbol}`} className="rounded-full bg-red-100 px-2.5 py-1 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-300">
                          利好 {symbol.name || symbol.symbol}
                        </span>
                      ))}
                      {item.negative_symbols.map(symbol => (
                        <span key={`ns-${symbol.symbol}`} className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                          利空 {symbol.name || symbol.symbol}
                        </span>
                      ))}
                      {item.positive_symbols.length === 0 && item.negative_symbols.length === 0 && (
                        <span className="text-xs text-slate-400 dark:text-slate-500">未识别到明确个股</span>
                      )}
                    </div>
                  </div>
                </div>

                {item.url && (
                  <div>
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs font-medium text-blue-600 hover:text-blue-500 dark:text-blue-300 dark:hover:text-blue-200"
                    >
                      查看原文
                    </a>
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
