import { useState, useEffect } from 'react'
import {
  ChartBarIcon,
  ArrowPathIcon,
} from '@heroicons/react/24/outline'

interface Strategy {
  strategy_id: string
  name: string
  strategy_type: 'selection' | 'trading' | 'risk' | 'portfolio'
  description: string
  is_active: boolean
  parameters: Record<string, any>
  last_run_time?: string
  run_count: number
}

const API_BASE_URL = '' // 使用相对路径，由 Vite 代理转发

const strategyTypeConfig = {
  selection: { label: '选股策略', color: 'blue' },
  trading: { label: '交易策略', color: 'green' },
  risk: { label: '风控策略', color: 'yellow' },
  portfolio: { label: '组合策略', color: 'purple' },
}

export default function Strategies() {
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadStrategies()
  }, [])

  const loadStrategies = async () => {
    try {
      setLoading(true)
      const response = await fetch(`${API_BASE_URL}/v1/strategies`)
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

  const toggleStrategy = async (strategyId: string, activate: boolean) => {
    try {
      const endpoint = activate ? 'activate' : 'deactivate'
      await fetch(`${API_BASE_URL}/v1/strategies/${strategyId}/${endpoint}`, {
        method: 'POST',
      })
      await loadStrategies()
    } catch (err) {
      console.error('Failed to toggle strategy:', err)
    }
  }

  const updateParameters = async (strategyId: string, parameters: Record<string, any>) => {
    try {
      await fetch(`${API_BASE_URL}/v1/strategies/${strategyId}/parameters`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parameters }),
      })
      await loadStrategies()
    } catch (err) {
      console.error('Failed to update parameters:', err)
    }
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

  const activeCount = strategies.filter(s => s.is_active).length

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      {/* 页面标题 */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">策略管理</h1>
        <p className="text-slate-600 mt-1">管理和优化您的量化交易策略</p>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-slate-500">总策略数</p>
          <p className="text-2xl font-bold text-slate-900">{strategies.length}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-slate-500">活跃策略</p>
          <p className="text-2xl font-bold text-green-600">{activeCount}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-slate-500">后端状态</p>
          <p className="text-2xl font-bold text-blue-600">✅ 已连接</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 策略列表 */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-lg shadow">
            <div className="p-4 border-b border-slate-200">
              <h2 className="text-lg font-semibold text-slate-900">策略列表</h2>
            </div>

            <div className="divide-y divide-slate-200">
              {strategies.map(strategy => {
                const config = strategyTypeConfig[strategy.strategy_type]
                return (
                  <button
                    key={strategy.strategy_id}
                    onClick={() => setSelectedStrategy(strategy)}
                    className={`w-full p-4 text-left hover:bg-slate-50 transition ${
                      selectedStrategy?.strategy_id === strategy.strategy_id ? 'bg-blue-50' : ''
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <h3 className="font-medium text-slate-900">{strategy.name}</h3>
                        <p className="text-sm text-slate-600 mt-1">{config.label}</p>
                      </div>
                      {strategy.is_active ? (
                        <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded-full">
                          运行中
                        </span>
                      ) : (
                        <span className="px-2 py-1 bg-slate-100 text-slate-600 text-xs rounded-full">
                          已停用
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-slate-500 mt-2 line-clamp-2">{strategy.description}</p>
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {/* 策略详情 */}
        <div className="lg:col-span-2">
          {selectedStrategy ? (
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-start justify-between mb-6">
                <div>
                  <h2 className="text-xl font-bold text-slate-900">{selectedStrategy.name}</h2>
                  <p className="text-slate-600 mt-1">{selectedStrategy.description}</p>
                </div>
                <button
                  onClick={() => toggleStrategy(selectedStrategy.strategy_id, !selectedStrategy.is_active)}
                  className={`px-4 py-2 rounded-lg font-medium ${
                    selectedStrategy.is_active
                      ? 'bg-red-50 text-red-600 hover:bg-red-100'
                      : 'bg-green-50 text-green-600 hover:bg-green-100'
                  }`}
                >
                  {selectedStrategy.is_active ? '停用策略' : '启用策略'}
                </button>
              </div>

              {/* 基本信息 */}
              <div className="bg-slate-50 rounded-lg p-4 mb-6">
                <h3 className="font-semibold text-slate-900 mb-3">基本信息</h3>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-slate-500">策略ID:</span>
                    <span className="ml-2 font-mono text-slate-900">{selectedStrategy.strategy_id}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">类型:</span>
                    <span className="ml-2 text-slate-900">{strategyTypeConfig[selectedStrategy.strategy_type].label}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">运行次数:</span>
                    <span className="ml-2 text-slate-900">{selectedStrategy.run_count} 次</span>
                  </div>
                  <div>
                    <span className="text-slate-500">最后运行:</span>
                    <span className="ml-2 text-slate-900">{selectedStrategy.last_run_time || '未运行'}</span>
                  </div>
                </div>
              </div>

              {/* 参数配置 */}
              <div>
                <h3 className="font-semibold text-slate-900 mb-4">策略参数</h3>
                <div className="space-y-4">
                  {Object.entries(selectedStrategy.parameters).map(([key, value]) => (
                    <div key={key} className="flex items-center gap-4">
                      <label className="w-40 text-sm font-medium text-slate-700">
                        {key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                      </label>
                      <input
                        type={typeof value === 'number' ? 'number' : 'text'}
                        value={value ?? ''}
                        onChange={(e) => {
                          const newValue = typeof value === 'number' 
                            ? parseFloat(e.target.value) 
                            : e.target.value
                          updateParameters(selectedStrategy.strategy_id, {
                            ...selectedStrategy.parameters,
                            [key]: newValue,
                          })
                        }}
                        className="flex-1 px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                        step={typeof value === 'number' ? '0.01' : undefined}
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-white rounded-lg shadow p-12 text-center">
              <ChartBarIcon className="h-16 w-16 mx-auto text-slate-300 mb-4" />
              <h3 className="text-lg font-medium text-slate-900 mb-2">选择一个策略</h3>
              <p className="text-slate-500">从左侧列表中选择一个策略查看详情</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
