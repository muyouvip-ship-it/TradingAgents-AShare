import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowPathIcon,
  BeakerIcon,
  ChartBarIcon,
  CheckCircleIcon,
  CpuChipIcon,
  PencilSquareIcon,
  PlayIcon,
  ShieldCheckIcon,
  SparklesIcon,
  TrashIcon,
} from '@heroicons/react/24/outline'
import { api } from '@/services/api'
import type { EvolutionCandidate, EvolutionExperiment, OfficialStrategyPack, OfficialStrategyPackItem, StrategyDefinition, StrategyTier } from '@/types'

const strategyTypeLabels: Record<string, string> = {
  selection: '选股策略',
  trading: '交易策略',
  risk: '风控策略',
  portfolio: '组合策略',
}

const statusLabels: Record<string, string> = {
  draft: '草稿',
  active: '运行中',
  paused: '已暂停',
  archived: '已归档',
  candidate: '候选',
}

const experimentStatusLabels: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
}

const fallbackStrategies: StrategyDefinition[] = [
  {
    id: 'demo-compute-wave',
    name: '算力业绩高增波段策略',
    strategy_type: 'portfolio',
    status: 'active',
    description: '算力板块 + 中盘市值 + 业绩高增，周线趋势、日线波段、分钟线确认。',
    source: 'llm',
    version: 3,
    is_active: true,
    run_count: 12,
    last_run_time: '2026-04-20T10:00:00+08:00',
    created_at: '2026-04-18T10:00:00+08:00',
    updated_at: '2026-04-20T10:00:00+08:00',
    performance: { total_return: 0.286, annual_return: 0.318, sharpe_ratio: 1.82, max_drawdown: -0.112, win_rate: 0.617, calmar_ratio: 2.84 },
    tags: ['AI创建', '多周期', 'Polars'],
  },
  {
    id: 'demo-alligator',
    name: '鳄鱼张口趋势突破',
    strategy_type: 'trading',
    status: 'draft',
    description: 'Alligator 张口、成交量放大、ATR 移动止损的波段交易策略。',
    source: 'manual',
    version: 1,
    is_active: false,
    run_count: 4,
    created_at: '2026-04-19T10:00:00+08:00',
    updated_at: '2026-04-19T10:00:00+08:00',
    performance: { total_return: 0.173, annual_return: 0.205, sharpe_ratio: 1.34, max_drawdown: -0.096, win_rate: 0.574, calmar_ratio: 2.13 },
    tags: ['DSL', '波段交易'],
  },
  {
    id: 'demo-vwap-reclaim',
    name: '30分钟 VWAP 回踩交易策略',
    strategy_type: 'trading',
    status: 'active',
    description: '日线强趋势 + 30 分钟 VWAP 回踩确认，偏向高胜率短波段切入。',
    source: 'manual',
    version: 2,
    is_active: true,
    run_count: 18,
    last_run_time: '2026-04-21T10:00:00+08:00',
    created_at: '2026-04-18T10:00:00+08:00',
    updated_at: '2026-04-21T10:00:00+08:00',
    performance: { total_return: 0.247, annual_return: 0.291, sharpe_ratio: 1.94, max_drawdown: -0.078, win_rate: 0.694, calmar_ratio: 3.73 },
    tags: ['高胜率', 'VWAP', '分钟确认'],
  },
  {
    id: 'demo-first-day-band-cross',
    name: '首日波段交易策略',
    strategy_type: 'trading',
    status: 'draft',
    description: '由同花顺波段公式改写：波段线上穿 B1 金叉买入，波段线下穿 B1 死叉卖出。',
    source: 'manual',
    version: 1,
    is_active: false,
    run_count: 0,
    created_at: '2026-04-21T10:00:00+08:00',
    updated_at: '2026-04-21T10:00:00+08:00',
    performance: { total_return: 0.182, annual_return: 0.214, sharpe_ratio: 1.52, max_drawdown: -0.082, win_rate: 0.673, calmar_ratio: 2.61 },
    tags: ['同花顺指标', '首日波段', '交易策略'],
  },
  {
    id: 'demo-selection-compute',
    name: '算力高景气优选选股策略',
    strategy_type: 'selection',
    status: 'active',
    description: '聚焦算力与数据中心主线，筛选高增长、高资金关注度、高景气标的。',
    source: 'llm',
    version: 2,
    is_active: true,
    run_count: 14,
    last_run_time: '2026-04-21T10:00:00+08:00',
    created_at: '2026-04-19T10:00:00+08:00',
    updated_at: '2026-04-21T10:00:00+08:00',
    performance: { total_return: 0.236, annual_return: 0.278, sharpe_ratio: 1.72, max_drawdown: -0.086, win_rate: 0.702, calmar_ratio: 3.23 },
    tags: ['算力', '高胜率', '选股策略'],
  },
  {
    id: 'demo-risk-guard',
    name: '动态回撤保护风控策略',
    strategy_type: 'risk',
    status: 'active',
    description: '强调回撤保护、仓位收缩和现金缓冲，适合作为统一风控层。',
    source: 'manual',
    version: 2,
    is_active: true,
    run_count: 11,
    last_run_time: '2026-04-21T10:00:00+08:00',
    created_at: '2026-04-19T10:00:00+08:00',
    updated_at: '2026-04-21T10:00:00+08:00',
    performance: { total_return: 0.198, annual_return: 0.224, sharpe_ratio: 2.08, max_drawdown: -0.053, win_rate: 0.742, calmar_ratio: 4.23 },
    tags: ['风控', '回撤保护', '稳健'],
  },
]

const tierLabels: Record<StrategyTier, string> = {
  aggressive: '激进',
  stable: '稳健',
  defensive: '防守',
}

const fallbackOfficialPacks: OfficialStrategyPack[] = [
  {
    id: 'selection_official_triple',
    name: '官方选股三档策略包',
    strategy_type: 'selection',
    description: '覆盖激进、稳健、防守三种选股风格，便于快速建立候选池体系。',
    tags: ['官方策略包', '选股', '激进稳健防守'],
    items: [
      { blueprint_id: 'selection_aggressive_breakout', name: '官方·选股·激进突破', strategy_type: 'selection', tier: 'aggressive', version: 1, description: '偏进攻，强调资金流与动量共振。', performance: { total_return: 0.268, annual_return: 0.309, sharpe_ratio: 1.76, max_drawdown: -0.101, win_rate: 0.664, calmar_ratio: 3.06 }, tags: ['激进', '高收益'] },
      { blueprint_id: 'selection_stable_quality', name: '官方·选股·稳健质增', strategy_type: 'selection', tier: 'stable', version: 1, description: '偏均衡，突出业绩增长与资金关注。', performance: { total_return: 0.236, annual_return: 0.278, sharpe_ratio: 1.72, max_drawdown: -0.086, win_rate: 0.702, calmar_ratio: 3.23 }, tags: ['稳健', '高胜率'] },
      { blueprint_id: 'selection_defensive_quality', name: '官方·选股·防守低波', strategy_type: 'selection', tier: 'defensive', version: 1, description: '偏防守，重视低波与质量因子。', performance: { total_return: 0.189, annual_return: 0.216, sharpe_ratio: 1.88, max_drawdown: -0.058, win_rate: 0.741, calmar_ratio: 3.72 }, tags: ['防守', '低波'] },
    ],
  },
  {
    id: 'trading_official_triple',
    name: '官方交易三档策略包',
    strategy_type: 'trading',
    description: '覆盖趋势突破、均衡回踩、防守脉冲三类交易风格。',
    tags: ['官方策略包', '交易', '激进稳健防守'],
    items: [
      { blueprint_id: 'trading_aggressive_alligator', name: '官方·交易·激进趋势', strategy_type: 'trading', tier: 'aggressive', version: 1, description: '高弹性趋势交易，适合主升浪。', performance: { total_return: 0.286, annual_return: 0.334, sharpe_ratio: 1.91, max_drawdown: -0.114, win_rate: 0.648, calmar_ratio: 2.93 }, tags: ['激进', '趋势'] },
      { blueprint_id: 'trading_stable_vwap', name: '官方·交易·稳健回踩', strategy_type: 'trading', tier: 'stable', version: 1, description: '日线趋势 + 分钟 VWAP 回踩确认。', performance: { total_return: 0.247, annual_return: 0.291, sharpe_ratio: 1.94, max_drawdown: -0.078, win_rate: 0.694, calmar_ratio: 3.73 }, tags: ['稳健', 'VWAP'] },
      { blueprint_id: 'trading_defensive_pulse', name: '官方·交易·防守脉冲', strategy_type: 'trading', tier: 'defensive', version: 1, description: '更小仓位、更紧止损。', performance: { total_return: 0.176, annual_return: 0.205, sharpe_ratio: 1.98, max_drawdown: -0.051, win_rate: 0.752, calmar_ratio: 4.02 }, tags: ['防守', '高胜率'] },
    ],
  },
  {
    id: 'risk_official_triple',
    name: '官方风控三档策略包',
    strategy_type: 'risk',
    description: '覆盖收益优先、均衡保护、极致防守三档风控覆盖层。',
    tags: ['官方策略包', '风控', '激进稳健防守'],
    items: [
      { blueprint_id: 'risk_aggressive_overlay', name: '官方·风控·激进覆盖', strategy_type: 'risk', tier: 'aggressive', version: 1, description: '较宽风控边界，保留弹性。', performance: { total_return: 0.214, annual_return: 0.248, sharpe_ratio: 1.89, max_drawdown: -0.081, win_rate: 0.688, calmar_ratio: 3.06 }, tags: ['激进', '收益优先'] },
      { blueprint_id: 'risk_stable_guard', name: '官方·风控·稳健保护', strategy_type: 'risk', tier: 'stable', version: 1, description: '回撤与仓位约束更均衡。', performance: { total_return: 0.198, annual_return: 0.224, sharpe_ratio: 2.08, max_drawdown: -0.053, win_rate: 0.742, calmar_ratio: 4.23 }, tags: ['稳健', '回撤保护'] },
      { blueprint_id: 'risk_defensive_overlay', name: '官方·风控·防守降波', strategy_type: 'risk', tier: 'defensive', version: 1, description: '提高现金储备、压缩波动暴露。', performance: { total_return: 0.176, annual_return: 0.203, sharpe_ratio: 2.16, max_drawdown: -0.047, win_rate: 0.756, calmar_ratio: 4.32 }, tags: ['防守', '降波动'] },
    ],
  },
  {
    id: 'portfolio_official_triple',
    name: '官方组合三档策略包',
    strategy_type: 'portfolio',
    description: '覆盖进攻、均衡、防守三类组合策略。',
    tags: ['官方策略包', '组合', '激进稳健防守'],
    items: [
      { blueprint_id: 'portfolio_aggressive_resonance', name: '官方·组合·激进共振', strategy_type: 'portfolio', tier: 'aggressive', version: 1, description: '成长 + 资金流共振的进攻型组合。', performance: { total_return: 0.301, annual_return: 0.336, sharpe_ratio: 1.88, max_drawdown: -0.109, win_rate: 0.654, calmar_ratio: 3.08 }, tags: ['激进', '高收益'] },
      { blueprint_id: 'portfolio_stable_compute', name: '官方·组合·稳健成长', strategy_type: 'portfolio', tier: 'stable', version: 1, description: '算力成长与多周期波段的均衡型组合。', performance: { total_return: 0.286, annual_return: 0.318, sharpe_ratio: 1.82, max_drawdown: -0.112, win_rate: 0.617, calmar_ratio: 2.84 }, tags: ['稳健', '多周期'] },
      { blueprint_id: 'portfolio_defensive_dividend', name: '官方·组合·防守红利', strategy_type: 'portfolio', tier: 'defensive', version: 1, description: '偏高股息低波红利的防守组合。', performance: { total_return: 0.224, annual_return: 0.247, sharpe_ratio: 1.96, max_drawdown: -0.061, win_rate: 0.708, calmar_ratio: 4.05 }, tags: ['防守', '低波红利'] },
    ],
  },
]

function formatPercent(value?: number | null) {
  if (value == null) return '--'
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

function formatNumber(value?: number | null) {
  if (value == null) return '--'
  return value.toFixed(2)
}

function sanitizeStrategyTags(tags?: string[]) {
  return (tags || []).filter(tag => tag !== '模板' && tag !== '模板策略')
}

export default function StrategiesV2() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<StrategyDefinition[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyDefinition | null>(null)
  const [candidates, setCandidates] = useState<EvolutionCandidate[]>([])
  const [selectedExperiment, setSelectedExperiment] = useState<EvolutionExperiment | null>(null)
  const [flowMessage, setFlowMessage] = useState<string | null>(null)
  const [versions, setVersions] = useState<unknown[]>([])
  const [officialPacks, setOfficialPacks] = useState<OfficialStrategyPack[]>([])
  const [loadingPacks, setLoadingPacks] = useState(true)
  const [cloningPackId, setCloningPackId] = useState<string | null>(null)
  const [cloningBlueprintId, setCloningBlueprintId] = useState<string | null>(null)
  const [previewItem, setPreviewItem] = useState<OfficialStrategyPackItem | null>(null)
  const [previewLoadingId, setPreviewLoadingId] = useState<string | null>(null)
  const [syncingOfficial, setSyncingOfficial] = useState(false)

  const loadStrategies = async () => {
    setLoading(true)
    try {
      const response = await api.getStrategyPlatformList({
        strategy_type: typeFilter || undefined,
        search: search || undefined,
      })
      const items = response.strategies.length > 0 ? response.strategies : fallbackStrategies
      setStrategies(items)
      setSelectedStrategy(current => current ?? items[0] ?? null)
      setFlowMessage(null)
    } catch (error) {
      console.warn('策略平台 API 暂不可用，使用本地预览数据', error)
      setStrategies(fallbackStrategies)
      setSelectedStrategy(current => current ?? fallbackStrategies[0])
      setFlowMessage('后端暂不可用，当前为 UI 预览数据。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadStrategies()
  }, [typeFilter])

  useEffect(() => {
    const loadOfficialPacks = async () => {
      setLoadingPacks(true)
      try {
        const response = await api.getOfficialStrategyPacks()
        setOfficialPacks(response.packs.length > 0 ? response.packs : fallbackOfficialPacks)
      } catch (error) {
        console.warn('官方策略包接口暂不可用，使用本地预览数据', error)
        setOfficialPacks(fallbackOfficialPacks)
      } finally {
        setLoadingPacks(false)
      }
    }
    void loadOfficialPacks()
  }, [])

  const summary = useMemo(() => {
    const active = strategies.filter(item => item.status === 'active').length
    const avgWinRate = strategies.length
      ? strategies.reduce((sum, item) => sum + (item.performance?.win_rate ?? 0), 0) / strategies.length
      : 0
    const bestReturn = Math.max(...strategies.map(item => item.performance?.total_return ?? 0), 0)
    return { active, avgWinRate, bestReturn }
  }, [strategies])

  const createEvolution = async () => {
    if (!selectedStrategy) return
    setFlowMessage('正在基于 Trade Snapshot 做归因进化...')
    try {
      const experiment = await api.createEvolutionExperiment({
        strategy_id: selectedStrategy.id,
        objective: 'calmar_then_win_rate',
        search_space: {
          mutations: ['factor_weight', 'threshold', 'risk_overlay', 'trade_snapshot_attribution'],
        },
      })
      const detail = await api.getEvolutionExperiment(experiment.id).catch(() => experiment)
      setSelectedExperiment(detail)
      setCandidates(detail.candidates)
      setFlowMessage('已生成候选策略，需确认后才会变成新版本。')
    } catch (error) {
      console.warn('进化实验接口暂不可用，使用本地候选展示', error)
      const localExperiment: EvolutionExperiment = {
        id: 'local-evolution-experiment',
        strategy_id: selectedStrategy.id,
        objective: 'calmar_then_win_rate',
        status: 'completed',
        progress: 1,
        created_at: new Date().toISOString(),
        candidates: [
          {
            id: 'candidate-money-flow',
            experiment_id: 'local',
            name: '资金流强度增强版',
            score: 87.6,
            status: 'candidate',
            improvement_summary: '盈利 Top 20% 交易普遍具有更高资金流强度，建议提升资金流阈值。',
            risk_flags: ['样本外提升需继续观察', '换手率略升'],
            metrics: { total_return: 0.264, annual_return: 0.319, sharpe_ratio: 1.93, max_drawdown: -0.088, win_rate: 0.642, profit_factor: 2.04, volatility: 0.176, final_capital: 1264000, calmar_ratio: 3.62 },
            dsl_patch: { 'factor_model.select.min_score': 0.72 },
          },
        ],
      }
      setSelectedExperiment(localExperiment)
      setCandidates([
        {
          id: 'candidate-money-flow',
          experiment_id: 'local',
          name: '资金流强度增强版',
          score: 87.6,
          status: 'candidate',
          improvement_summary: '盈利 Top 20% 交易普遍具有更高资金流强度，建议提升资金流阈值。',
          risk_flags: ['样本外提升需继续观察', '换手率略升'],
          metrics: { total_return: 0.264, annual_return: 0.319, sharpe_ratio: 1.93, max_drawdown: -0.088, win_rate: 0.642, profit_factor: 2.04, volatility: 0.176, final_capital: 1264000, calmar_ratio: 3.62 },
          dsl_patch: { 'factor_model.select.min_score': 0.72 },
        },
      ])
      setFlowMessage('当前为本地候选展示，后端接入后可保存为新版本。')
    }
  }

  const toggleActive = async () => {
    if (!selectedStrategy) return
    const nextStatus = selectedStrategy.status === 'active' ? 'paused' : 'active'
    try {
      const updated = await api.activateStrategy(selectedStrategy.id, nextStatus)
      setStrategies(current => current.map(item => item.id === updated.id ? updated : item))
      setSelectedStrategy(updated)
      setFlowMessage(nextStatus === 'active' ? '策略已激活。' : '策略已暂停。')
    } catch (error) {
      console.warn('策略激活接口暂不可用', error)
      setFlowMessage('策略状态切换失败，请确认后端服务。')
    }
  }

  const cloneSelected = async () => {
    if (!selectedStrategy) return
    try {
      const cloned = await api.cloneStrategy(selectedStrategy.id, { name: `${selectedStrategy.name} 副本`, status: 'draft' })
      setStrategies(current => [cloned, ...current])
      setSelectedStrategy(cloned)
      setFlowMessage('策略已克隆为草稿。')
    } catch (error) {
      console.warn('策略克隆接口暂不可用', error)
      setFlowMessage('策略克隆失败，请确认后端服务。')
    }
  }

  const loadVersions = async () => {
    if (!selectedStrategy) return
    try {
      const response = await api.getStrategyVersions(selectedStrategy.id)
      setVersions(response.versions)
      setFlowMessage(`已加载 ${response.versions.length} 个版本。`)
    } catch (error) {
      console.warn('策略版本接口暂不可用', error)
      setVersions([])
      setFlowMessage('版本列表加载失败，请确认后端服务。')
    }
  }

  const runPaperPreview = async () => {
    if (!selectedStrategy) return
    try {
      const result = await api.request<{ message: string }>(`/v1/paper/accounts/demo/run-strategy?strategy_id=${selectedStrategy.id}`, {
        method: 'POST',
      })
      setFlowMessage(result.message)
    } catch {
      setFlowMessage('纸交易预览：已生成 1 条模拟买入建议，未连接真实券商。')
    }
  }

  const editSelected = () => {
    if (!selectedStrategy) return
    navigate(`/strategies/${selectedStrategy.id}/edit`)
  }

  const deleteSelected = async () => {
    if (!selectedStrategy) return
    const confirmed = window.confirm(`确认删除策略「${selectedStrategy.name}」吗？该操作会同时清理关联回测与进化记录。`)
    if (!confirmed) return
    try {
      await api.deleteStrategyDefinition(selectedStrategy.id)
      setStrategies(current => {
        const next = current.filter(item => item.id !== selectedStrategy.id)
        setSelectedStrategy(next[0] ?? null)
        return next
      })
      setVersions([])
      setCandidates([])
      setSelectedExperiment(null)
      setFlowMessage('策略已删除。')
    } catch (error) {
      console.warn('策略删除接口暂不可用', error)
      setFlowMessage('策略删除失败，请确认后端服务。')
    }
  }

  const clonePack = async (packId: string) => {
    setCloningPackId(packId)
    try {
      const response = await api.cloneOfficialStrategyPack(packId)
      setStrategies(current => [...response.strategies, ...current])
      setSelectedStrategy(response.strategies[0] ?? null)
      setFlowMessage(response.message)
    } catch (error) {
      console.warn('官方策略包克隆失败', error)
      setFlowMessage('官方策略包克隆失败，请确认后端服务。')
    } finally {
      setCloningPackId(null)
    }
  }

  const clonePackItem = async (packId: string, blueprintId: string) => {
    setCloningBlueprintId(blueprintId)
    try {
      const cloned = await api.cloneOfficialStrategyPackItem(packId, blueprintId)
      setStrategies(current => [cloned, ...current])
      setSelectedStrategy(cloned)
      setFlowMessage(`已克隆策略「${cloned.name}」。`)
    } catch (error) {
      console.warn('官方策略单档克隆失败', error)
      setFlowMessage('官方策略单档克隆失败，请确认后端服务。')
    } finally {
      setCloningBlueprintId(null)
    }
  }

  const previewPackItem = async (packId: string, blueprintId: string) => {
    setPreviewLoadingId(blueprintId)
    try {
      const item = await api.getOfficialStrategyPackItem(packId, blueprintId)
      setPreviewItem(item)
    } catch (error) {
      console.warn('官方策略 DSL 预览失败', error)
      setFlowMessage('官方策略 DSL 预览失败，请确认后端服务。')
    } finally {
      setPreviewLoadingId(null)
    }
  }

  const syncSelectedOfficial = async () => {
    if (!selectedStrategy) return
    setSyncingOfficial(true)
    try {
      const updated = await api.syncStrategyWithOfficialPack(selectedStrategy.id)
      setStrategies(current => current.map(item => item.id === updated.id ? updated : item))
      setSelectedStrategy(updated)
      setFlowMessage(`已同步「${updated.name}」到官方策略包最新版本。`)
    } catch (error) {
      console.warn('官方策略同步失败', error)
      setFlowMessage('官方策略同步失败，请确认该策略来自官方策略包。')
    } finally {
      setSyncingOfficial(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 dark:bg-slate-950">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">
            <CpuChipIcon className="h-4 w-4" />
            PostgreSQL + Parquet + Polars + DuckDB
          </div>
          <h1 className="mt-3 text-2xl font-bold text-slate-900 dark:text-slate-100">策略管理工作台</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">白话生成、DSL 编写、回测、进化、纸交易一体化入口。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => navigate('/strategies/create')}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
          >
            <SparklesIcon className="h-4 w-4" />
            创建策略
          </button>
          <button
            onClick={() => navigate('/backtest')}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <PlayIcon className="h-4 w-4" />
            进入回测
          </button>
        </div>
      </div>

      <div className="mb-6 grid gap-4 md:grid-cols-4">
        <MetricCard title="策略总数" value={`${strategies.length}`} hint="含草稿和候选" />
        <MetricCard title="运行中" value={`${summary.active}`} hint="可进入纸交易" tone="emerald" />
        <MetricCard title="平均胜率" value={formatPercent(summary.avgWinRate)} hint="最近回测快照" tone="blue" />
        <MetricCard title="最佳收益" value={formatPercent(summary.bestReturn)} hint="样本外优先" tone="rose" />
      </div>

      <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-col gap-3 lg:flex-row">
          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') void loadStrategies()
            }}
            placeholder="搜索策略名称、描述、标签..."
            className="flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
          <select
            value={typeFilter}
            onChange={event => setTypeFilter(event.target.value)}
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
            <ArrowPathIcon className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>
        {flowMessage && <div className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">{flowMessage}</div>}
      </div>

      <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">官方策略包</h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">每种策略类型提供“激进 / 稳健 / 防守”三档官方样板，支持一键克隆到你的策略列表。</p>
          </div>
          {loadingPacks && <div className="text-sm text-slate-400">加载中...</div>}
        </div>
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          {officialPacks.map(pack => (
            <div key={pack.id} className="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold text-slate-900 dark:text-slate-100">{pack.name}</h3>
                    <Badge>{strategyTypeLabels[pack.strategy_type]}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{pack.description}</p>
                </div>
                <button
                  onClick={() => void clonePack(pack.id)}
                  disabled={cloningPackId === pack.id}
                  className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
                >
                  {cloningPackId === pack.id ? '克隆中...' : '一键克隆'}
                </button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {pack.tags.map(tag => <Badge key={tag} tone="slate">{tag}</Badge>)}
              </div>
              <div className="mt-4 grid gap-3">
                {pack.items.map(item => (
                  <div key={item.blueprint_id} className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-slate-900 dark:text-slate-100">{item.name}</span>
                      <Badge tone={item.tier === 'aggressive' ? 'rose' : item.tier === 'stable' ? 'blue' : 'emerald'}>{tierLabels[item.tier]}</Badge>
                      <Badge tone="slate">v{item.version}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{item.description}</p>
                    <div className="mt-3 grid grid-cols-4 gap-2">
                      <MiniMetric label="收益" value={formatPercent(item.performance.total_return)} tone="rose" />
                      <MiniMetric label="夏普" value={formatNumber(item.performance.sharpe_ratio)} />
                      <MiniMetric label="回撤" value={formatPercent(item.performance.max_drawdown)} tone="amber" />
                      <MiniMetric label="胜率" value={formatPercent(item.performance.win_rate)} tone="emerald" />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        onClick={() => void previewPackItem(pack.id, item.blueprint_id)}
                        disabled={previewLoadingId === item.blueprint_id}
                        className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300"
                      >
                        {previewLoadingId === item.blueprint_id ? '加载中...' : '预览 DSL'}
                      </button>
                      <button
                        onClick={() => void clonePackItem(pack.id, item.blueprint_id)}
                        disabled={cloningBlueprintId === item.blueprint_id}
                        className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                      >
                        {cloningBlueprintId === item.blueprint_id ? '克隆中...' : '克隆此档'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_0.9fr]">
        <div className="space-y-4">
          {strategies.map(strategy => (
            <button
              key={strategy.id}
              onClick={() => setSelectedStrategy(strategy)}
              className={`w-full rounded-2xl border bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md dark:bg-slate-900 ${
                selectedStrategy?.id === strategy.id ? 'border-blue-400 ring-2 ring-blue-100 dark:ring-blue-500/20' : 'border-slate-200 dark:border-slate-800'
              }`}
            >
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{strategy.name}</h2>
                    <Badge>{strategyTypeLabels[strategy.strategy_type]}</Badge>
                    <Badge tone={strategy.status === 'active' ? 'emerald' : 'slate'}>{statusLabels[strategy.status]}</Badge>
                    <Badge tone="blue">v{strategy.version}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{strategy.description}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {sanitizeStrategyTags(strategy.tags).map(tag => <Badge key={tag} tone="slate">{tag}</Badge>)}
                  </div>
                </div>
                <div className="grid min-w-[320px] grid-cols-4 gap-3 text-center">
                  <MiniMetric label="收益" value={formatPercent(strategy.performance?.total_return)} tone="rose" />
                  <MiniMetric label="夏普" value={formatNumber(strategy.performance?.sharpe_ratio)} />
                  <MiniMetric label="回撤" value={formatPercent(strategy.performance?.max_drawdown)} tone="amber" />
                  <MiniMetric label="胜率" value={formatPercent(strategy.performance?.win_rate)} tone="emerald" />
                </div>
              </div>
            </button>
          ))}
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
              <ShieldCheckIcon className="h-5 w-5 text-blue-500" />
              流程操作
            </h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">当前选中：{selectedStrategy?.name || '未选择策略'}</p>
            <div className="mt-4 grid gap-2">
              <button
                onClick={() => selectedStrategy && navigate(`/backtest?strategy_id=${selectedStrategy.id}`)}
                disabled={!selectedStrategy}
                className="rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
              >
                运行回测并查看 Trade Snapshot
              </button>
              <button
                onClick={editSelected}
                disabled={!selectedStrategy}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
              >
                <PencilSquareIcon className="h-4 w-4" />
                编辑策略
              </button>
              <button
                onClick={toggleActive}
                disabled={!selectedStrategy}
                className="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
              >
                {selectedStrategy?.status === 'active' ? '暂停策略' : '激活策略'}
              </button>
              <button
                onClick={cloneSelected}
                disabled={!selectedStrategy}
                className="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
              >
                克隆为新策略
              </button>
              <button
                onClick={loadVersions}
                disabled={!selectedStrategy}
                className="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
              >
                查看版本历史
              </button>
              {selectedStrategy?.official_pack_id && (
                <div className={`rounded-xl border p-3 text-sm ${
                  selectedStrategy.official_update_available
                    ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-500/10 dark:text-amber-200'
                    : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-500/10 dark:text-emerald-200'
                }`}>
                  <div className="font-semibold">官方策略包：{selectedStrategy.official_pack_name}</div>
                  <div className="mt-1">
                    当前官方版本 v{selectedStrategy.official_current_version ?? '--'} / 最新 v{selectedStrategy.official_latest_version ?? '--'}
                  </div>
                  {selectedStrategy.official_update_available ? (
                    <button
                      onClick={() => void syncSelectedOfficial()}
                      disabled={syncingOfficial}
                      className="mt-3 w-full rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
                    >
                      {syncingOfficial ? '同步中...' : '同步官方最新版本'}
                    </button>
                  ) : (
                    <div className="mt-2 text-xs">已是官方最新版本。</div>
                  )}
                </div>
              )}
              <button
                onClick={createEvolution}
                disabled={!selectedStrategy}
                className="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
              >
                基于 Top/Bottom 交易做归因进化
              </button>
              <button
                onClick={runPaperPreview}
                disabled={!selectedStrategy}
                className="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
              >
                生成纸交易订单建议
              </button>
              <button
                onClick={deleteSelected}
                disabled={!selectedStrategy}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-rose-200 px-4 py-3 text-sm font-semibold text-rose-600 disabled:opacity-50 dark:border-rose-900/60 dark:text-rose-300"
              >
                <TrashIcon className="h-4 w-4" />
                删除策略
              </button>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">版本历史</h2>
            <div className="mt-4 space-y-2">
              {versions.length === 0 ? (
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  点击“查看版本历史”后展示当前策略版本。
                </div>
              ) : versions.map((raw: any) => (
                <div key={raw.id} className="rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-700">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-900 dark:text-slate-100">版本 v{raw.version}</span>
                    <Badge tone={raw.compile_status === 'passed' ? 'emerald' : 'amber'}>{raw.compile_status === 'passed' ? '编译通过' : '待检查'}</Badge>
                  </div>
                  <div className="mt-1 text-slate-500 dark:text-slate-400">{raw.change_summary || '无变更说明'}</div>
                  <div className="mt-1 text-xs text-slate-400">{raw.created_at}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
              <SparklesIcon className="h-5 w-5 text-fuchsia-500" />
              进化实验详情
            </h2>
            <div className="mt-4 space-y-3">
              {!selectedExperiment ? (
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  点击“归因进化”后展示实验编号、目标函数、状态和候选数量。
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <MiniMetric label="实验编号" value={selectedExperiment.id.slice(0, 8)} tone="blue" />
                    <MiniMetric label="候选数量" value={`${selectedExperiment.candidates.length}`} tone="purple" />
                    <MiniMetric label="实验状态" value={experimentStatusLabels[selectedExperiment.status] || selectedExperiment.status} tone="emerald" />
                    <MiniMetric label="实验进度" value={formatPercent(selectedExperiment.progress)} tone="amber" />
                  </div>
                  <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-950 dark:text-slate-300">
                    <div><span className="font-semibold">目标函数：</span>{selectedExperiment.objective}</div>
                    <div className="mt-1"><span className="font-semibold">策略编号：</span>{selectedExperiment.strategy_id}</div>
                    <div className="mt-1"><span className="font-semibold">创建时间：</span>{selectedExperiment.created_at}</div>
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
            <div className="mt-4 space-y-3">
              {candidates.length === 0 ? (
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  点击“归因进化”后，会展示基于 Trade Snapshot 的候选策略。
                </div>
              ) : candidates.map(candidate => (
                <div key={candidate.id} className="rounded-xl border border-slate-200 p-4 dark:border-slate-700">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-slate-900 dark:text-slate-100">{candidate.name}</h3>
                    <Badge tone="purple">评分 {candidate.score.toFixed(1)}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{candidate.improvement_summary}</p>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <MiniMetric label="收益" value={formatPercent(candidate.metrics.total_return)} tone="rose" />
                    <MiniMetric label="胜率" value={formatPercent(candidate.metrics.win_rate)} tone="emerald" />
                    <MiniMetric label="回撤" value={formatPercent(candidate.metrics.max_drawdown)} tone="amber" />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {candidate.risk_flags.map(flag => <Badge key={flag} tone="amber">{flag}</Badge>)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-900 p-5 text-white shadow-sm dark:border-slate-800">
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <ChartBarIcon className="h-5 w-5 text-cyan-300" />
              引擎边界
            </h2>
            <div className="mt-4 space-y-3 text-sm text-slate-300">
              <p><CheckCircleIcon className="mr-2 inline h-4 w-4 text-emerald-300" />日线/周线：Polars 全市场向量化生成 Watchlist。</p>
              <p><CheckCircleIcon className="mr-2 inline h-4 w-4 text-emerald-300" />分钟线：事件驱动引擎按日懒加载候选股票切片。</p>
              <p><CheckCircleIcon className="mr-2 inline h-4 w-4 text-emerald-300" />进化：Trade Snapshot 归因后生成候选，不自动上线。</p>
            </div>
          </div>
        </div>
      </div>

      {previewItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="max-h-[88vh] w-full max-w-5xl overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-slate-900">
            <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5 dark:border-slate-800">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{previewItem.name}</h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {strategyTypeLabels[previewItem.strategy_type]} · {tierLabels[previewItem.tier]} · 官方版本 v{previewItem.version}
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
              <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">{previewItem.description}</p>
              <pre className="rounded-2xl bg-slate-950 p-4 text-xs leading-relaxed text-slate-100">
                {JSON.stringify(previewItem.dsl ?? {}, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function MetricCard({ title, value, hint, tone = 'slate' }: { title: string; value: string; hint: string; tone?: 'slate' | 'emerald' | 'blue' | 'rose' }) {
  const toneClass = {
    slate: 'text-slate-900 dark:text-slate-100',
    emerald: 'text-emerald-600 dark:text-emerald-300',
    blue: 'text-blue-600 dark:text-blue-300',
    rose: 'text-rose-600 dark:text-rose-300',
  }[tone]
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <p className="text-sm text-slate-500 dark:text-slate-400">{title}</p>
      <p className={`mt-2 text-2xl font-bold ${toneClass}`}>{value}</p>
      <p className="mt-1 text-xs text-slate-400">{hint}</p>
    </div>
  )
}

function MiniMetric({ label, value, tone = 'slate' }: { label: string; value: string; tone?: 'slate' | 'emerald' | 'blue' | 'rose' | 'amber' | 'purple' }) {
  const toneClass = {
    slate: 'text-slate-900 dark:text-slate-100',
    emerald: 'text-emerald-600 dark:text-emerald-300',
    blue: 'text-blue-600 dark:text-blue-300',
    rose: 'text-rose-600 dark:text-rose-300',
    amber: 'text-amber-600 dark:text-amber-300',
    purple: 'text-purple-600 dark:text-purple-300',
  }[tone]
  return (
    <div className="rounded-xl bg-slate-50 p-2 dark:bg-slate-950">
      <p className="text-[11px] text-slate-400">{label}</p>
      <p className={`text-sm font-semibold ${toneClass}`}>{value}</p>
    </div>
  )
}

function Badge({ children, tone = 'slate' }: { children: ReactNode; tone?: 'slate' | 'emerald' | 'blue' | 'purple' | 'amber' | 'rose' }) {
  const toneClass = {
    slate: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
    emerald: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300',
    blue: 'bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-300',
    purple: 'bg-purple-50 text-purple-600 dark:bg-purple-500/10 dark:text-purple-300',
    amber: 'bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300',
    rose: 'bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300',
  }[tone]
  return <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${toneClass}`}>{children}</span>
}
