import { useEffect, useMemo, useRef, useState } from 'react'
import {
    BusinessDay,
    CandlestickData,
    CandlestickSeries,
    ColorType,
    IChartApi,
    ISeriesMarkersPluginApi,
    ISeriesApi,
    LineData,
    LineSeries,
    MouseEventParams,
    SeriesMarker,
    Time,
    createSeriesMarkers,
    createChart,
} from 'lightweight-charts'
import { Activity, CandlestickChart, Layers3 } from 'lucide-react'
import { api } from '@/services/api'
import type { ChanlunOverlayResponse, KlineCandle } from '@/types'
import { useAnalysisStore } from '@/stores/analysisStore'

interface KlinePanelProps {
    symbol: string
    onSymbolChange?: (symbol: string) => void
    showChanlunOverlay?: boolean
    focusDate?: string | null
    markers?: Array<{
        date: string
        side: 'buy' | 'sell'
        timestamp?: string
        quantity?: number
        price?: number
        reason?: string
        text?: string
        color?: string
    }>
}

function normalizeDateKey(value?: string | null): string {
    return value ? value.slice(0, 10) : ''
}

function shiftDateText(dateText: string, offsetDays: number): string {
    const date = new Date(`${dateText}T00:00:00`)
    if (Number.isNaN(date.getTime())) return dateText
    date.setDate(date.getDate() + offsetDays)
    return toDateText(date)
}

function toDateText(date: Date): string {
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
}

function toBusinessDay(value: string): BusinessDay | null {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
    if (!m) return null
    const year = Number(m[1])
    const month = Number(m[2])
    const day = Number(m[3])
    if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null
    return { year, month, day }
}

const SYMBOL_NAME_MAP: Record<string, string> = {
    '000001.SH': '上证指数',
    '399001.SZ': '深证成指',
    '399006.SZ': '创业板指',
    '000300.SH': '沪深300',
    '000905.SH': '中证500',
    '000852.SH': '中证1000',
    '300750.SZ': '宁德时代',
    '600406.SH': '国电南瑞',
    '510300.SH': '沪深300ETF',
}

function getDisplayName(symbol: string): string {
    const s = symbol.toUpperCase()
    return SYMBOL_NAME_MAP[s] ? `${SYMBOL_NAME_MAP[s]}（${s}）` : s
}

function formatNumber(value?: number | null, digits = 2): string {
    if (value == null || !Number.isFinite(value)) return '--'
    return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    }).format(value)
}

function formatVolume(value?: number | null): string {
    if (value == null || !Number.isFinite(value)) return '--'
    if (Math.abs(value) >= 1e8) return `${formatNumber(value / 1e8, 2)}亿`
    if (Math.abs(value) >= 1e4) return `${formatNumber(value / 1e4, 2)}万`
    return formatNumber(value, 0)
}

const INDEX_PRESETS = [
    { symbol: '000001.SH', label: '上证指数' },
    { symbol: '399001.SZ', label: '深证成指' },
    { symbol: '399006.SZ', label: '创业板指' },
    { symbol: '000688.SH', label: '科创50' },
    { symbol: '899050.BJ', label: '北证50' },
] as const

export default function KlinePanel({ symbol, onSymbolChange, showChanlunOverlay = true, focusDate, markers = [] }: KlinePanelProps) {
    const currentAnalysisSymbol = useAnalysisStore((state) => state.currentSymbol)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const chartRef = useRef<IChartApi | null>(null)
    const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
    const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [isDark, setIsDark] = useState(document.documentElement.classList.contains('dark'))
    const [candles, setCandles] = useState<KlineCandle[]>([])
    const [activeCandle, setActiveCandle] = useState<KlineCandle | null>(null)
    const [overlayLoading, setOverlayLoading] = useState(false)
    const [overlayMessage, setOverlayMessage] = useState<string | null>(null)
    const [overlayData, setOverlayData] = useState<ChanlunOverlayResponse | null>(null)
    const [overlayToggles, setOverlayToggles] = useState({
        fractals: true,
        bi: true,
        segments: true,
        zhongshu: true,
        buySell: true,
    })
    const candlesRef = useRef<KlineCandle[]>([])
    const overlaySeriesRef = useRef<Array<ISeriesApi<'Line'>>>([])

    const range = useMemo(() => {
        const markerDates = markers
            .map(item => normalizeDateKey(item.timestamp || item.date))
            .filter(Boolean)
            .sort()
        const focusDateKey = normalizeDateKey(focusDate)
        if (focusDateKey) markerDates.push(focusDateKey)
        markerDates.sort()

        if (markerDates.length > 0) {
            const start = shiftDateText(markerDates[0], -30)
            const end = shiftDateText(markerDates[markerDates.length - 1], 30)
            return { start, end }
        }

        const end = new Date()
        const start = new Date(end.getTime() - 180 * 24 * 60 * 60 * 1000)
        return {
            start: toDateText(start),
            end: toDateText(end),
        }
    }, [focusDate, markers])

    // Listen for theme changes
    useEffect(() => {
        const observer = new MutationObserver(() => {
            const dark = document.documentElement.classList.contains('dark')
            setIsDark(dark)
        })
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
        return () => observer.disconnect()
    }, [])

    useEffect(() => {
        if (!containerRef.current) return

        const textColor = isDark ? '#94a3b8' : '#475569'
        const gridColor = isDark ? 'rgba(51, 65, 85, 0.6)' : 'rgba(203, 213, 225, 0.6)'
        const bgColor = isDark ? 'transparent' : 'transparent'

        let chart: IChartApi
        let series: ISeriesApi<'Candlestick'>
        let seriesMarkers: ISeriesMarkersPluginApi<Time>
        try {
            chart = createChart(containerRef.current, {
                layout: {
                    background: { type: ColorType.Solid, color: bgColor },
                    textColor: textColor,
                    attributionLogo: false,
                },
                localization: {
                    locale: 'zh-CN',
                    dateFormat: 'yyyy-MM-dd',
                },
                width: containerRef.current.clientWidth,
                height: containerRef.current.clientHeight,
                grid: {
                    vertLines: { color: gridColor },
                    horzLines: { color: gridColor },
                },
                rightPriceScale: {
                    borderColor: isDark ? '#334155' : '#cbd5e1',
                },
                timeScale: {
                    borderColor: isDark ? '#334155' : '#cbd5e1',
                    timeVisible: true,
                    rightOffset: 6,
                    tickMarkFormatter: (time: BusinessDay | string) => {
                        if (typeof time !== 'object') return String(time)
                        const y = String(time.year)
                        const m = String(time.month).padStart(2, '0')
                        const d = String(time.day).padStart(2, '0')
                        return `${y}/${m}/${d}`
                    },
                },
                crosshair: {
                    vertLine: { color: isDark ? 'rgba(59, 130, 246, 0.35)' : 'rgba(59, 130, 246, 0.25)' },
                    horzLine: { color: isDark ? 'rgba(59, 130, 246, 0.35)' : 'rgba(59, 130, 246, 0.25)' },
                },
            })

            series = chart.addSeries(CandlestickSeries, {
                upColor: '#ef4444',
                downColor: '#22c55e',
                wickUpColor: '#ef4444',
                wickDownColor: '#22c55e',
                borderVisible: false,
            })
            seriesMarkers = createSeriesMarkers(series, [])
        } catch (chartError) {
            setError(chartError instanceof Error ? `K线图初始化失败：${chartError.message}` : 'K线图初始化失败')
            return
        }

        chartRef.current = chart
        seriesRef.current = series
        markersRef.current = seriesMarkers
        if (candlesRef.current.length) {
            const existingData: CandlestickData[] = candlesRef.current.flatMap((c) => {
                const time = toBusinessDay((c.date || '').slice(0, 10))
                const open = Number(c.open)
                const high = Number(c.high)
                const low = Number(c.low)
                const close = Number(c.close)
                if (!time) return []
                if (![open, high, low, close].every(Number.isFinite)) return []
                return [{ time, open, high, low, close }]
            })
            series.setData(existingData)
            chart.timeScale().fitContent()
        }

        const handleCrosshairMove = (param: MouseEventParams) => {
            if (!param.time || !seriesRef.current) {
                setActiveCandle(candlesRef.current.length ? candlesRef.current[candlesRef.current.length - 1] : null)
                return
            }
            const pointData = param.seriesData.get(seriesRef.current) as CandlestickData | undefined
            if (!pointData) return
            const time = typeof pointData.time === 'object'
                ? `${pointData.time.year}-${String(pointData.time.month).padStart(2, '0')}-${String(pointData.time.day).padStart(2, '0')}`
                : String(pointData.time)
            const matched = candlesRef.current.find(c => c.date === time)
            if (matched) setActiveCandle(matched)
        }
        chart.subscribeCrosshairMove(handleCrosshairMove)

        const handleDblClick = () => {
            chartRef.current?.timeScale().fitContent()
        }
        containerRef.current.addEventListener('dblclick', handleDblClick)

        const onResize = () => {
            if (!containerRef.current || !chartRef.current) return
            chartRef.current.applyOptions({
                width: containerRef.current.clientWidth,
                height: containerRef.current.clientHeight,
            })
        }

        window.addEventListener('resize', onResize)
        return () => {
            window.removeEventListener('resize', onResize)
            containerRef.current?.removeEventListener('dblclick', handleDblClick)
            chart.unsubscribeCrosshairMove(handleCrosshairMove)
            chartRef.current?.remove()
            chartRef.current = null
            seriesRef.current = null
            markersRef.current = null
            overlaySeriesRef.current = []
        }
    }, [isDark])

    useEffect(() => {
        let cancelled = false

        const load = async () => {
            if (!seriesRef.current) return
            setLoading(true)
            setError(null)
            try {
                const resp = await api.getKline(symbol, range.start, range.end)
                const data: CandlestickData[] = resp.candles.flatMap((c) => {
                    const time = toBusinessDay((c.date || '').slice(0, 10))
                    const open = Number(c.open)
                    const high = Number(c.high)
                    const low = Number(c.low)
                    const close = Number(c.close)
                    if (!time) return []
                    if (![open, high, low, close].every(Number.isFinite)) return []
                    return [{ time, open, high, low, close }]
                })

                if (cancelled) return
                setCandles(resp.candles)
                candlesRef.current = resp.candles
                setActiveCandle(resp.candles.length ? resp.candles[resp.candles.length - 1] : null)
                seriesRef.current?.setData(data)
                chartRef.current?.timeScale().fitContent()
                if (!data.length) {
                    setError('暂无可用K线数据')
                }
            } catch (e) {
                if (cancelled) return
                setError(e instanceof Error ? e.message : '加载K线失败')
                setCandles([])
                candlesRef.current = []
                setActiveCandle(null)
                seriesRef.current?.setData([])
            } finally {
                if (!cancelled) setLoading(false)
            }
        }

        load()
        return () => {
            cancelled = true
        }
    }, [range.end, range.start, symbol])

    useEffect(() => {
        const targetDate = normalizeDateKey(focusDate)
        if (!targetDate || !chartRef.current || !candlesRef.current.length) return
        const targetIndex = candlesRef.current.findIndex(item => normalizeDateKey(item.date) === targetDate)
        if (targetIndex < 0) return
        const matched = candlesRef.current[targetIndex]
        if (matched) setActiveCandle(matched)
        const from = candlesRef.current[Math.max(0, targetIndex - 12)]
        const to = candlesRef.current[Math.min(candlesRef.current.length - 1, targetIndex + 12)]
        const fromTime = toBusinessDay(normalizeDateKey(from?.date))
        const toTime = toBusinessDay(normalizeDateKey(to?.date))
        if (fromTime && toTime) {
            chartRef.current.timeScale().setVisibleRange({ from: fromTime, to: toTime })
        }
    }, [candles, focusDate])

    useEffect(() => {
        if (!showChanlunOverlay) {
            setOverlayData(null)
            setOverlayMessage(null)
            setOverlayLoading(false)
            return
        }
        let cancelled = false
        const loadOverlay = async () => {
            setOverlayLoading(true)
            try {
                const response = await api.getChanlunOverlay(symbol, range.start, range.end)
                if (cancelled) return
                setOverlayData(response)
                setOverlayMessage(response.message || null)
            } catch (error) {
                if (cancelled) return
                setOverlayData(null)
                setOverlayMessage(error instanceof Error ? error.message : '缠论叠加加载失败')
            } finally {
                if (!cancelled) setOverlayLoading(false)
            }
        }
        void loadOverlay()
        return () => {
            cancelled = true
        }
    }, [range.end, range.start, showChanlunOverlay, symbol])

    useEffect(() => {
        if (!markersRef.current) return
        const tradeMarkers: SeriesMarker<Time>[] = markers.flatMap((marker) => {
            const time = toBusinessDay((marker.date || '').slice(0, 10))
            if (!time) return []
            return [{
                time,
                position: marker.side === 'buy' ? 'belowBar' : 'aboveBar',
                shape: marker.side === 'buy' ? 'arrowUp' : 'arrowDown',
                color: marker.color || (marker.side === 'buy' ? '#ef4444' : '#22c55e'),
                text: marker.text || (marker.side === 'buy' ? '买' : '卖'),
            }]
        })
        const overlayMarkers: SeriesMarker<Time>[] = []
        if (showChanlunOverlay && overlayToggles.fractals && overlayData) {
            overlayMarkers.push(...overlayData.fractals.flatMap((point) => {
                const time = toBusinessDay((point.date || '').slice(0, 10))
                if (!time) return []
                return [{
                    time,
                    position: point.type === 'top' ? ('aboveBar' as const) : ('belowBar' as const),
                    shape: 'circle' as const,
                    color: point.type === 'top' ? '#a855f7' : '#06b6d4',
                    text: point.type === 'top' ? '顶' : '底',
                    price: Number(point.price),
                }]
            }))
        }
        if (showChanlunOverlay && overlayToggles.buySell && overlayData) {
            overlayMarkers.push(...overlayData.buy_sell_points.flatMap((point) => {
                const time = toBusinessDay((point.date || '').slice(0, 10))
                if (!time) return []
                return [{
                    time,
                    position: point.side === 'buy' ? ('belowBar' as const) : ('aboveBar' as const),
                    shape: point.side === 'buy' ? ('arrowUp' as const) : ('arrowDown' as const),
                    color: point.side === 'buy' ? '#ef4444' : '#22c55e',
                    text: point.type.replace('_', ''),
                    price: Number(point.price),
                }]
            }))
        }
        markersRef.current.setMarkers([...tradeMarkers, ...overlayMarkers])
    }, [markers, overlayData, overlayToggles.buySell, overlayToggles.fractals, showChanlunOverlay])

    useEffect(() => {
        if (!chartRef.current) return
        overlaySeriesRef.current.forEach((series) => chartRef.current?.removeSeries(series))
        overlaySeriesRef.current = []
        if (!showChanlunOverlay || !overlayData) return

        const pushLineSeries = (data: LineData<Time>[], options: Record<string, unknown>) => {
            if (!chartRef.current || data.length < 2) return
            const lineSeries = chartRef.current.addSeries(LineSeries, {
                lastValueVisible: false,
                priceLineVisible: false,
                crosshairMarkerVisible: false,
                ...options,
            })
            lineSeries.setData(data)
            overlaySeriesRef.current.push(lineSeries)
        }

        const createLine = (startDate: string, endDate: string, startPrice: number, endPrice: number): LineData<Time>[] => {
            const startTime = toBusinessDay((startDate || '').slice(0, 10))
            const endTime = toBusinessDay((endDate || '').slice(0, 10))
            if (!startTime || !endTime) return []
            return [
                { time: startTime, value: Number(startPrice) },
                { time: endTime, value: Number(endPrice) },
            ]
        }

        if (overlayToggles.bi) {
            overlayData.bi.forEach((stroke) => {
                pushLineSeries(
                    createLine(stroke.start_date, stroke.end_date, stroke.start_price, stroke.end_price),
                    {
                        color: stroke.direction === 'up' ? '#f97316' : '#10b981',
                        lineWidth: 2,
                    },
                )
            })
        }

        if (overlayToggles.segments) {
            overlayData.segments.forEach((segment) => {
                pushLineSeries(
                    createLine(segment.start_date, segment.end_date, segment.start_price, segment.end_price),
                    {
                        color: '#3b82f6',
                        lineWidth: 3,
                    },
                )
            })
        }

        if (overlayToggles.zhongshu) {
            overlayData.zhongshu.forEach((center) => {
                pushLineSeries(
                    createLine(center.start_date, center.end_date, center.high, center.high),
                    {
                        color: '#eab308',
                        lineWidth: 2,
                        lineStyle: 2,
                    },
                )
                pushLineSeries(
                    createLine(center.start_date, center.end_date, center.low, center.low),
                    {
                        color: '#eab308',
                        lineWidth: 2,
                        lineStyle: 2,
                    },
                )
            })
        }
    }, [isDark, overlayData, overlayToggles.bi, overlayToggles.segments, overlayToggles.zhongshu, showChanlunOverlay])

    const panelCandle = activeCandle ?? (candles.length ? candles[candles.length - 1] : null)
    const panelChange = panelCandle?.change ?? (panelCandle ? panelCandle.close - panelCandle.open : null)
    const panelChangePercent = panelCandle?.change_percent ?? (
        panelCandle && panelCandle.open !== 0 ? (panelChange! / panelCandle.open) * 100 : null
    )
    const isUp = (panelChange ?? 0) >= 0
    const compactChangePercent = panelChangePercent == null ? '--' : `${panelChangePercent >= 0 ? '+' : ''}${formatNumber(panelChangePercent)}%`
    const showCurrentSymbolButton = !!currentAnalysisSymbol && currentAnalysisSymbol !== symbol
    const currentSymbolLabel = currentAnalysisSymbol ? getDisplayName(currentAnalysisSymbol).replace(/（.*?）/, '') : '当前标的'
    const activeMarkerDetails = useMemo(() => {
        const activeDate = normalizeDateKey(panelCandle?.date)
        if (!activeDate) return []
        return markers.filter(marker => normalizeDateKey(marker.date) === activeDate)
    }, [markers, panelCandle?.date])

    return (
        <section className="card h-full flex flex-col overflow-hidden">
            <div className="flex items-center justify-between mb-3 shrink-0">
                <div className="min-w-0 flex items-center gap-3">
                    <CandlestickChart className="w-5 h-5 text-cyan-500" />
                    <div className="min-w-0 flex flex-wrap items-center gap-x-4 gap-y-1">
                        <h2 className="truncate text-lg font-semibold text-slate-900 dark:text-slate-100">{getDisplayName(symbol)} K线</h2>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                            <span className="text-slate-500 dark:text-slate-400">{panelCandle?.date || '--'}</span>
                            <span className={`font-medium ${isUp ? 'text-red-500' : 'text-emerald-500'}`}>收盘 {formatNumber(panelCandle?.close)}</span>
                            <span className="text-slate-500 dark:text-slate-400">开盘 {formatNumber(panelCandle?.open)}</span>
                            <span className={`font-medium ${isUp ? 'text-red-500' : 'text-emerald-500'}`}>{compactChangePercent}</span>
                            <span className="text-slate-500 dark:text-slate-400">高/低 {formatNumber(panelCandle?.high)} / {formatNumber(panelCandle?.low)}</span>
                            <span className="text-slate-500 dark:text-slate-400">量 {formatVolume(panelCandle?.volume)}</span>
                            <span className="text-slate-500 dark:text-slate-400">换手 {panelCandle?.turnover_rate == null ? '--' : `${formatNumber(panelCandle.turnover_rate)}%`}</span>
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-1.5">
                    {showChanlunOverlay && (
                    <div className="hidden flex-wrap items-center gap-1 rounded-xl border border-slate-200 px-2 py-1 dark:border-slate-700 xl:flex">
                        <Layers3 className="h-3.5 w-3.5 text-violet-500" />
                        {[
                            ['fractals', '分型'],
                            ['bi', '笔'],
                            ['segments', '线段'],
                            ['zhongshu', '中枢'],
                            ['buySell', '买卖点'],
                        ].map(([key, label]) => {
                            const active = overlayToggles[key as keyof typeof overlayToggles]
                            return (
                                <button
                                    key={key}
                                    type="button"
                                    onClick={() => setOverlayToggles((prev) => ({ ...prev, [key]: !prev[key as keyof typeof prev] }))}
                                    className={`rounded-lg px-2 py-1 text-[11px] font-medium transition ${
                                        active
                                            ? 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300'
                                            : 'text-slate-500 dark:text-slate-400'
                                    }`}
                                >
                                    {label}
                                </button>
                            )
                        })}
                    </div>
                    )}
                    {showCurrentSymbolButton && (
                        <button
                            onClick={() => onSymbolChange?.(currentAnalysisSymbol)}
                            className="text-xs px-2.5 py-1 rounded border border-emerald-500 text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 hover:bg-emerald-100 dark:hover:bg-emerald-500/20 transition-colors"
                        >
                            {currentSymbolLabel}
                        </button>
                    )}
                    {INDEX_PRESETS.map((item) => (
                        <button
                            key={item.symbol}
                            onClick={() => onSymbolChange?.(item.symbol)}
                            className={`text-xs px-2 py-1 rounded border transition-colors ${item.symbol === symbol
                                    ? 'border-blue-500 text-blue-500 bg-blue-50 dark:bg-blue-500/10'
                                    : 'border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:border-slate-400 dark:hover:border-slate-500'
                                }`}
                        >
                            {item.label}
                        </button>
                    ))}
                </div>
            </div>
            <div className="relative flex-1 min-h-0 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 overflow-hidden">
                <div ref={containerRef} className="absolute inset-0" />
                {loading && (
                    <div className="absolute right-3 top-3 text-xs px-2 py-1 rounded bg-white/90 dark:bg-slate-800/90 text-slate-600 dark:text-slate-400 flex items-center gap-1">
                        <Activity className="w-3 h-3 animate-pulse" />
                        加载中
                    </div>
                )}
                {showChanlunOverlay && overlayLoading && (
                    <div className="absolute right-3 top-12 text-xs px-2 py-1 rounded bg-white/90 dark:bg-slate-800/90 text-violet-600 dark:text-violet-300 flex items-center gap-1">
                        <Layers3 className="w-3 h-3 animate-pulse" />
                        缠论计算中
                    </div>
                )}
                {error && (
                    <div className="absolute left-3 top-3 text-xs px-2 py-1 rounded bg-white/90 dark:bg-slate-800/90 text-orange-500">
                        {error}
                    </div>
                )}
                {activeMarkerDetails.length > 0 && (
                    <div className="absolute left-3 bottom-3 z-10 max-w-[420px] rounded-xl bg-white/95 px-3 py-2 shadow-lg ring-1 ring-slate-200 dark:bg-slate-900/95 dark:ring-slate-700">
                        <div className="mb-1 text-[11px] font-medium text-slate-500 dark:text-slate-400">当日买卖点</div>
                        <div className="space-y-1.5">
                            {activeMarkerDetails.slice(0, 4).map((marker, index) => {
                                const isBuy = marker.side === 'buy'
                                return (
                                    <div key={`${marker.timestamp || marker.date}_${index}`} className="text-xs">
                                        <span className={`font-semibold ${isBuy ? 'text-red-500' : 'text-emerald-500'}`}>
                                            {isBuy ? '买点' : '卖点'}
                                        </span>
                                        <span className="ml-2 text-slate-700 dark:text-slate-200">
                                            {marker.timestamp ? marker.timestamp.slice(0, 19).replace('T', ' ') : (marker.date || '').slice(0, 10)}
                                        </span>
                                        {marker.price != null && <span className="ml-2 text-slate-700 dark:text-slate-200">@ {formatNumber(marker.price)}</span>}
                                        {marker.quantity != null && <span className="ml-2 text-slate-700 dark:text-slate-200">{marker.quantity} 股</span>}
                                        {marker.reason && <div className="mt-0.5 text-slate-500 dark:text-slate-400">{marker.reason}</div>}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                )}
                {showChanlunOverlay && overlayMessage && !error && (
                    <div className="absolute left-3 top-12 text-xs px-2 py-1 rounded bg-white/90 dark:bg-slate-800/90 text-violet-600 dark:text-violet-300">
                        {overlayMessage}
                    </div>
                )}
            </div>
        </section>
    )
}
