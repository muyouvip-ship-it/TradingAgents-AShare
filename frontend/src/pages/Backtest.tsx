import { useState, useEffect } from 'react'
import { PlayIcon } from '@heroicons/react/24/outline'
import { ArrowPathIcon } from '@heroicons/react/24/solid'
import {
  PortfolioValueChart,
  DrawdownChart,
  ReturnsDistributionChart,
} from '../components/Charts'

interface Strategy {
  id: string
  name: string
  strategy_type: string
  description: string
  is_active: boolean
  parameters: Record<string, any>
}

interface BacktestJob {
  id: string
  status: string
  progress: number
  error_message?: string | null
  result?: any
}

interface BacktestResult {
  metrics: {
    total_return: number
    annual_return: number
    sharpe_ratio: number
    max_drawdown: number
    win_rate: number
    profit_factor: number
    volatility: number
    final_capital: number
  }
  details?: {
    trade_list?: Array<any>
    equity_curve?: Array<any>
  }
  summary?: {
    strategy_name?: string
    initial_capital?: number
    final_capital?: number
    symbol_count?: number
    data_row_count?: number
  }
  diagnostics?: {
    zero_trade_reason?: string | null
    buy_trade_count?: number
    sell_trade_count?: number
    has_any_trade?: boolean
  }
}

const API_BASE_URL = ''

export default function Backtest() {
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [params, setParams] = useState({
    symbol: '000001',
    start_date: '2024-09-01',
    end_date: '2024-12-31',
    initial_capital: 1000000,
  })

  useEffect(() => {
    loadStrategies()
  }, [])

  const loadStrategies = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/strategies`)
      if (!response.ok) throw new Error('Failed to fetch strategies')
      const data = await response.json()
      setStrategies(data.strategies || [])
      if (data.strategies?.length > 0) {
        setSelectedStrategy(data.strategies[0].id)
      }
    } catch (err) {
      console.error('Failed to load strategies:', err)
    }
  }

  const runBacktest = async () => {
    if (!selectedStrategy) {
      setError('请选择一个策略')
      return
    }

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/backtest/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy_id: selectedStrategy,
          symbols: params.symbol ? [params.symbol.replace('.SZ', '').replace('.SH', '')] : [],
          start_date: params.start_date,
          end_date: params.end_date,
          initial_capital: params.initial_capital,
          max_symbols: 20,
        }),
      })

      if (!response.ok) throw new Error('Backtest failed')
      const job: BacktestJob = await response.json()

      let finalJob: BacktestJob = job
      for (let i = 0; i < 60; i++) {
        await new Promise((resolve) => setTimeout(resolve, 1000))
        const pollRes = await fetch(`${API_BASE_URL}/api/v1/backtest/jobs/${job.id}`)
        if (!pollRes.ok) throw new Error('Failed to poll backtest job')
        finalJob = await pollRes.json()
        if (finalJob.status === 'completed') break
        if (finalJob.status === 'failed' || finalJob.status === 'cancelled') {
          throw new Error(finalJob.error_message || `Backtest ${finalJob.status}`)
        }
      }

      if (finalJob.status !== 'completed' || !finalJob.result) {
        throw new Error('Backtest did not finish in time')
      }

      setResult(finalJob.result)
    } catch (err) {
      setError(err instanceof Error ? err.message : '回测失败')
    } finally {
      setLoading(false)
    }
  }

  const formatPercent = (value: number) => `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`

  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('zh-CN', {
      style: 'currency',
      currency: 'CNY',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)

  const chartData = (result?.details?.equity_curve || []).map((item: any) => ({
    date: item.date,
    value: item.equity,
    cash: item.cash,
    position: item.positions_value,
    price: item.equity,
  }))

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">策略回测</h1>
        <p className="text-slate-600 mt-1">验证策略在历史数据上的表现</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-slate-900 mb-4">回测配置</h2>

            <div className="mb-4">
              <label className="block text-sm font-medium text-slate-700 mb-2">选择策略</label>
              <select
                value={selectedStrategy}
                onChange={(e) => setSelectedStrategy(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg"
              >
                <option value="">请选择策略</option>
                {strategies.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-slate-700 mb-2">股票代码</label>
              <input
                type="text"
                value={params.symbol}
                onChange={(e) => setParams({ ...params, symbol: e.target.value })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg"
                placeholder="例如: 000001"
              />
            </div>

            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">开始日期</label>
                <input type="date" value={params.start_date} onChange={(e) => setParams({ ...params, start_date: e.target.value })} className="w-full px-3 py-2 border border-slate-300 rounded-lg" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">结束日期</label>
                <input type="date" value={params.end_date} onChange={(e) => setParams({ ...params, end_date: e.target.value })} className="w-full px-3 py-2 border border-slate-300 rounded-lg" />
              </div>
            </div>

            <div className="mb-6">
              <label className="block text-sm font-medium text-slate-700 mb-2">初始资金 (元)</label>
              <input type="number" value={params.initial_capital} onChange={(e) => setParams({ ...params, initial_capital: parseInt(e.target.value) })} className="w-full px-3 py-2 border border-slate-300 rounded-lg" />
            </div>

            <button
              onClick={runBacktest}
              disabled={loading || !selectedStrategy}
              className={`w-full py-3 rounded-lg font-medium transition flex items-center justify-center gap-2 ${loading || !selectedStrategy ? 'bg-slate-100 text-slate-400 cursor-not-allowed' : 'bg-blue-600 text-white hover:bg-blue-700'}`}
            >
              {loading ? <><ArrowPathIcon className="h-5 w-5 animate-spin" />回测运行中...</> : <><PlayIcon className="h-5 w-5" />开始回测</>}
            </button>

            {error && <div className="mt-4 p-3 bg-red-50 text-red-600 rounded-lg text-sm">{error}</div>}
          </div>
        </div>

        <div className="lg:col-span-2">
          {result ? (
            <div className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-white rounded-lg shadow p-4"><p className="text-sm text-slate-500 mb-1">总收益率</p><p className={`text-2xl font-bold ${result.metrics.total_return >= 0 ? 'text-green-600' : 'text-red-600'}`}>{formatPercent(result.metrics.total_return)}</p></div>
                <div className="bg-white rounded-lg shadow p-4"><p className="text-sm text-slate-500 mb-1">年化收益</p><p className={`text-2xl font-bold ${result.metrics.annual_return >= 0 ? 'text-green-600' : 'text-red-600'}`}>{formatPercent(result.metrics.annual_return)}</p></div>
                <div className="bg-white rounded-lg shadow p-4"><p className="text-sm text-slate-500 mb-1">夏普比率</p><p className="text-2xl font-bold text-slate-900">{result.metrics.sharpe_ratio.toFixed(2)}</p></div>
                <div className="bg-white rounded-lg shadow p-4"><p className="text-sm text-slate-500 mb-1">最大回撤</p><p className="text-2xl font-bold text-red-600">{formatPercent(result.metrics.max_drawdown)}</p></div>
              </div>

              {result.diagnostics && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
                  <div className="font-medium mb-1">回测诊断</div>
                  <div>买入笔数：{result.diagnostics.buy_trade_count ?? 0}</div>
                  <div>卖出笔数：{result.diagnostics.sell_trade_count ?? 0}</div>
                  {result.diagnostics.zero_trade_reason && <div>零交易原因：{result.diagnostics.zero_trade_reason}</div>}
                </div>
              )}

              <div className="bg-white rounded-lg shadow p-6">
                <h3 className="text-lg font-semibold text-slate-900 mb-4">详细指标</h3>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
                  <div><p className="text-sm text-slate-500">胜率</p><p className="text-xl font-semibold text-slate-900">{(result.metrics.win_rate * 100).toFixed(1)}%</p></div>
                  <div><p className="text-sm text-slate-500">盈亏比</p><p className="text-xl font-semibold text-slate-900">{result.metrics.profit_factor.toFixed(2)}</p></div>
                  <div><p className="text-sm text-slate-500">波动率</p><p className="text-xl font-semibold text-slate-900">{formatPercent(result.metrics.volatility)}</p></div>
                  <div><p className="text-sm text-slate-500">总交易次数</p><p className="text-xl font-semibold text-slate-900">{result.details?.trade_list?.length || 0} 次</p></div>
                  <div><p className="text-sm text-slate-500">初始资金</p><p className="text-xl font-semibold text-slate-900">{formatCurrency(result.summary?.initial_capital || 0)}</p></div>
                  <div><p className="text-sm text-slate-500">最终资金</p><p className={`text-xl font-semibold ${(result.metrics.final_capital ?? 0) >= (result.summary?.initial_capital ?? 0) ? 'text-green-600' : 'text-red-600'}`}>{formatCurrency(result.metrics.final_capital ?? result.summary?.final_capital ?? 0)}</p></div>
                </div>
              </div>

              {chartData.length > 0 && (
                <div className="space-y-6">
                  <PortfolioValueChart data={chartData} />
                  <DrawdownChart data={chartData} />
                  <ReturnsDistributionChart data={chartData} />
                </div>
              )}

              {result.details?.trade_list && result.details.trade_list.length > 0 && (
                <div className="bg-white rounded-lg shadow p-6">
                  <h3 className="text-lg font-semibold text-slate-900 mb-4">交易记录</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-200">
                          <th className="text-left py-2 text-slate-600">日期</th>
                          <th className="text-left py-2 text-slate-600">类型</th>
                          <th className="text-right py-2 text-slate-600">价格</th>
                          <th className="text-right py-2 text-slate-600">数量</th>
                          <th className="text-right py-2 text-slate-600">原因</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.details.trade_list.map((trade: any, index: number) => (
                          <tr key={index} className="border-b border-slate-100">
                            <td className="py-2 text-slate-900">{trade.timestamp?.slice(0, 10) || '-'}</td>
                            <td className="py-2"><span className={`px-2 py-1 rounded text-xs font-medium ${trade.direction === 'buy' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>{trade.direction === 'buy' ? '买入' : '卖出'}</span></td>
                            <td className="py-2 text-right text-slate-900">{trade.price.toFixed(2)}</td>
                            <td className="py-2 text-right text-slate-900">{trade.quantity}</td>
                            <td className="py-2 text-right text-slate-900">{trade.reason || '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-white rounded-lg shadow p-12 text-center text-slate-500">运行一次回测后，这里会显示结果</div>
          )}
        </div>
      </div>
    </div>
  )
}
