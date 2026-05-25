import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import AgentCollaboration from '@/components/AgentCollaboration'
import DebateDrawer from '@/components/DebateDrawer'
import ReportViewer from '@/components/ReportViewer'
import ChatCopilotPanel from '@/components/ChatCopilotPanel'
import DecisionCard from '@/components/DecisionCard'
import RiskRadar from '@/components/RiskRadar'
import KeyMetrics from '@/components/KeyMetrics'
import { useAnalysisStore } from '@/stores/analysisStore'

const KlinePanel = lazy(() => import('@/components/KlinePanel'))

function mapDecision(decision?: string): 'buy' | 'sell' | 'hold' | 'add' | 'reduce' | 'watch' | undefined {
    if (!decision) return undefined
    const d = decision.toUpperCase()
    if (d.includes('SELL') || d.includes('卖出')) return 'sell'
    if (d.includes('REDUCE') || d.includes('减持')) return 'reduce'
    if (d.includes('WATCH') || d.includes('观望')) return 'watch'
    if (d.includes('HOLD') || d.includes('持有')) return 'hold'
    if (d.includes('ADD') || d.includes('增持')) return 'add'
    if (d.includes('BUY') || d.includes('买入')) return 'buy'
    return undefined
}

function extractConfidence(text?: string): number | undefined {
    if (!text) return undefined
    const m = text.match(/置信度[:：]\s*(\d+)%/i) ?? text.match(/confidence[:：]\s*(\d+)%/i)
    if (m) {
        const v = parseInt(m[1])
        return v >= 0 && v <= 100 ? v : undefined
    }
    return undefined
}

function extractPrice(text: string | undefined, type: 'target' | 'stop'): number | undefined {
    if (!text) return undefined
    const normalized = text.replace(/[*_`#>()[\]（）]/g, '')
    const patterns = type === 'target'
        ? [/目标(?:价|价格|位|价位)?(?:区间)?\s*[:：]?\s*[¥$]?\s*(\d+(?:\.\d+)?)/, /(?:target|target\s*price)\s*[:：]?\s*[¥$]?\s*(\d+(?:\.\d+)?)/i]
        : [/止损(?:价|价格|位|价位)?\s*[:：]?\s*[¥$]?\s*(\d+(?:\.\d+)?)/, /(?:stop[-\s_]?loss|stop\s*price)\s*[:：]?\s*[¥$]?\s*(\d+(?:\.\d+)?)/i]
    for (const p of patterns) {
        const m = normalized.match(p)
        if (m) return parseFloat(m[1])
    }
    return undefined
}

export default function Analysis() {
    const [searchParams] = useSearchParams()
    const querySymbol = (searchParams.get('symbol') || '').trim().toUpperCase()
    const [activeSymbol, setActiveSymbol] = useState(() => querySymbol || useAnalysisStore.getState().currentSymbol || '000001.SH')
    const [activeSection, setActiveSection] = useState<string | undefined>()
    const [debateDrawer, setDebateDrawer] = useState<'research' | 'risk' | null>(null)
    const reportRef = useRef<HTMLDivElement | null>(null)
    const {
        report,
        currentSymbol,
        setCurrentSymbol,
        jobConfidence,
        jobTargetPrice,
        jobStopLoss,
        riskItems,
        keyMetrics,
    } = useAnalysisStore()

    const handleShowReport = (section?: string) => {
        setActiveSection(section)
        reportRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }

    const initialChatInput = querySymbol ? `分析 ${querySymbol} 今日走势` : undefined

    useEffect(() => {
        if (!querySymbol) return
        const timer = window.setTimeout(() => setActiveSymbol(querySymbol), 0)
        return () => window.clearTimeout(timer)
    }, [querySymbol])

    useEffect(() => {
        if (!currentSymbol || querySymbol) return
        const timer = window.setTimeout(() => {
            setActiveSymbol(prev => (prev === currentSymbol ? prev : currentSymbol))
        }, 0)
        return () => window.clearTimeout(timer)
    }, [currentSymbol, querySymbol])

    const finalDecision = report?.final_trade_decision
    const confidence = jobConfidence ?? extractConfidence(finalDecision)
    const targetPrice = jobTargetPrice ?? extractPrice(finalDecision, 'target')
    const stopLoss = jobStopLoss ?? extractPrice(finalDecision, 'stop')

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-[340px_minmax(0,1fr)] gap-4 min-h-[calc(100vh-5rem)]">
                <aside className="h-[calc(100vh-5rem)] sticky top-0 flex flex-col gap-4">
                    <div className="min-h-0 flex-1">
                        <ChatCopilotPanel
                            onSymbolDetected={(symbol) => {
                                setActiveSymbol(symbol)
                                setCurrentSymbol(symbol)
                            }}
                            onShowReport={handleShowReport}
                            initialInput={initialChatInput}
                        />
                    </div>
                </aside>

                <div className="min-w-0 space-y-4">
                    <div className="h-[360px]">
                        <Suspense
                            fallback={(
                                <div className="card flex h-full items-center justify-center text-slate-500 dark:text-slate-400">
                                    <svg className="mr-2 h-5 w-5 animate-spin text-blue-500" viewBox="0 0 24 24" fill="none">
                                        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.2" strokeWidth="4" />
                                        <path d="M22 12A10 10 0 0 0 12 2" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
                                    </svg>
                                    正在加载 K 线组件...
                                </div>
                            )}
                        >
                            <KlinePanel
                                symbol={activeSymbol}
                                onSymbolChange={(symbol) => {
                                    setActiveSymbol(symbol)
                                }}
                            />
                        </Suspense>
                    </div>

                    <AgentCollaboration onSelectSection={handleShowReport} onOpenDebate={setDebateDrawer} selectedSection={activeSection} />

                    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
                        <DecisionCard
                            symbol={activeSymbol}
                            report={report || undefined}
                            decision={mapDecision(report?.decision)}
                            direction={report?.direction}
                            confidence={confidence}
                            targetPrice={targetPrice}
                            stopLoss={stopLoss}
                            reasoning={finalDecision?.slice(0, 300)}
                        />
                        <RiskRadar items={riskItems} />
                        <KeyMetrics items={keyMetrics} />
                    </div>

                    <div ref={reportRef}>
                        <ReportViewer activeSection={activeSection} />
                    </div>
                </div>
            </div>

            <DebateDrawer debate={debateDrawer} onClose={() => setDebateDrawer(null)} />
        </div>
    )
}
