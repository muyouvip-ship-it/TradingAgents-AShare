import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, Clock3, FileText, RefreshCw, ShieldAlert, TerminalSquare } from 'lucide-react'

import VirtualList from '@/components/VirtualList'
import { api } from '@/services/api'
import type { RuntimeLogSource, RuntimeLogsResponse } from '@/types'

const levelOptions: Array<{ value: 'all' | 'error' | 'warning' | 'info'; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'error', label: '错误' },
  { value: 'warning', label: '警告' },
  { value: 'info', label: '信息' },
]

const lineOptions = [100, 300, 500, 1000]

export default function DebugLogs() {
  const [sources, setSources] = useState<RuntimeLogSource[]>([])
  const [selectedSource, setSelectedSource] = useState('backend_runtime')
  const [selectedLevel, setSelectedLevel] = useState<'all' | 'error' | 'warning' | 'info'>('all')
  const [selectedLines, setSelectedLines] = useState(300)
  const [liveMode, setLiveMode] = useState(true)
  const [streamStatus, setStreamStatus] = useState('未连接')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [payload, setPayload] = useState<RuntimeLogsResponse | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const currentSource = useMemo(
    () => sources.find(item => item.id === selectedSource) ?? sources[0] ?? null,
    [selectedSource, sources],
  )
  const logViewportHeight = typeof window !== 'undefined'
    ? Math.max(360, Math.min(Math.floor(window.innerHeight * 0.72), 780))
    : 640

  const loadSources = async () => {
    try {
      const response = await api.getRuntimeLogSources()
      setSources(response.sources)
      if (!response.sources.find(item => item.id === selectedSource) && response.sources[0]) {
        setSelectedSource(response.sources[0].id)
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '获取日志来源失败')
    }
  }

  const loadLogs = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await api.getRuntimeLogs({
        source: selectedSource,
        lines: selectedLines,
        level: selectedLevel,
      })
      setPayload(response)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '读取日志失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSources()
  }, [])

  useEffect(() => {
    if (!sources.length) return
    if (liveMode) {
      setPayload(null)
      return
    }
    void loadLogs()
  }, [liveMode, selectedSource, selectedLines, selectedLevel, sources.length])

  useEffect(() => {
    if (!liveMode || !sources.length) {
      abortRef.current?.abort()
      abortRef.current = null
      setStreamStatus('未连接')
      return
    }

    const controller = new AbortController()
    abortRef.current?.abort()
    abortRef.current = controller
    setStreamStatus('连接中...')
    setError(null)
    setPayload(null)

    const startStream = async () => {
      try {
        const response = await api.streamRuntimeLogs({
          source: selectedSource,
          lines: selectedLines,
          level: selectedLevel,
          signal: controller.signal,
        })
        if (!response.body) throw new Error('实时日志流不可用')

        setStreamStatus('实时追踪中')
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const blocks = buffer.split('\n\n')
          buffer = blocks.pop() || ''

          for (const block of blocks) {
            const event = parseSseBlock(block)
            if (!event) continue
            if (event.event === 'ready') {
              setStreamStatus('实时追踪中')
            } else if (event.event === 'status') {
              const message = typeof event.data.message === 'string' ? event.data.message : '等待日志更新'
              setStreamStatus(message)
            } else if (event.event === 'log' && typeof event.data.line === 'string') {
              appendRuntimeLogLine(event.data.line)
            }
          }
        }

        if (!controller.signal.aborted) setStreamStatus('连接已断开')
      } catch (streamError) {
        if (controller.signal.aborted) return
        setStreamStatus('连接失败')
        setError(streamError instanceof Error ? streamError.message : '实时日志连接失败')
      }
    }

    void startStream()
    return () => controller.abort()
  }, [liveMode, selectedSource, selectedLevel, selectedLines, sources.length])

  const appendRuntimeLogLine = (line: string) => {
    setPayload(current => {
      const sourceInfo = current?.source ?? currentSource ?? {
        id: selectedSource,
        label: selectedSource,
        path: selectedSource,
        exists: true,
        size_bytes: 0,
        modified_at: null,
      }
      const nextLines = [...(current?.lines ?? []), line].slice(-selectedLines)
      return {
        source: sourceInfo,
        lines: nextLines,
        line_count: nextLines.length,
        max_lines: selectedLines,
        truncated: nextLines.length >= selectedLines,
        read_at: new Date().toISOString(),
      }
    })
  }

  return (
    <div className="space-y-4">
      <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">
              <TerminalSquare className="h-4 w-4" />
              运行日志调试
            </div>
            <h1 className="mt-3 text-2xl font-bold text-slate-900 dark:text-slate-100">程序运行日志</h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              查看前后端运行日志，快速定位接口报错、启动异常和策略执行问题。
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => void loadLogs()}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              刷新日志
            </button>
            <button
              onClick={() => setLiveMode(current => !current)}
              className={`rounded-xl px-4 py-2 text-sm font-semibold ${
                liveMode
                  ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'
                  : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
              }`}
            >
              {liveMode ? '实时追踪中' : '实时追踪已关闭'}
            </button>
          </div>
        </div>
        <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          <span className={`h-2 w-2 rounded-full ${liveMode && streamStatus === '实时追踪中' ? 'bg-emerald-500' : liveMode ? 'bg-amber-500' : 'bg-slate-400'}`} />
          实时状态：{streamStatus}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">日志来源</h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">左侧选择要查看的程序日志文件。</p>
          </div>

          <div className="space-y-3">
            {sources.map(source => {
              const active = source.id === currentSource?.id
              return (
                <button
                  key={source.id}
                  type="button"
                  onClick={() => setSelectedSource(source.id)}
                  className={`w-full rounded-2xl border p-4 text-left transition ${
                    active
                      ? 'border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-500/10'
                      : 'border-slate-200 bg-slate-50 hover:bg-white dark:border-slate-700 dark:bg-slate-950 dark:hover:bg-slate-900'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">{source.label}</div>
                    <span className={`rounded-full px-2 py-1 text-[11px] ${source.exists ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-rose-100 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300'}`}>
                      {source.exists ? '可读取' : '不存在'}
                    </span>
                  </div>
                  <div className="mt-2 font-mono text-xs text-slate-500 dark:text-slate-400">{source.path}</div>
                  <div className="mt-3 flex items-center gap-3 text-xs text-slate-400 dark:text-slate-500">
                    <span>大小 {formatBytes(source.size_bytes)}</span>
                    <span>{source.modified_at ? formatDateTime(source.modified_at) : '暂无修改时间'}</span>
                  </div>
                </button>
              )
            })}
          </div>

          <div className="space-y-3 rounded-2xl bg-slate-50 p-4 dark:bg-slate-950">
            <label className="block">
              <div className="text-xs text-slate-500 dark:text-slate-400">日志级别</div>
              <select
                value={selectedLevel}
                onChange={event => setSelectedLevel(event.target.value as 'all' | 'error' | 'warning' | 'info')}
                className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              >
                {levelOptions.map(option => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>

            <label className="block">
              <div className="text-xs text-slate-500 dark:text-slate-400">读取行数</div>
              <select
                value={selectedLines}
                onChange={event => setSelectedLines(Number(event.target.value))}
                className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              >
                {lineOptions.map(option => (
                  <option key={option} value={option}>最近 {option} 行</option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="flex flex-col gap-3 border-b border-slate-100 pb-4 dark:border-slate-800 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{payload?.source.label ?? currentSource?.label ?? '日志内容'}</h2>
              <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                <span className="inline-flex items-center gap-1"><FileText className="h-3.5 w-3.5" />{payload?.source.path ?? currentSource?.path ?? '--'}</span>
                <span className="inline-flex items-center gap-1"><Clock3 className="h-3.5 w-3.5" />{payload?.read_at ? formatDateTime(payload.read_at) : '未读取'}</span>
                <span>显示 {payload?.line_count ?? 0} 行</span>
                <span>{liveMode ? '实时追加新增日志' : '当前为手动刷新模式'}</span>
              </div>
            </div>

            {payload?.truncated && (
              <div className="inline-flex items-center gap-2 rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                <ShieldAlert className="h-4 w-4" />
                已截断为最近 {payload.max_lines} 行
              </div>
            )}
          </div>

          {error && (
            <div className="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:bg-rose-500/10 dark:text-rose-200">
              <div className="inline-flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" />读取失败</div>
              <div className="mt-1">{error}</div>
            </div>
          )}

          <div className="mt-4 rounded-2xl bg-slate-950 p-4">
            {payload?.lines?.length ? (
              <VirtualList
                items={payload.lines}
                height={logViewportHeight}
                estimateSize={24}
                overscan={12}
                className="font-mono text-xs leading-6 text-slate-100"
                itemKey={(_, index) => index}
                renderItem={(line, index) => (
                  <div className="whitespace-pre break-all">
                    <span className="mr-3 inline-block w-12 select-none text-right text-slate-500">{index + 1}</span>
                    <span>{line}</span>
                  </div>
                )}
              />
            ) : (
              <div className="py-6 font-mono text-xs leading-6 text-slate-100">
                {currentSource?.exists
                  ? '当前日志暂无内容。'
                  : '当前日志文件不存在，请先启动对应程序或检查日志输出配置。'}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function parseSseBlock(block: string): { event: string; data: Record<string, unknown> } | null {
  const lines = block.split('\n')
  let event = 'message'
  const dataLines: string[] = []
  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }
  if (!dataLines.length) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) as Record<string, unknown> }
  } catch {
    return null
  }
}
