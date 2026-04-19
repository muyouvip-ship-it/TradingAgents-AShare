import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeftIcon, PlusIcon, TrashIcon, ChartBarIcon } from '@heroicons/react/24/outline'

interface Indicator {
  id: string
  name: string
  display_name: string
  parameters: Record<string, any>
}

interface Rule {
  id: string
  name: string
  condition: string
  parameters: Record<string, any>
}

interface StrategyForm {
  name: string
  strategy_type: string
  parent_id: string | null
  description: string
  indicators: Indicator[]
  entry_rules: Rule[]
  exit_rules: Rule[]
  position_rules: {
    initial: number
    max_position: number
    add_on_profit?: number
    reduce_on_loss?: number
    max_single_position: number
  }
  risk_rules: {
    stop_loss: number
    take_profit?: number
    trailing_stop?: number
    max_positions: number
    max_daily_loss: number
  }
  parameters: Record<string, any>
}

const API_BASE_URL = ''

const indicatorTemplates = [
  { name: 'MACD', display_name: 'MACD (指数平滑异同移动平均线)', parameters: { fast: 12, slow: 26, signal: 9 } },
  { name: 'MA', display_name: 'MA (移动平均线)', parameters: { period: 20, type: 'SMA' } },
  { name: 'RSI', display_name: 'RSI (相对强弱指数)', parameters: { period: 14 } },
  { name: 'BOLL', display_name: 'BOLL (布林带)', parameters: { period: 20, std: 2 } },
  { name: 'VOL_MA', display_name: 'VOL_MA (成交量均线)', parameters: { period: 5 } },
  { name: 'ATR', display_name: 'ATR (平均真实波幅)', parameters: { period: 14 } },
]

export default function StrategyCreate() {
  const navigate = useNavigate()
  const { id } = useParams()
  const isEdit = Boolean(id)

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<StrategyForm>({
    name: '',
    strategy_type: 'selection',
    parent_id: null,
    description: '',
    indicators: [],
    entry_rules: [],
    exit_rules: [],
    position_rules: {
      initial: 0.3,
      max_position: 0.8,
      max_single_position: 0.3,
    },
    risk_rules: {
      stop_loss: 0.05,
      take_profit: 0.15,
      trailing_stop: 0.03,
      max_positions: 10,
      max_daily_loss: 0.03,
    },
    parameters: {},
  })

  useEffect(() => {
    if (isEdit && id) {
      loadStrategy(id)
    }
  }, [id, isEdit])

  const loadStrategy = async (strategyId: string) => {
    try {
      setLoading(true)
      const response = await fetch(`${API_BASE_URL}/api/v1/strategies/${strategyId}`)
      if (!response.ok) throw new Error('Failed to fetch')
      const data = await response.json()
      
      setForm({
        name: data.name,
        strategy_type: data.strategy_type,
        parent_id: data.parent_id,
        description: data.description || '',
        indicators: data.indicators || [],
        entry_rules: data.entry_rules || [],
        exit_rules: data.exit_rules || [],
        position_rules: data.position_rules || form.position_rules,
        risk_rules: data.risk_rules || form.risk_rules,
        parameters: data.parameters || {},
      })
    } catch (err) {
      console.error('Failed to load strategy:', err)
      alert('加载策略失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent, saveAsDraft: boolean = false) => {
    e.preventDefault()
    
    if (!form.name.trim()) {
      alert('请输入策略名称')
      return
    }

    try {
      setSaving(true)
      
      const url = isEdit 
        ? `${API_BASE_URL}/api/v1/strategies/${id}`
        : `${API_BASE_URL}/api/v1/strategies`
      
      const method = isEdit ? 'PUT' : 'POST'
      
      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })

      if (!response.ok) throw new Error('Failed to save')

      const data = await response.json()
      
      if (saveAsDraft) {
        alert('策略已保存为草稿')
      } else {
        // 激活策略
        await fetch(`${API_BASE_URL}/api/v1/strategies/${data.id}/activate`, {
          method: 'POST',
        })
        alert('策略已保存并激活')
      }
      
      navigate('/strategies')
    } catch (err) {
      console.error('Failed to save strategy:', err)
      alert('保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  const addIndicator = () => {
    const template = indicatorTemplates[0]
    const newIndicator: Indicator = {
      id: Date.now().toString(),
      name: template.name,
      display_name: template.display_name,
      parameters: { ...template.parameters },
    }
    setForm({ ...form, indicators: [...form.indicators, newIndicator] })
  }

  const removeIndicator = (id: string) => {
    setForm({ ...form, indicators: form.indicators.filter(i => i.id !== id) })
  }

  const updateIndicator = (id: string, updates: Partial<Indicator>) => {
    setForm({
      ...form,
      indicators: form.indicators.map(i => i.id === id ? { ...i, ...updates } : i),
    })
  }

  const addRule = (type: 'entry' | 'exit') => {
    const newRule: Rule = {
      id: Date.now().toString(),
      name: '新规则',
      condition: '',
      parameters: {},
    }
    const key = type === 'entry' ? 'entry_rules' : 'exit_rules'
    setForm({ ...form, [key]: [...form[key], newRule] })
  }

  const removeRule = (type: 'entry' | 'exit', id: string) => {
    const key = type === 'entry' ? 'entry_rules' : 'exit_rules'
    setForm({ ...form, [key]: form[key].filter(r => r.id !== id) })
  }

  const updateRule = (type: 'entry' | 'exit', id: string, updates: Partial<Rule>) => {
    const key = type === 'entry' ? 'entry_rules' : 'exit_rules'
    setForm({
      ...form,
      [key]: form[key].map(r => r.id === id ? { ...r, ...updates } : r),
    })
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <p className="text-slate-600">加载中...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      {/* 页面标题 */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/strategies')}
            className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <ArrowLeftIcon className="h-5 w-5 text-slate-600" />
          </button>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">
              {isEdit ? '编辑策略' : '创建新策略'}
            </h1>
            <p className="text-slate-600 mt-1">配置策略参数、指标和规则</p>
          </div>
        </div>
      </div>

      <form onSubmit={(e) => handleSubmit(e, false)}>
        {/* 基本信息 */}
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-slate-900 mb-4">基本信息</h2>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                策略名称 <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="例如：波段跟踪策略V1"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                策略类型 <span className="text-red-500">*</span>
              </label>
              <select
                value={form.strategy_type}
                onChange={(e) => setForm({ ...form, strategy_type: e.target.value })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="selection">选股策略</option>
                <option value="trading">交易策略</option>
                <option value="risk">风控策略</option>
                <option value="portfolio">组合策略</option>
              </select>
            </div>

            <div className="col-span-2">
              <label className="block text-sm font-medium text-slate-700 mb-1">
                策略描述
              </label>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                rows={3}
                placeholder="描述策略的主要特点和应用场景..."
              />
            </div>
          </div>
        </div>

        {/* 指标配置 */}
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-slate-900">📊 指标配置</h2>
            <button
              type="button"
              onClick={addIndicator}
              className="flex items-center px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              <PlusIcon className="h-4 w-4 mr-1" />
              添加指标
            </button>
          </div>

          {form.indicators.length === 0 ? (
            <div className="text-center py-8 text-slate-500 bg-slate-50 rounded-lg">
              点击"添加指标"开始配置
            </div>
          ) : (
            <div className="space-y-4">
              {form.indicators.map((indicator, index) => (
                <div key={indicator.id} className="border border-slate-200 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="w-6 h-6 rounded-full bg-blue-100 text-blue-700 text-sm flex items-center justify-center">
                        {index + 1}
                      </span>
                      <select
                        value={indicator.name}
                        onChange={(e) => {
                          const template = indicatorTemplates.find(t => t.name === e.target.value)
                          if (template) {
                            updateIndicator(indicator.id, {
                              name: template.name,
                              display_name: template.display_name,
                              parameters: { ...template.parameters },
                            })
                          }
                        }}
                        className="px-3 py-1.5 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500"
                      >
                        {indicatorTemplates.map(t => (
                          <option key={t.name} value={t.name}>{t.display_name}</option>
                        ))}
                      </select>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeIndicator(indicator.id)}
                      className="text-red-500 hover:text-red-700"
                    >
                      <TrashIcon className="h-4 w-4" />
                    </button>
                  </div>

                  {/* 指标参数 */}
                  <div className="grid grid-cols-3 gap-3">
                    {Object.entries(indicator.parameters).map(([key, value]) => (
                      <div key={key}>
                        <label className="block text-xs text-slate-600 mb-1">{key}</label>
                        <input
                          type="number"
                          value={value as number}
                          onChange={(e) => updateIndicator(indicator.id, {
                            parameters: { ...indicator.parameters, [key]: parseFloat(e.target.value) },
                          })}
                          className="w-full px-2 py-1.5 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 入场规则 */}
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-slate-900">🎯 入场条件 (全部满足才买入)</h2>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => addRule('entry')}
                className="flex items-center px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                <PlusIcon className="h-4 w-4 mr-1" />
                添加规则
              </button>
              <button
                type="button"
                onClick={() => {
                  addRule('entry')
                  updateRule('entry', form.entry_rules[form.entry_rules.length - 1].id, {
                    name: '均线金叉',
                    condition: 'cross_above(ma5, ma20)'
                  })
                }}
                className="flex items-center px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
              >
                <ChartBarIcon className="h-4 w-4 mr-1" />
                均线金叉模板
              </button>
            </div>
          </div>

          {form.entry_rules.length === 0 ? (
            <div className="text-center py-8 text-slate-500 bg-slate-50 rounded-lg">
              点击"添加规则"配置入场条件
            </div>
          ) : (
            <div className="space-y-3">
              {form.entry_rules.map((rule, index) => (
                <div key={rule.id} className="flex items-start gap-3 border border-slate-200 rounded-lg p-3">
                  <span className="w-6 h-6 rounded-full bg-green-100 text-green-700 text-sm flex items-center justify-center flex-shrink-0 mt-1">
                    {index + 1}
                  </span>
                  <div className="flex-1">
                    <input
                      type="text"
                      value={rule.name}
                      onChange={(e) => updateRule('entry', rule.id, { name: e.target.value })}
                      placeholder="规则名称"
                      className="w-full px-2 py-1.5 border border-slate-300 rounded text-sm mb-2 focus:ring-2 focus:ring-blue-500"
                    />
                    <input
                      type="text"
                      value={rule.condition}
                      onChange={(e) => updateRule('entry', rule.id, { condition: e.target.value })}
                      placeholder="条件表达式，如: macd > signal AND volume > volume_ma * 1.5"
                      className="w-full px-2 py-1.5 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeRule('entry', rule.id)}
                    className="text-red-500 hover:text-red-700 mt-1"
                  >
                    <TrashIcon className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 出场规则 */}
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-slate-900">🚪 出场条件 (满足任一则卖出)</h2>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => addRule('exit')}
                className="flex items-center px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                <PlusIcon className="h-4 w-4 mr-1" />
                添加规则
              </button>
              <button
                type="button"
                onClick={() => {
                  addRule('exit')
                  updateRule('exit', form.exit_rules[form.exit_rules.length - 1].id, {
                    name: '均线死叉',
                    condition: 'cross_below(ma5, ma20)'
                  })
                }}
                className="flex items-center px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                <ChartBarIcon className="h-4 w-4 mr-1" />
                均线死叉模板
              </button>
            </div>
          </div>

          {form.exit_rules.length === 0 ? (
            <div className="text-center py-8 text-slate-500 bg-slate-50 rounded-lg">
              点击"添加规则"配置出场条件
            </div>
          ) : (
            <div className="space-y-3">
              {form.exit_rules.map((rule, index) => (
                <div key={rule.id} className="flex items-start gap-3 border border-slate-200 rounded-lg p-3">
                  <span className="w-6 h-6 rounded-full bg-red-100 text-red-700 text-sm flex items-center justify-center flex-shrink-0 mt-1">
                    {index + 1}
                  </span>
                  <div className="flex-1">
                    <input
                      type="text"
                      value={rule.name}
                      onChange={(e) => updateRule('exit', rule.id, { name: e.target.value })}
                      placeholder="规则名称"
                      className="w-full px-2 py-1.5 border border-slate-300 rounded text-sm mb-2 focus:ring-2 focus:ring-blue-500"
                    />
                    <input
                      type="text"
                      value={rule.condition}
                      onChange={(e) => updateRule('exit', rule.id, { condition: e.target.value })}
                      placeholder="条件表达式"
                      className="w-full px-2 py-1.5 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeRule('exit', rule.id)}
                    className="text-red-500 hover:text-red-700 mt-1"
                  >
                    <TrashIcon className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 仓位管理 */}
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-slate-900 mb-4">⚖️ 仓位管理</h2>
          
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm text-slate-600 mb-1">初始仓位</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="1"
                value={form.position_rules.initial}
                onChange={(e) => setForm({
                  ...form,
                  position_rules: { ...form.position_rules, initial: parseFloat(e.target.value) },
                })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-slate-500 mt-1">{(form.position_rules.initial * 100).toFixed(0)}%</p>
            </div>

            <div>
              <label className="block text-sm text-slate-600 mb-1">最大仓位</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="1"
                value={form.position_rules.max_position}
                onChange={(e) => setForm({
                  ...form,
                  position_rules: { ...form.position_rules, max_position: parseFloat(e.target.value) },
                })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-slate-500 mt-1">{(form.position_rules.max_position * 100).toFixed(0)}%</p>
            </div>

            <div>
              <label className="block text-sm text-slate-600 mb-1">单股最大仓位</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="1"
                value={form.position_rules.max_single_position}
                onChange={(e) => setForm({
                  ...form,
                  position_rules: { ...form.position_rules, max_single_position: parseFloat(e.target.value) },
                })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-slate-500 mt-1">{(form.position_rules.max_single_position * 100).toFixed(0)}%</p>
            </div>
          </div>
        </div>

        {/* 风控规则 */}
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-slate-900 mb-4">🛡️ 风控规则</h2>
          
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm text-slate-600 mb-1">止损比例</label>
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={form.risk_rules.stop_loss}
                onChange={(e) => setForm({
                  ...form,
                  risk_rules: { ...form.risk_rules, stop_loss: parseFloat(e.target.value) },
                })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-slate-500 mt-1">{(form.risk_rules.stop_loss * 100).toFixed(1)}%</p>
            </div>

            <div>
              <label className="block text-sm text-slate-600 mb-1">止盈比例</label>
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={form.risk_rules.take_profit || ''}
                onChange={(e) => setForm({
                  ...form,
                  risk_rules: { ...form.risk_rules, take_profit: parseFloat(e.target.value) },
                })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-slate-500 mt-1">{form.risk_rules.take_profit ? (form.risk_rules.take_profit * 100).toFixed(1) + '%' : '未设置'}</p>
            </div>

            <div>
              <label className="block text-sm text-slate-600 mb-1">移动止损</label>
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={form.risk_rules.trailing_stop || ''}
                onChange={(e) => setForm({
                  ...form,
                  risk_rules: { ...form.risk_rules, trailing_stop: parseFloat(e.target.value) },
                })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-slate-500 mt-1">{form.risk_rules.trailing_stop ? (form.risk_rules.trailing_stop * 100).toFixed(1) + '%' : '未设置'}</p>
            </div>

            <div>
              <label className="block text-sm text-slate-600 mb-1">最大持仓数</label>
              <input
                type="number"
                min="1"
                max="100"
                value={form.risk_rules.max_positions}
                onChange={(e) => setForm({
                  ...form,
                  risk_rules: { ...form.risk_rules, max_positions: parseInt(e.target.value) },
                })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm text-slate-600 mb-1">单日最大亏损</label>
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={form.risk_rules.max_daily_loss}
                onChange={(e) => setForm({
                  ...form,
                  risk_rules: { ...form.risk_rules, max_daily_loss: parseFloat(e.target.value) },
                })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-slate-500 mt-1">{(form.risk_rules.max_daily_loss * 100).toFixed(1)}%</p>
            </div>
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={() => navigate('/strategies')}
            className="px-4 py-2 border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
          >
            取消
          </button>
          <button
            type="button"
            onClick={(e) => handleSubmit(e, true)}
            disabled={saving}
            className="px-4 py-2 border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
          >
            保存为草稿
          </button>
          <button
            type="submit"
            disabled={saving}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {saving ? '保存中...' : '保存并激活'}
          </button>
        </div>
      </form>
    </div>
  )
}
