import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, AreaChart, Area, BarChart, Bar } from 'recharts'

interface ChartProps {
  data: any[]
  dataKey: string
  title: string
  color?: string
  type?: 'line' | 'area' | 'bar'
}

function formatChineseUnit(value: number) {
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toFixed(2)
}

export function PerformanceChart({ data, dataKey, title, color = '#3b82f6', type = 'line' }: ChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="bg-slate-50 rounded-lg p-8 text-center">
        <p className="text-slate-500">暂无数据</p>
      </div>
    )
  }

  const formatValue = (value: number) => {
    return formatChineseUnit(value)
  }

  const formatPercent = (value: number) => {
    return `${(value * 100).toFixed(2)}%`
  }

  const formatDate = (date: string) => {
    try {
      const d = new Date(date)
      return `${d.getMonth() + 1}/${d.getDate()}`
    } catch {
      return date
    }
  }

  const chartData = data.map((item) => ({
    ...item,
    date: formatDate(item.date),
  }))

  const isPercentage = dataKey.includes('return') || dataKey.includes('rate') || dataKey.includes('drawdown')
  const formatter = isPercentage ? formatPercent : formatValue

  if (type === 'area') {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-4">{title}</h3>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} />
            <YAxis stroke="#94a3b8" fontSize={12} tickFormatter={formatter} />
            <Tooltip
              formatter={(value: any) => [formatter(value), title]}
              contentStyle={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px' }}
            />
            <Area type="monotone" dataKey={dataKey} stroke={color} fillOpacity={1} fill="url(#colorValue)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    )
  }

  if (type === 'bar') {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-4">{title}</h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} />
            <YAxis stroke="#94a3b8" fontSize={12} tickFormatter={formatter} />
            <Tooltip
              formatter={(value: any) => [formatter(value), title]}
              contentStyle={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px' }}
            />
            <Bar dataKey={dataKey} fill={color} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-slate-900 mb-4">{title}</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} />
          <YAxis stroke="#94a3b8" fontSize={12} tickFormatter={formatter} />
          <Tooltip
            formatter={(value: any) => [formatter(value), title]}
            contentStyle={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px' }}
          />
          <Legend />
          <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={false} name={title} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function PortfolioValueChart({ data }: { data: any[] }) {
  if (!data || data.length === 0) {
    return (
      <div className="bg-slate-50 rounded-lg p-8 text-center">
        <p className="text-slate-500">暂无数据</p>
      </div>
    )
  }

  const formatDate = (date: string) => {
    try {
      const d = new Date(date)
      return `${d.getMonth() + 1}/${d.getDate()}`
    } catch {
      return date
    }
  }

  const chartData = data.map((item) => ({
    date: formatDate(item.date),
    组合价值: item.value,
    现金: item.cash,
    持仓价值: item.position * item.price,
  }))

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-slate-900 mb-4">组合价值曲线</h3>
      <ResponsiveContainer width="100%" height={350}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} />
          <YAxis
            stroke="#94a3b8"
            fontSize={12}
            tickFormatter={(value) => formatChineseUnit(Number(value))}
          />
          <Tooltip
            formatter={(value: any) => [`¥${value.toLocaleString()}`, '']}
            labelFormatter={(label) => `日期: ${label}`}
            contentStyle={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px' }}
          />
          <Legend />
          <Area
            type="monotone"
            dataKey="组合价值"
            stroke="#3b82f6"
            fillOpacity={1}
            fill="url(#colorValue)"
            strokeWidth={2}
          />
          <Line type="monotone" dataKey="现金" stroke="#10b981" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="持仓价值" stroke="#f59e0b" strokeWidth={2} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

export function DrawdownChart({ data }: { data: any[] }) {
  if (!data || data.length === 0) {
    return (
      <div className="bg-slate-50 rounded-lg p-8 text-center">
        <p className="text-slate-500">暂无数据</p>
      </div>
    )
  }

  const formatDate = (date: string) => {
    try {
      const d = new Date(date)
      return `${d.getMonth() + 1}/${d.getDate()}`
    } catch {
      return date
    }
  }

  // 计算回撤
  let peak = data[0].value
  const chartData = data.map((item) => {
    if (item.value > peak) peak = item.value
    const drawdown = (item.value - peak) / peak
    return {
      date: formatDate(item.date),
      回撤: drawdown,
    }
  })

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-slate-900 mb-4">回撤曲线</h3>
      <ResponsiveContainer width="100%" height={250}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="colorDrawdown" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} />
          <YAxis
            stroke="#94a3b8"
            fontSize={12}
            tickFormatter={(value) => `${(value * 100).toFixed(1)}%`}
          />
          <Tooltip
            formatter={(value: any) => [`${(value * 100).toFixed(2)}%`, '回撤']}
            contentStyle={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px' }}
          />
          <Area
            type="monotone"
            dataKey="回撤"
            stroke="#ef4444"
            fillOpacity={1}
            fill="url(#colorDrawdown)"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ReturnsDistributionChart({ data }: { data: any[] }) {
  if (!data || data.length === 0) {
    return (
      <div className="bg-slate-50 rounded-lg p-8 text-center">
        <p className="text-slate-500">暂无数据</p>
      </div>
    )
  }

  // 计算每日收益率
  const returns = []
  for (let i = 1; i < data.length; i++) {
    const dailyReturn = (data[i].value - data[i - 1].value) / data[i - 1].value
    returns.push(dailyReturn)
  }

  // 分组统计
  const bins = [
    { range: '<-5%', count: 0 },
    { range: '-5%~-3%', count: 0 },
    { range: '-3%~-1%', count: 0 },
    { range: '-1%~0%', count: 0 },
    { range: '0%~1%', count: 0 },
    { range: '1%~3%', count: 0 },
    { range: '3%~5%', count: 0 },
    { range: '>5%', count: 0 },
  ]

  returns.forEach((r) => {
    if (r < -0.05) bins[0].count++
    else if (r < -0.03) bins[1].count++
    else if (r < -0.01) bins[2].count++
    else if (r < 0) bins[3].count++
    else if (r < 0.01) bins[4].count++
    else if (r < 0.03) bins[5].count++
    else if (r < 0.05) bins[6].count++
    else bins[7].count++
  })

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-slate-900 mb-4">收益分布</h3>
      <ResponsiveContainer width="100%" height={250}>
        <BarChart data={bins}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="range" stroke="#94a3b8" fontSize={11} />
          <YAxis stroke="#94a3b8" fontSize={12} />
          <Tooltip
            formatter={(value: any) => [`${value} 天`, '']}
            contentStyle={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px' }}
          />
          <Bar dataKey="count" fill="#8b5cf6" radius={[4, 4, 0, 0]} name="天数" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
