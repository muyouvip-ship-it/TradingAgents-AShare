import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  PlusIcon,
  PlayIcon,
  PauseIcon,
  BeakerIcon,
  ChartBarIcon,
  TrashIcon,
  ArrowPathIcon,
  MagnifyingGlassIcon,
} from '@heroicons/react/24/outline'

interface Strategy {
  id: string
  name: string
  strategy_type: string
  description: string
  status: string
  is_active: boolean
  version: number
  run_count: number
  last_run_time?: string
  created_at: string
  updated_at: string
  performance?: {
    total_return: number
    sharpe_ratio: number
    max_drawdown: number
    win_rate: number
  }
}

const API_BASE_URL = '' // 使用相对路径，由 Vite 代理转发

const strategyTypeConfig = {
  selection: { label: '选股策略', color: 'blue' },
  trading: { label: '交易策略', color: 'green' },
  risk: { label: '风控策略', color: 'yellow' },
  portfolio: { label: '组合策略', color: 'purple' },
}

const statusConfig = {
  draft: { label: '草稿', color: 'gray' },
  active: { label: '运行中', color: 'green' },
  paused: { label: '已暂停', color: 'yellow' },
  archived: { label: '已归档', color: 'red' },
}

export default function StrategiesV2() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterType, setFilterType] = useState<string>('')
  const [filterStatus, setFilterStatus] = useState<string>('')

  useEffect(() => {
    loadStrategies()
  }, [filterType, filterStatus])

  const loadStrategies = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      if (filterType) params.append('strategy_type', filterType)
      if (filterStatus) params.append('status', filterStatus)
      if (searchQuery) params.append('search', searchQuery)

      const response = await fetch(`${API_BASE_URL}/api/v1/strategies?${params}`)
      if (!response.ok) throw new Error('Failed to fetch')
      const data = await response.json()
      setStrategies(data.strategies || [])
      setError(null)
    } catch (err) {
      setError('无法连接到后端API')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    loadStrategies()
  }

  const toggleStrategy = async (strategyId: string, activate: boolean) => {
    try {
      const endpoint = activate ? 'activate' : 'deactivate'
      const response = await fetch(`${API_BASE_URL}/api/v1/strategies/${strategyId}/${endpoint}`, {
        method: 'POST',
      })
      if (!response.ok) throw new Error('Failed to toggle')
      await loadStrategies()
    } catch (err) {
      console.error('Failed to toggle strategy:', err)
      alert('操作失败，请重试')
    }
  }

  const deleteStrategy = async (strategyId: string) => {
    if (!confirm('确定要删除这个策略吗？此操作不可撤销。')) return

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/strategies/${strategyId}`, {
        method: 'DELETE',
      })
      if (!response.ok) throw new Error('Failed to delete')
      await loadStrategies()
    } catch (err) {
      console.error('Failed to delete strategy:', err)
      alert('删除失败，请重试')
    }
  }

  const formatPercentage = (value: number | undefined) => {
    if (value === undefined || value === null) return '-'
    return (value * 100).toFixed(2) + '%'
  }

  const formatNumber = (value: number | undefined) => {
    if (value === undefined || value === null) return '-'
    return value.toFixed(2)
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <ArrowPathIcon className="h-12 w-12 text-blue-600 animate-spin mx-auto mb-4" />
          <p className="text-slate-600">加载策略数据...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-600 mb-4">{error}</p>
          <button
            onClick={loadStrategies}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            重试
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      {/* 页面标题 */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">策略管理中心</h1>
        <p className="text-slate-600 mt-1">管理和监控所有量化策略</p>
      </div>

      {/* 筛选栏 */}
      <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-4 mb-6">
        <div className="flex flex-wrap items-center gap-4">
          {/* 搜索框 */}
          <form onSubmit={handleSearch} className="flex-1 min-w-64">
            <div className="relative">
              <MagnifyingGlassIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-slate-400" />
              <input
                type="text"
                placeholder="搜索策略名称或描述..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          </form>

          {/* 类型筛选 */}
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="">全部类型</option>
            <option value="selection">选股策略</option>
            <option value="trading">交易策略</option>
            <option value="risk">风控策略</option>
            <option value="portfolio">组合策略</option>
          </select>

          {/* 状态筛选 */}
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="">全部状态</option>
            <option value="active">运行中</option>
            <option value="paused">已暂停</option>
            <option value="draft">草稿</option>
          </select>

          {/* 新建按钮 */}
          <button
            onClick={() => navigate('/strategies/create')}
            className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <PlusIcon className="h-5 w-5 mr-2" />
            新建策略
          </button>
        </div>
      </div>

      {/* 策略列表 */}
      {strategies.length === 0 ? (
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-12 text-center">
          <ChartBarIcon className="h-12 w-12 text-slate-400 mx-auto mb-4" />
          <p className="text-slate-600 mb-4">还没有策略</p>
          <button
            onClick={() => navigate('/strategies/create')}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            创建第一个策略
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {strategies.map((strategy) => {
            const typeConfig = strategyTypeConfig[strategy.strategy_type as keyof typeof strategyTypeConfig] || { label: '未知', color: 'gray' }
            const statusConf = statusConfig[strategy.status as keyof typeof statusConfig] || { label: '未知', color: 'gray' }

            return (
              <div
                key={strategy.id}
                className="bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden hover:shadow-md transition-shadow"
              >
                {/* 头部 */}
                <div className="p-4 flex items-center justify-between border-b border-slate-100">
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${strategy.is_active ? 'bg-green-500' : 'bg-slate-300'}`} />
                    <h3 className="font-semibold text-slate-900">{strategy.name}</h3>
                    <span className={`px-2 py-0.5 text-xs rounded bg-${typeConfig.color}-100 text-${typeConfig.color}-700`}>
                      {typeConfig.label}
                    </span>
                    <span className={`px-2 py-0.5 text-xs rounded bg-${statusConf.color}-100 text-${statusConf.color}-700`}>
                      {statusConf.label}
                    </span>
                  </div>
                  <div className="text-sm text-slate-500">
                    v{strategy.version}
                  </div>
                </div>

                {/* 绩效快照 */}
                {strategy.performance && (
                  <div className="p-4 grid grid-cols-2 md:grid-cols-4 gap-4 bg-slate-50">
                    <div>
                      <p className="text-xs text-slate-500 mb-1">总收益</p>
                      <p className={`text-lg font-semibold ${strategy.performance.total_return >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                        {formatPercentage(strategy.performance.total_return)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 mb-1">夏普比率</p>
                      <p className="text-lg font-semibold text-slate-900">
                        {formatNumber(strategy.performance.sharpe_ratio)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 mb-1">最大回撤</p>
                      <p className="text-lg font-semibold text-red-600">
                        {formatPercentage(strategy.performance.max_drawdown)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 mb-1">胜率</p>
                      <p className="text-lg font-semibold text-slate-900">
                        {formatPercentage(strategy.performance.win_rate)}
                      </p>
                    </div>
                  </div>
                )}

                {/* 描述和统计 */}
                <div className="p-4 text-sm text-slate-600">
                  {strategy.description && <p className="mb-2">{strategy.description}</p>}
                  <div className="flex gap-4 text-xs">
                    <span>创建: {new Date(strategy.created_at).toLocaleDateString()}</span>
                    <span>运行次数: {strategy.run_count}</span>
                    {strategy.last_run_time && (
                      <span>最后运行: {new Date(strategy.last_run_time).toLocaleString()}</span>
                    )}
                  </div>
                </div>

                {/* 操作按钮 */}
                <div className="p-4 flex items-center gap-2 border-t border-slate-100">
                  <button
                    onClick={() => navigate(`/strategies/${strategy.id}`)}
                    className="px-3 py-1.5 text-sm border border-slate-300 rounded hover:bg-slate-50 transition-colors"
                  >
                    详情
                  </button>
                  <button
                    onClick={() => navigate(`/strategies/${strategy.id}/edit`)}
                    className="px-3 py-1.5 text-sm border border-slate-300 rounded hover:bg-slate-50 transition-colors"
                  >
                    编辑
                  </button>
                  <button
                    onClick={() => navigate(`/backtest/create?strategy_id=${strategy.id}`)}
                    className="px-3 py-1.5 text-sm border border-slate-300 rounded hover:bg-slate-50 transition-colors flex items-center"
                  >
                    <BeakerIcon className="h-4 w-4 mr-1" />
                    回测
                  </button>
                  <button
                    onClick={() => toggleStrategy(strategy.id, !strategy.is_active)}
                    className={`px-3 py-1.5 text-sm rounded transition-colors flex items-center ${
                      strategy.is_active
                        ? 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200'
                        : 'bg-green-100 text-green-700 hover:bg-green-200'
                    }`}
                  >
                    {strategy.is_active ? (
                      <>
                        <PauseIcon className="h-4 w-4 mr-1" />
                        停用
                      </>
                    ) : (
                      <>
                        <PlayIcon className="h-4 w-4 mr-1" />
                        启动
                      </>
                    )}
                  </button>
                  <button
                    onClick={() => deleteStrategy(strategy.id)}
                    className="ml-auto px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 rounded transition-colors"
                  >
                    <TrashIcon className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
