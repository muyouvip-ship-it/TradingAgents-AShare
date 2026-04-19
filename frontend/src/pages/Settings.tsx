import { useState, useEffect, useMemo, useRef } from 'react'
import { Save, Key, Database, Loader2, Trash2, Link2, Copy, Plus, CheckCircle2, Mail, Flame, Webhook, Calendar, Download, BarChart3, LineChart, TrendingUp, FileText, DollarSign } from 'lucide-react'
import { api } from '@/services/api'
import { useAuthStore } from '@/stores/authStore'
import type { RuntimeWarmupResult, UserToken } from '@/types'

type ProviderPreset = {
    id: string
    label: string
    provider: string
    baseUrl: string
    protocol: string
    editableBaseUrl?: boolean
}

const PROVIDER_PRESETS: ProviderPreset[] = [
    { id: 'openai', label: 'OpenAI', provider: 'openai', baseUrl: 'https://api.openai.com/v1', protocol: 'OpenAI' },
    { id: 'anthropic', label: 'Anthropic', provider: 'anthropic', baseUrl: '', protocol: 'Anthropic' },
    { id: 'google', label: 'Google Gemini', provider: 'google', baseUrl: '', protocol: 'Google' },
    { id: 'dashscope', label: '阿里云百炼（DashScope）', provider: 'openai', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', protocol: 'OpenAI 兼容' },
    { id: 'deepseek', label: 'DeepSeek', provider: 'openai', baseUrl: 'https://api.deepseek.com/v1', protocol: 'OpenAI 兼容' },
    { id: 'moonshot', label: 'Moonshot AI（Kimi）', provider: 'openai', baseUrl: 'https://api.moonshot.cn/v1', protocol: 'OpenAI 兼容' },
    { id: 'zhipu', label: '智谱 AI', provider: 'openai', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', protocol: 'OpenAI 兼容' },
    { id: 'siliconflow', label: '硅基流动', provider: 'openai', baseUrl: 'https://api.siliconflow.cn/v1', protocol: 'OpenAI 兼容' },
    { id: 'custom-openai', label: '自定义 OpenAI 兼容', provider: 'openai', baseUrl: '', protocol: 'OpenAI 兼容', editableBaseUrl: true },
]

function inferPreset(llmProvider: string, backendUrl: string): string {
    const normalizedProvider = (llmProvider || '').toLowerCase()
    const normalizedUrl = (backendUrl || '').replace(/\/$/, '')
    const matched = PROVIDER_PRESETS.find((preset) => {
        if (preset.provider !== normalizedProvider) return false
        if (!preset.baseUrl && preset.id !== 'custom-openai') return true
        return preset.baseUrl.replace(/\/$/, '') === normalizedUrl
    })
    if (matched) return matched.id
    if (normalizedProvider === 'openai') return 'custom-openai'
    return normalizedProvider || 'openai'
}

export default function Settings() {
    const { user } = useAuthStore()
    const [defaultAnalysts, setDefaultAnalysts] = useState(['market', 'social', 'news', 'fundamentals', 'macro', 'smart_money', 'volume_price'])
    const [customPrompt, setCustomPrompt] = useState('')
    const [llmApiKey, setLlmApiKey] = useState('')
    const [hasStoredApiKey, setHasStoredApiKey] = useState(false)
    const [wecomWebhook, setWecomWebhook] = useState('')
    const [hasStoredWebhook, setHasStoredWebhook] = useState(false)
    const [storedWebhookDisplay, setStoredWebhookDisplay] = useState('')

    const [providerPreset, setProviderPreset] = useState('openai')
    const [customBaseUrl, setCustomBaseUrl] = useState('')
    const [deepThinkLlm, setDeepThinkLlm] = useState('')
    const [quickThinkLlm, setQuickThinkLlm] = useState('')
    const [maxDebateRounds, setMaxDebateRounds] = useState(1)
    const [maxRiskRounds, setMaxRiskRounds] = useState(1)
    const [serverFallbackEnabled, setServerFallbackEnabled] = useState(true)
    const [emailReportEnabled, setEmailReportEnabled] = useState(true)
    const [wecomReportEnabled, setWecomReportEnabled] = useState(true)
    const [configLoading, setConfigLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [saveAllSaving, setSaveAllSaving] = useState(false)
    const [warmingUp, setWarmingUp] = useState(false)
    const [saved, setSaved] = useState(false)
    const [saveMessage, setSaveMessage] = useState('设置已保存')
    const [configError, setConfigError] = useState<string | null>(null)
    const [warmupResults, setWarmupResults] = useState<RuntimeWarmupResult[]>([])
    const [warmupError, setWarmupError] = useState<string | null>(null)
    const [wecomWarmingUp, setWecomWarmingUp] = useState(false)
    const [wecomWarmupMessage, setWecomWarmupMessage] = useState<string | null>(null)
    const [wecomWarmupError, setWecomWarmupError] = useState<string | null>(null)

    // API Token states
    const [tokens, setTokens] = useState<UserToken[]>([])
    const [tokensLoading, setTokensLoading] = useState(false)
    const [newTokenName, setNewTokenName] = useState('')
    const [isCreatingToken, setIsCreatingToken] = useState(false)
    const [copiedTokenId, setCopiedTokenId] = useState<string | null>(null)
    const [newlyCreatedToken, setNewlyCreatedToken] = useState<string | null>(null)

    // 回测数据配置状态（简化版）
    const [dateRange, setDateRange] = useState({
        start: new Date(new Date().setFullYear(new Date().getFullYear() - 1)).toISOString().split('T')[0],
        end: new Date().toISOString().split('T')[0]
    })
    
    const [selectedDataTypes, setSelectedDataTypes] = useState<string[]>(['daily_kline'])
    const [dataSource, setDataSource] = useState('quantclass')  // 默认量化课堂
    const [autoUpdate, setAutoUpdate] = useState(true)  // 默认每日自动更新
    const [downloading, setDownloading] = useState(false)
    const [downloadProgress, setDownloadProgress] = useState(0)
    const [dataStats, setDataStats] = useState<any[]>([])  // 已下载数据统计
    const [dataTasks, setDataTasks] = useState<any[]>([])  // 下载任务列表
    const [loadingStats, setLoadingStats] = useState(false)
    const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)  // 轮询定时器（使用ref避免重新渲染）

    const selectedPreset = useMemo(
        () => PROVIDER_PRESETS.find((item) => item.id === providerPreset) || PROVIDER_PRESETS[0],
        [providerPreset],
    )

    const effectiveProvider = selectedPreset.provider
    const effectiveBaseUrl = selectedPreset.editableBaseUrl ? customBaseUrl.trim() : selectedPreset.baseUrl
    useEffect(() => {
        setWarmupResults([])
        setWarmupError(null)
    }, [providerPreset, customBaseUrl, deepThinkLlm, quickThinkLlm, llmApiKey])

    useEffect(() => {
        setWecomWarmupMessage(null)
        setWecomWarmupError(null)
    }, [wecomWebhook])

    useEffect(() => {
        try {
            const stored = localStorage.getItem('tradingagents-settings')
            if (stored) {
                const s = JSON.parse(stored) as Record<string, unknown> & {
                    defaultAnalysts?: string[]
                }
                if ('apiUrl' in s) {
                    delete s.apiUrl
                    localStorage.setItem('tradingagents-settings', JSON.stringify(s))
                }
                if (s.defaultAnalysts) setDefaultAnalysts(s.defaultAnalysts)
                if (typeof s.customPrompt === 'string') setCustomPrompt(s.customPrompt)
            }
        } catch {}
    }, [])

    useEffect(() => {
        setConfigLoading(true)
        setConfigError(null)
        api.getConfig()
            .then(cfg => {
                setProviderPreset(inferPreset(cfg.llm_provider, cfg.backend_url))
                setCustomBaseUrl(cfg.backend_url || '')
                setDeepThinkLlm(cfg.deep_think_llm)
                setQuickThinkLlm(cfg.quick_think_llm)
                setMaxDebateRounds(cfg.max_debate_rounds)
                setMaxRiskRounds(cfg.max_risk_discuss_rounds)
                setHasStoredApiKey(!!cfg.has_api_key)
                setHasStoredWebhook(!!cfg.has_wecom_webhook)
                setStoredWebhookDisplay(cfg.wecom_webhook_display || '')
                setServerFallbackEnabled(!!cfg.server_fallback_enabled)
                setEmailReportEnabled(cfg.email_report_enabled !== false)
                setWecomReportEnabled(cfg.wecom_report_enabled !== false)
                if (Array.isArray(cfg.default_analysts) && cfg.default_analysts.length > 0) {
                    setDefaultAnalysts(cfg.default_analysts)
                }
            })
            .catch(err => {
                setConfigError(err instanceof Error ? err.message : '无法连接到后端')
            })
            .finally(() => setConfigLoading(false))

        // Fetch tokens
        fetchTokens()
        
        // 加载回测数据统计和配置
        loadBacktestDataInfo()
        
        // 清理函数：组件卸载时停止轮询
        return () => {
            if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current)
            }
        }
    }, [])

    const fetchTokens = async () => {
        setTokensLoading(true)
        try {
            const data = await api.getTokens()
            setTokens(data)
        } catch (err) {
            console.error('Failed to fetch tokens:', err)
        } finally {
            setTokensLoading(false)
        }
    }

    // 加载回测数据信息
    const loadBacktestDataInfo = async () => {
        setLoadingStats(true)
        try {
            // 调用实际API获取数据统计（使用api服务自动添加认证token）
            const statsResponse = await api.request<{stats?: any[], total?: number}>('/v1/backtest-data/stats')
            // API返回的是 {stats: [...], total: ...} 格式
            if (statsResponse && Array.isArray(statsResponse.stats)) {
                setDataStats(statsResponse.stats)
            } else if (Array.isArray(statsResponse)) {
                // 兼容直接返回数组的情况
                setDataStats(statsResponse)
            } else {
                console.warn('stats API返回数据格式异常:', statsResponse)
                setDataStats([])
            }
            
            // 调用实际API获取任务列表
            const tasksResponse = await api.request<{tasks?: any[], total?: number}>('/v1/backtest-data/tasks')
            // API返回的是 {tasks: [...], total: ...} 格式
            if (tasksResponse && Array.isArray(tasksResponse.tasks)) {
                setDataTasks(tasksResponse.tasks)
            } else if (Array.isArray(tasksResponse)) {
                // 兼容直接返回数组的情况
                setDataTasks(tasksResponse)
            } else {
                console.warn('tasks API返回数据格式异常:', tasksResponse)
                setDataTasks([])
            }
        } catch (err) {
            console.error('加载回测数据信息失败:', err)
            // 发生错误时设置为空数组
            setDataStats([])
            setDataTasks([])
        } finally {
            setLoadingStats(false)
        }
    }

    // 下载回测数据
    const handleDownloadData = async () => {
        if (selectedDataTypes.length === 0) {
            alert('请选择至少一种数据类型')
            return
        }
        
        setDownloading(true)
        setDownloadProgress(0)
        
        try {
            // 调用实际API批量下载（使用api服务自动添加认证token）
            // 默认下载全部股票（不传symbols参数）
            const result = await api.request<{created_tasks?: number}>('/v1/backtest-data/batch-download', {
                method: 'POST',
                body: JSON.stringify({
                    data_types: selectedDataTypes,
                    date_range_start: dateRange.start,
                    date_range_end: dateRange.end,
                    data_source: dataSource
                })
            })
            console.log('下载任务创建成功:', result)
            
            // 显示成功消息
            alert(`成功创建 ${result.created_tasks || selectedDataTypes.length} 个下载任务`)
            
            // 重新加载数据
            loadBacktestDataInfo()
            
            // 启动任务状态轮询
            startTaskPolling()
            
        } catch (err) {
            console.error('下载数据失败:', err)
            alert(err instanceof Error ? err.message : '下载数据失败')
        } finally {
            setDownloading(false)
            setDownloadProgress(100)
        }
    }

    // 启动任务状态轮询
    const startTaskPolling = () => {
        // 清除已有的定时器
        if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current)
        }
        
        // 立即执行一次
        loadBacktestDataInfo()
        
        // 每2秒轮询一次任务状态
        const interval = setInterval(async () => {
            try {
                const tasksResponse = await api.request<{tasks?: any[], total?: number}>('/v1/backtest-data/tasks')
                // 处理API返回的数据格式
                const tasksData = tasksResponse && Array.isArray(tasksResponse.tasks) 
                    ? tasksResponse.tasks 
                    : Array.isArray(tasksResponse) 
                        ? tasksResponse 
                        : []
                
                if (tasksData.length > 0) {
                    setDataTasks(tasksData)
                    
                    // 检查是否所有任务都已完成
                    const allCompleted = tasksData.every(task => 
                        task.status === 'completed' || task.status === 'failed'
                    )
                    
                    if (allCompleted) {
                        // 所有任务完成，停止轮询并刷新统计数据
                        clearInterval(interval)
                        pollingIntervalRef.current = null
                        loadBacktestDataInfo()
                    }
                }
            } catch (err) {
                console.error('轮询任务状态失败:', err)
            }
        }, 2000)
        
        pollingIntervalRef.current = interval
    }

    // 切换数据类型选择
    // 数据源兼容性映射
    const DATA_SOURCE_COMPATIBILITY: Record<string, string[]> = {
        'daily_kline': ['quantclass', 'akshare', 'baostock', 'tushare', 'eastmoney'],
        'minute_kline': ['akshare'],  // 量化课堂不支持1分钟K线
        'index_data': ['quantclass', 'akshare', 'baostock', 'tushare', 'eastmoney'],
        'chip_data': ['quantclass'],  // 只有量化课堂支持
        'financial_data': ['quantclass'],  // 只有量化课堂支持
        'research_reports': ['eastmoney']  // 只有东方财富支持
    }

    // 数据源名称映射
    const DATA_SOURCE_NAMES: Record<string, string> = {
        'quantclass': '量化课堂',
        'akshare': 'AKShare',
        'baostock': 'Baostock',
        'tushare': 'Tushare',
        'eastmoney': '东方财富'
    }

    const toggleDataType = (type: string) => {
        const newSelectedTypes = selectedDataTypes.includes(type) 
            ? selectedDataTypes.filter(t => t !== type) 
            : [...selectedDataTypes, type]
        
        setSelectedDataTypes(newSelectedTypes)
        
        // 检查数据源兼容性
        const compatibleSources = DATA_SOURCE_COMPATIBILITY[type] || []
        if (compatibleSources.length > 0 && !compatibleSources.includes(dataSource)) {
            // 当前数据源不支持该数据类型，自动切换
            const newSource = compatibleSources[0]
            setDataSource(newSource)
            alert(`提示：${getDataTypeName(type)}不支持${DATA_SOURCE_NAMES[dataSource]}，已自动切换到${DATA_SOURCE_NAMES[newSource]}`)
        }
    }

    // 获取数据类型显示名称
    const getDataTypeName = (type: string) => {
        const names: Record<string, string> = {
            'daily_kline': '股票日K线',
            'minute_kline': '股票1分钟K线',
            'index_data': '指数数据',
            'chip_data': '筹码数据',
            'financial_data': '财务数据',
            'research_reports': '研报数据'
        }
        return names[type] || type
    }

    // 获取数据类型图标
    const getDataTypeIcon = (type: string) => {
        const icons: Record<string, any> = {
            'daily_kline': BarChart3,
            'minute_kline': LineChart,
            'index_data': TrendingUp,
            'chip_data': Database,
            'financial_data': DollarSign,
            'research_reports': FileText
        }
        return icons[type] || BarChart3
    }

    const handleCreateToken = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!newTokenName.trim()) return
        setIsCreatingToken(true)
        try {
            const created = await api.createToken({ name: newTokenName.trim() })
            setNewTokenName('')
            setNewlyCreatedToken(created.token || null)
            await fetchTokens()
        } catch (err) {
            alert(err instanceof Error ? err.message : '创建 Token 失败')
        } finally {
            setIsCreatingToken(false)
        }
    }

    const handleDeleteToken = async (tokenId: string) => {
        if (!confirm('确定要吊销此 Token 吗？吊销后使用该 Token 的 API 请求将立即失效。')) return
        try {
            await api.deleteToken(tokenId)
            await fetchTokens()
        } catch (err) {
            alert(err instanceof Error ? err.message : '吊销 Token 失败')
        }
    }

    const copyToClipboard = (text: string, id: string) => {
        navigator.clipboard.writeText(text)
        setCopiedTokenId(id)
        setTimeout(() => setCopiedTokenId(null), 2000)
    }

    const persistLocalSettings = () => {
        localStorage.setItem('tradingagents-settings', JSON.stringify({
            defaultAnalysts,
            customPrompt,
        }))
        localStorage.setItem('ta-custom-prompt', customPrompt)
    }

    const buildRuntimeConfigPayload = (options?: { includeEmail?: boolean; includeWecom?: boolean }) => ({
        llm_provider: effectiveProvider,
        backend_url: effectiveBaseUrl || undefined,
        deep_think_llm: deepThinkLlm,
        quick_think_llm: quickThinkLlm,
        max_debate_rounds: maxDebateRounds,
        max_risk_discuss_rounds: maxRiskRounds,
        api_key: llmApiKey || undefined,
        ...(options?.includeWecom ? {
            wecom_webhook_url: wecomWebhook.trim() || undefined,
            wecom_report_enabled: wecomReportEnabled,
        } : {}),
        ...(options?.includeEmail ? { email_report_enabled: emailReportEnabled } : {}),
        default_analysts: defaultAnalysts,
    })

    const showSavedMessage = (message: string) => {
        setSaveMessage(message)
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
    }

    const submitConfig = async (options?: { forceWarmup?: boolean; successMessage?: string; includeEmail?: boolean; includeWecom?: boolean }) => {
        persistLocalSettings()
        const { forceWarmup = false, successMessage = '设置已保存', includeEmail = true, includeWecom = false } = options || {}
        const response = await api.updateConfig({
            ...buildRuntimeConfigPayload({ includeEmail, includeWecom }),
            warmup: true,
            force_warmup: forceWarmup,
        })
        setHasStoredApiKey(!!response.has_api_key)
        setHasStoredWebhook(!!response.current.has_wecom_webhook)
        setStoredWebhookDisplay(response.current.wecom_webhook_display || '')
        setWecomReportEnabled(response.current.wecom_report_enabled !== false)
        setLlmApiKey('')
        setWecomWebhook('')
        showSavedMessage(response.warmup?.message || successMessage)
        return response
    }

    const handleSaveAll = async () => {
        setSaveAllSaving(true)
        try {
            // 保存基础配置
            await submitConfig({ includeEmail: true, includeWecom: true, successMessage: '全部设置已保存' })
            
            // 保存回测数据配置
            await api.request<void>('/v1/backtest-data/configs', {
                method: 'POST',
                body: JSON.stringify({
                    data_types: selectedDataTypes,
                    date_range_start: dateRange.start,
                    date_range_end: dateRange.end,
                    data_source: dataSource,
                    auto_update: autoUpdate
                })
            })
            
            showSavedMessage('全部设置已保存（包含回测数据配置）')
        } catch (err) {
            alert(err instanceof Error ? err.message : '保存全部设置失败')
        } finally {
            setSaveAllSaving(false)
        }
    }

    const handleWarmup = async () => {
        setWarmingUp(true)
        setWarmupError(null)
        setWarmupResults([])
        try {
            const response = await api.warmupConfig({
                ...buildRuntimeConfigPayload(),
                prompt: '你好',
            })
            setWarmupResults(response.results || [])
        } catch (err) {
            setWarmupError(err instanceof Error ? err.message : 'Warmup 触发失败')
        } finally {
            setWarmingUp(false)
        }
    }
    const handleClearApiKey = async () => {
        if (!hasStoredApiKey) return
        setSaving(true)
        try {
            const response = await api.updateConfig({ clear_api_key: true })
            setHasStoredApiKey(!!response.has_api_key)
            setLlmApiKey('')
            setSaved(true)
            setTimeout(() => setSaved(false), 2000)
        } catch (err) {
            alert(err instanceof Error ? err.message : '清除密钥失败')
        } finally {
            setSaving(false)
        }
    }

    const handleClearWebhook = async () => {
        if (!hasStoredWebhook) return
        setSaving(true)
        try {
            const response = await api.updateConfig({ clear_wecom_webhook: true })
            setHasStoredWebhook(!!response.current.has_wecom_webhook)
            setStoredWebhookDisplay(response.current.wecom_webhook_display || '')
            setWecomWebhook('')
            setWecomWarmupMessage(null)
            setWecomWarmupError(null)
            showSavedMessage('企业微信机器人已清除')
        } catch (err) {
            alert(err instanceof Error ? err.message : '清除企业微信机器人失败')
        } finally {
            setSaving(false)
        }
    }

    const handleWecomWarmup = async () => {
        setWecomWarmingUp(true)
        setWecomWarmupMessage(null)
        setWecomWarmupError(null)
        try {
            const response = await api.warmupWecom({
                wecom_webhook_url: wecomWebhook.trim() || undefined,
            })
            setWecomWarmupMessage(
                response.webhook_display
                    ? `${response.message}，目标：${response.webhook_display}`
                    : response.message
            )
        } catch (err) {
            setWecomWarmupError(err instanceof Error ? err.message : 'Webhook 测试发送失败')
        } finally {
            setWecomWarmingUp(false)
        }
    }

    const toggleAnalyst = (analyst: string) => {
        setDefaultAnalysts(prev =>
            prev.includes(analyst) ? prev.filter(a => a !== analyst) : [...prev, analyst]
        )
    }

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">系统设置</h1>
                <p className="text-slate-500 dark:text-slate-400 mt-1">配置当前账户的分析参数与模型</p>
            </div>

            <div className="card space-y-4">
                <div className="flex items-center gap-2">
                    <Database className="w-5 h-5 text-purple-500" />
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">模型接入</h2>
                    {configLoading && <Loader2 className="ml-auto w-4 h-4 animate-spin text-slate-400" />}
                </div>

                {configError && (
                    <p className="text-sm text-amber-500">⚠ {configError}（显示本地默认值）</p>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            模型厂商
                        </label>
                        <select
                            value={providerPreset}
                            onChange={e => setProviderPreset(e.target.value)}
                            className="input w-full"
                            disabled={configLoading}
                        >
                            {PROVIDER_PRESETS.map((preset) => (
                                <option key={preset.id} value={preset.id}>{preset.label}</option>
                            ))}
                        </select>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            接入协议
                        </label>
                        <div className="input w-full flex items-center gap-2 bg-slate-50 dark:bg-slate-900/70 text-slate-600 dark:text-slate-300">
                            <Link2 className="w-4 h-4 text-slate-400" />
                            <span>{selectedPreset.protocol}</span>
                        </div>
                    </div>

                    {(selectedPreset.baseUrl || selectedPreset.editableBaseUrl) && (
                        <div className="md:col-span-2">
                            <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                                Base URL
                            </label>
                            <input
                                type="text"
                                value={selectedPreset.editableBaseUrl ? customBaseUrl : selectedPreset.baseUrl}
                                onChange={e => setCustomBaseUrl(e.target.value)}
                                className="input w-full"
                                disabled={configLoading || !selectedPreset.editableBaseUrl}
                                placeholder="https://your-openai-compatible-endpoint/v1"
                            />
                            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                {selectedPreset.editableBaseUrl
                                    ? '自定义 OpenAI 兼容服务需要自行填写 Base URL。'
                                    : '该厂商默认通过预设的 OpenAI 兼容地址接入，通常只需填写模型名和 API Key。'}
                            </p>
                        </div>
                    )}

                    <div>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            常规模型
                            <span className="ml-1 text-xs text-slate-400 font-normal">用于意图识别、JSON 提取等轻量任务</span>
                        </label>
                        <input
                            type="text"
                            value={quickThinkLlm}
                            onChange={e => setQuickThinkLlm(e.target.value)}
                            className="input w-full"
                            placeholder="例如：gpt-4.1-mini / deepseek-chat / moonshot-v1-8k"
                            disabled={configLoading}
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            推理模型
                            <span className="ml-1 text-xs text-slate-400 font-normal">用于深度分析、辩论等复杂任务</span>
                        </label>
                        <input
                            type="text"
                            value={deepThinkLlm}
                            onChange={e => setDeepThinkLlm(e.target.value)}
                            className="input w-full"
                            placeholder="例如：gpt-4.1 / deepseek-reasoner / kimi-k2-0905-preview"
                            disabled={configLoading}
                        />
                    </div>

                    <div className="md:col-span-2">
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            用户模型 Key
                        </label>
                        <div className="relative">
                            <Key className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                            <input
                                type="password"
                                value={llmApiKey}
                                onChange={e => setLlmApiKey(e.target.value)}
                                className="input w-full pl-10"
                                placeholder={hasStoredApiKey ? '已保存，留空则保持不变' : '输入你的模型 API Key'}
                                disabled={configLoading}
                            />
                        </div>
                        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
                            <div className="text-xs text-slate-500 dark:text-slate-400">
                                {serverFallbackEnabled
                                    ? '当前后端已开启公共模型回退：未填写个人 Key 时，可能仍会使用服务端默认模型配置。'
                                    : '当前后端已关闭公共模型回退：未填写个人 Key 时，将无法发起需要模型的分析任务。'}
                            </div>
                            {hasStoredApiKey && (
                                <button
                                    type="button"
                                    onClick={handleClearApiKey}
                                    disabled={saving || saveAllSaving}
                                    className="inline-flex items-center gap-1 text-xs text-rose-500 hover:text-rose-600 disabled:opacity-50"
                                >
                                    <Trash2 className="w-3.5 h-3.5" />
                                    清除密钥
                                </button>
                            )}
                        </div>
                        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                            保存模型配置后，系统会在后台自动测试连通性；也可以直接点击下方按钮，发送\u201c你好\u201d来验证模型是否正常响应。
                        </p>
                    </div>

                    <div className="md:col-span-2 rounded-2xl border border-slate-200/80 dark:border-slate-700/80 bg-slate-50/80 dark:bg-slate-900/40 p-4 space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                                <div className="text-sm font-medium text-slate-900 dark:text-slate-100">连通性测试</div>
                                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                    使用当前表单配置向模型发送“你好”，不会自动保存设置。
                                </p>
                            </div>
                            <button onClick={handleWarmup} disabled={saving || saveAllSaving || warmingUp || configLoading} className="btn-secondary inline-flex items-center gap-2">
                                {warmingUp ? <Loader2 className="w-4 h-4 animate-spin" /> : <Flame className="w-4 h-4" />}
                                {warmingUp ? '测试中...' : '测试连接'}
                            </button>
                        </div>

                        {warmupError && (
                            <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-600 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
                                {warmupError}
                            </div>
                        )}

                        {warmupResults.length > 0 && (
                            <div className="space-y-3">
                                {warmupResults.map((item, index) => (
                                    <div
                                        key={`${item.model}-${index}`}
                                        className="rounded-xl border border-slate-200/80 dark:border-slate-700/80 bg-white dark:bg-slate-950/40 px-4 py-3"
                                    >
                                        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                                            <span className="font-medium text-slate-700 dark:text-slate-200">{item.targets.join(' / ')}</span>
                                            <span>{item.model}</span>
                                        </div>
                                        {item.content && (
                                            <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm text-slate-700 dark:text-slate-200">
                                                {item.content}
                                            </pre>
                                        )}
                                        {item.error && (
                                            <p className="mt-2 text-sm text-rose-500 dark:text-rose-300">{item.error}</p>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            <div className="card space-y-4">
                <div className="flex items-center gap-2">
                    <Database className="w-5 h-5 text-green-500" />
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">默认分析配置</h2>
                </div>

                <div>
                    <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        默认启用分析师
                    </label>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        {[
                            { key: 'market', label: '市场分析' },
                            { key: 'social', label: '舆情分析' },
                            { key: 'news', label: '新闻分析' },
                            { key: 'fundamentals', label: '基本面' },
                            { key: 'macro', label: '宏观板块' },
                            { key: 'smart_money', label: '主力资金' },
                            { key: 'volume_price', label: '量价分析' },
                        ].map((analyst) => {
                            const active = defaultAnalysts.includes(analyst.key)
                            return (
                                <button
                                    key={analyst.key}
                                    type="button"
                                    onClick={() => toggleAnalyst(analyst.key)}
                                    className={`rounded-xl border px-3 py-3 text-sm transition-colors ${
                                        active
                                            ? 'bg-blue-50 dark:bg-blue-500/10 border-blue-500 text-blue-600 dark:text-blue-400'
                                            : 'bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-400'
                                    }`}
                                >
                                    {analyst.label}
                                </button>
                            )
                        })}
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            辩论轮数上限
                        </label>
                        <input
                            type="number"
                            min={1}
                            max={5}
                            value={maxDebateRounds}
                            onChange={e => setMaxDebateRounds(Number(e.target.value))}
                            className="input w-full"
                            disabled={configLoading}
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            风险讨论轮数上限
                        </label>
                        <input
                            type="number"
                            min={1}
                            max={5}
                            value={maxRiskRounds}
                            onChange={e => setMaxRiskRounds(Number(e.target.value))}
                            className="input w-full"
                            disabled={configLoading}
                        />
                    </div>
                </div>

                <div>
                    <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        自定义分析提示
                    </label>
                    <textarea
                        value={customPrompt}
                        onChange={e => setCustomPrompt(e.target.value)}
                        className="input w-full min-h-[80px] resize-y"
                        placeholder="例如：更关注估值安全边际、政策催化与机构资金行为。"
                    />
                </div>
            </div>

            <div className="card space-y-4">
                <div className="flex items-center gap-2">
                    <Key className="w-5 h-5 text-amber-500" />
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">API 访问令牌</h2>
                    {tokensLoading && <Loader2 className="w-4 h-4 animate-spin text-slate-400 ml-auto" />}
                </div>

                <div className="text-sm text-slate-500 dark:text-slate-400 mb-4">
                    使用 API Token 在三方应用（如 Open Claw）中调用投研分析接口。请妥善保管您的 Token。
                </div>

                {/* Newly created token — show once */}
                {newlyCreatedToken && (
                    <div className="p-3 rounded-2xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800">
                        <div className="text-sm font-medium text-emerald-800 dark:text-emerald-200 mb-1">Token 创建成功 — 请立即复制，关闭后无法再次查看</div>
                        <div className="flex items-center gap-2">
                            <code className="text-xs text-emerald-700 dark:text-emerald-300 bg-white dark:bg-slate-950 px-1.5 py-0.5 rounded border font-mono tracking-tight break-all">
                                {newlyCreatedToken}
                            </code>
                            <button
                                onClick={() => copyToClipboard(newlyCreatedToken, '__new__')}
                                className="p-1 hover:bg-emerald-100 dark:hover:bg-emerald-800 rounded transition-colors text-emerald-600"
                                title="复制 Token"
                            >
                                {copiedTokenId === '__new__' ? <CheckCircle2 className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                            </button>
                        </div>
                        <button onClick={() => setNewlyCreatedToken(null)} className="mt-2 text-xs text-emerald-600 hover:underline">我已复制，关闭提示</button>
                    </div>
                )}

                {/* Token List */}
                <div className="space-y-3">
                    {tokens.map((token) => (
                        <div key={token.id} className="flex flex-col sm:flex-row sm:items-center gap-3 p-3 rounded-2xl bg-slate-50 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-800 transition-all group">
                            <div className="flex-1 min-w-0">
                                <div className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">{token.name}</div>
                                <div className="flex items-center gap-2 mt-1">
                                    <code className="text-xs text-slate-500 dark:text-slate-400 bg-white dark:bg-slate-950 px-1.5 py-0.5 rounded border border-slate-100 dark:border-slate-800 font-mono tracking-tight">
                                        ta-sk-{'•'.repeat(16)}{token.token_hint || '****'}
                                    </code>
                                </div>
                                <div className="text-[10px] text-slate-400 dark:text-slate-500 mt-1">
                                    创建于：{new Date(token.created_at).toLocaleDateString()}
                                    {token.last_used_at && ` • 最后使用：${new Date(token.last_used_at).toLocaleString()}`}
                                </div>
                            </div>
                            <button
                                onClick={() => handleDeleteToken(token.id)}
                                className="self-end sm:self-center p-2 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-500/10 rounded-xl transition-colors"
                                title="吊销 Token"
                            >
                                <Trash2 className="w-4 h-4" />
                            </button>
                        </div>
                    ))}

                    {tokens.length === 0 && !tokensLoading && (
                        <div className="text-center py-6 border-2 border-dashed border-slate-100 dark:border-slate-800 rounded-3xl text-slate-400 text-sm font-medium">
                            暂无活跃的 API Token
                        </div>
                    )}
                </div>

                {/* Create Token Form */}
                    <form onSubmit={handleCreateToken} className="flex items-center gap-2 pt-2">
                        <input
                            type="text"
                            value={newTokenName}
                            onChange={e => setNewTokenName(e.target.value)}
                            placeholder="给新 Token 起个名字，如：Open Claw"
                            className="input flex-1 h-10 text-sm"
                            disabled={isCreatingToken || tokens.length >= 10}
                        />
                    <button
                        type="submit"
                        disabled={isCreatingToken || !newTokenName.trim() || tokens.length >= 10}
                        className="btn-primary h-10 px-4 flex items-center gap-2 whitespace-nowrap text-sm"
                    >
                        {isCreatingToken ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                        生成 Token
                    </button>
                </form>
                {tokens.length >= 10 && (
                    <p className="text-[10px] text-amber-500">已达到 Token 创建上限（10个）</p>
                )}
            </div>

            <div className="card space-y-4">
                <div className="flex items-center gap-2">
                    <Mail className="w-5 h-5 text-blue-500" />
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">报告推送</h2>
                </div>

                {/* 邮件推送 */}
                <div className="rounded-xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-900/40">
                    <div className="flex items-center justify-between">
                        <div>
                            <div className="text-sm font-medium text-slate-700 dark:text-slate-200">邮件推送</div>
                            <div className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">定时分析完成时发送至 {user?.email || '-'}</div>
                        </div>
                        <button
                            type="button"
                            onClick={() => setEmailReportEnabled(!emailReportEnabled)}
                            disabled={configLoading}
                            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
                                emailReportEnabled ? 'bg-blue-500' : 'bg-slate-300 dark:bg-slate-600'
                            }`}
                        >
                            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${emailReportEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
                        </button>
                    </div>
                </div>

                {/* 企业微信 Webhook */}
                <div className="rounded-xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 space-y-3 dark:border-slate-700/80 dark:bg-slate-900/40">
                    <div className="flex items-center justify-between">
                        <div>
                            <div className="text-sm font-medium text-slate-700 dark:text-slate-200">企业微信 Webhook</div>
                            <div className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
                                定时分析完成时向机器人推送摘要
                                {storedWebhookDisplay && <span className="ml-2 font-mono">({storedWebhookDisplay})</span>}
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={() => setWecomReportEnabled(!wecomReportEnabled)}
                            disabled={configLoading}
                            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
                                wecomReportEnabled ? 'bg-blue-500' : 'bg-slate-300 dark:bg-slate-600'
                            }`}
                        >
                            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${wecomReportEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
                        </button>
                    </div>

                    <div className="flex items-center gap-2">
                        <div className="relative flex-1">
                            <Webhook className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                            <input
                                type="text"
                                value={wecomWebhook}
                                onChange={e => setWecomWebhook(e.target.value)}
                                className="input w-full pl-10"
                                placeholder={hasStoredWebhook ? '已保存，留空则保持不变' : 'Webhook 地址'}
                                disabled={configLoading}
                            />
                        </div>
                        <button
                            type="button"
                            onClick={handleWecomWarmup}
                            disabled={configLoading || saving || saveAllSaving || wecomWarmingUp || (!wecomWebhook.trim() && !hasStoredWebhook)}
                            className="btn-secondary inline-flex items-center gap-1.5 text-xs shrink-0"
                        >
                            {wecomWarmingUp ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Flame className="w-3.5 h-3.5" />}
                            {wecomWarmingUp ? '发送中...' : '测试连接'}
                        </button>
                        {hasStoredWebhook && (
                            <button
                                type="button"
                                onClick={handleClearWebhook}
                                disabled={saving || saveAllSaving}
                                className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-rose-500 disabled:opacity-50 shrink-0"
                            >
                                <Trash2 className="w-3 h-3" />
                                清除
                            </button>
                        )}
                    </div>

                    {wecomWarmupMessage && (
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300">
                            {wecomWarmupMessage}
                        </div>
                    )}
                    {wecomWarmupError && (
                        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
                            {wecomWarmupError}
                        </div>
                    )}
                </div>
            </div>

            {/* 回测数据配置 */}
            <div className="card space-y-4">
                <div className="flex items-center gap-2">
                    <Database className="w-5 h-5 text-blue-500" />
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">回测数据配置</h2>
                    {loadingStats && <Loader2 className="ml-auto w-4 h-4 animate-spin text-slate-400" />}
                </div>

                <div className="space-y-4">
                    {/* 日期范围选择 */}
                    <div>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            日期范围选择
                        </label>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div className="relative">
                                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                                <input
                                    type="date"
                                    value={dateRange.start}
                                    onChange={e => setDateRange(prev => ({...prev, start: e.target.value}))}
                                    className="input w-full pl-10"
                                />
                            </div>
                            <div className="relative">
                                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                                <input
                                    type="date"
                                    value={dateRange.end}
                                    onChange={e => setDateRange(prev => ({...prev, end: e.target.value}))}
                                    className="input w-full pl-10"
                                />
                            </div>
                        </div>
                    </div>

                    {/* 数据类型选择 */}
                    <div>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            数据类型选择（可多选）
                        </label>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                            {['daily_kline', 'minute_kline', 'index_data', 'chip_data', 'financial_data', 'research_reports'].map(type => {
                                const Icon = getDataTypeIcon(type)
                                const isSelected = selectedDataTypes.includes(type)
                                return (
                                    <button
                                        key={type}
                                        type="button"
                                        onClick={() => toggleDataType(type)}
                                        className={`flex items-center gap-2 p-3 rounded-lg border transition-colors ${
                                            isSelected 
                                                ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20' 
                                                : 'border-slate-200 hover:border-slate-300 dark:border-slate-700 dark:hover:border-slate-600'
                                        }`}
                                    >
                                        <Icon className={`w-4 h-4 ${isSelected ? 'text-blue-500' : 'text-slate-400'}`} />
                                        <span className={`text-sm ${isSelected ? 'text-blue-700 dark:text-blue-300' : 'text-slate-600 dark:text-slate-400'}`}>
                                            {getDataTypeName(type)}
                                        </span>
                                    </button>
                                )
                            })}
                        </div>
                    </div>

                    {/* 数据源选择 */}
                    <div>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                            数据源选择
                        </label>
                        <select
                            value={dataSource}
                            onChange={e => setDataSource(e.target.value)}
                            className="input w-full"
                        >
                            <option value="quantclass">量化课堂（推荐）- 快速、高质量</option>
                            <option value="akshare">AKShare（免费无限制）</option>
                            <option value="baostock">Baostock（免费）</option>
                            <option value="tushare">Tushare（需要API Token）</option>
                            <option value="eastmoney">东方财富（免费）</option>
                        </select>
                    </div>

                    {/* 每日自动更新开关 */}
                    <div className="flex items-center justify-between">
                        <div>
                            <div className="text-sm font-medium text-slate-700 dark:text-slate-200">每日自动更新</div>
                            <div className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
                                每日自动下载最新数据
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={() => setAutoUpdate(!autoUpdate)}
                            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
                                autoUpdate ? 'bg-green-500' : 'bg-slate-300 dark:bg-slate-600'
                            }`}
                        >
                            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                autoUpdate ? 'translate-x-6' : 'translate-x-1'
                            }`} />
                        </button>
                    </div>

                    {/* 下载按钮 */}
                    <div className="pt-2">
                        <button
                            onClick={handleDownloadData}
                            disabled={downloading || selectedDataTypes.length === 0}
                            className="btn-primary inline-flex items-center gap-2 w-full justify-center"
                        >
                            {downloading ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    下载中... {downloadProgress}%
                                </>
                            ) : (
                                <>
                                    <Download className="w-4 h-4" />
                                    下载回测数据（全部股票）
                                </>
                            )}
                        </button>
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2 text-center">
                            将下载所选日期范围内的全部股票数据
                        </p>
                    </div>

                    {/* 下载进度展示 */}
                    {dataTasks.filter(t => t.status === 'running' || t.status === 'pending').length > 0 && (
                        <div className="mt-6 pt-4 border-t border-slate-200 dark:border-slate-700">
                            <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
                                <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
                                下载进度
                            </h3>
                            
                            <div className="space-y-3">
                                {dataTasks
                                    .filter(t => t.status === 'running' || t.status === 'pending')
                                    .map((task, index) => {
                                        const Icon = getDataTypeIcon(task.task_type)
                                        const progress = task.progress || 0
                                        
                                        return (
                                            <div 
                                                key={index} 
                                                className="p-4 rounded-lg border-2 border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/10"
                                            >
                                                <div className="flex items-center justify-between mb-2">
                                                    <div className="flex items-center gap-2">
                                                        <Icon className="w-5 h-5 text-blue-500" />
                                                        <span className="font-medium text-slate-900 dark:text-slate-100">
                                                            {getDataTypeName(task.task_type)}
                                                            {task.date_range_start && task.date_range_end && (
                                                                <span className="text-slate-500 dark:text-slate-400 ml-2">
                                                                    ({task.date_range_start} ~ {task.date_range_end})
                                                                </span>
                                                            )}
                                                        </span>
                                                    </div>
                                                    <span className={`px-2 py-1 rounded text-xs font-medium ${
                                                        task.status === 'running' 
                                                            ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300' 
                                                            : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
                                                    }`}>
                                                        {task.status === 'running' ? '下载中...' : '等待中'}
                                                    </span>
                                                </div>
                                                
                                                {/* 进度条 */}
                                                <div className="mb-2">
                                                    <div className="flex justify-between text-xs text-slate-600 dark:text-slate-400 mb-1">
                                                        <span>进度: {progress}%</span>
                                                        <span>{task.downloaded_records || 0} 条记录</span>
                                                    </div>
                                                    <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2">
                                                        <div 
                                                            className="bg-blue-500 h-2 rounded-full transition-all duration-300" 
                                                            style={{ width: `${progress}%` }}
                                                        ></div>
                                                    </div>
                                                </div>
                                                
                                                {/* 任务信息 */}
                                                <div className="text-xs text-slate-500 dark:text-slate-400">
                                                    创建时间: {new Date(task.created_at).toLocaleString('zh-CN')}
                                                </div>
                                            </div>
                                        )
                                    })}
                            </div>
                        </div>
                    )}

                    {/* 已下载数据展示 */}
                    <div className="mt-6 pt-4 border-t border-slate-200 dark:border-slate-700">
                        <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
                            <BarChart3 className="w-4 h-4 text-blue-500" />
                            已下载数据
                        </h3>
                        
                        {dataStats.length === 0 ? (
                            <div className="text-center py-8 text-slate-500 dark:text-slate-400">
                                <Database className="w-12 h-12 mx-auto mb-2 opacity-50" />
                                <p className="text-sm">暂无已下载的回测数据</p>
                                <p className="text-xs mt-1">请选择日期范围和数据类型后点击下载</p>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {dataStats.map((stat, index) => {
                                    const Icon = getDataTypeIcon(stat.data_type)
                                    const isComplete = stat.data_quality_score >= 90
                                    const hasIssues = stat.data_quality_score < 80
                                    
                                    return (
                                        <div 
                                            key={index} 
                                            className={`p-4 rounded-lg border-2 ${
                                                isComplete 
                                                    ? 'border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/10' 
                                                    : hasIssues 
                                                        ? 'border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/10'
                                                        : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50'
                                            }`}
                                        >
                                            <div className="flex items-start justify-between mb-3">
                                                <div className="flex items-center gap-2">
                                                    <Icon className={`w-5 h-5 ${isComplete ? 'text-green-500' : hasIssues ? 'text-amber-500' : 'text-blue-500'}`} />
                                                    <span className="font-medium text-slate-900 dark:text-slate-100">
                                                        {getDataTypeName(stat.data_type)}
                                                    </span>
                                                </div>
                                                <div className={`px-2 py-1 rounded text-xs font-medium ${
                                                    isComplete 
                                                        ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' 
                                                        : hasIssues 
                                                            ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'
                                                            : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
                                                }`}>
                                                    {isComplete ? '✓ 完整' : hasIssues ? '⚠ 部分缺失' : '○ 一般'}
                                                </div>
                                            </div>
                                            
                                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                                                <div>
                                                    <div className="text-slate-500 dark:text-slate-400 text-xs">数据量</div>
                                                    <div className="font-semibold text-slate-900 dark:text-slate-100">
                                                        {stat.total_records?.toLocaleString() || '0'} 条
                                                    </div>
                                                </div>
                                                <div>
                                                    <div className="text-slate-500 dark:text-slate-400 text-xs">数据区间</div>
                                                    <div className="font-semibold text-slate-900 dark:text-slate-100 text-xs">
                                                        {stat.date_range_start || '-'} ~ {stat.date_range_end || '-'}
                                                    </div>
                                                </div>
                                                <div>
                                                    <div className="text-slate-500 dark:text-slate-400 text-xs">股票数量</div>
                                                    <div className="font-semibold text-slate-900 dark:text-slate-100">
                                                        {stat.symbol_count || '全部'}
                                                    </div>
                                                </div>
                                                <div>
                                                    <div className="text-slate-500 dark:text-slate-400 text-xs">质量评分</div>
                                                    <div className={`font-semibold ${
                                                        isComplete ? 'text-green-600 dark:text-green-400' :
                                                        hasIssues ? 'text-amber-600 dark:text-amber-400' :
                                                        'text-slate-600 dark:text-slate-400'
                                                    }`}>
                                                        {stat.data_quality_score || 0}/100
                                                    </div>
                                                </div>
                                            </div>
                                            
                                            {stat.last_updated && (
                                                <div className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-700 text-xs text-slate-500 dark:text-slate-400">
                                                    最后更新: {stat.last_updated}
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </div>

                </div>
            </div>

            <div className="flex items-center gap-4">
                <button onClick={handleSaveAll} disabled={saveAllSaving} className="btn-primary inline-flex items-center gap-2">
                    {saveAllSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                    保存全部
                </button>
                {saved && <span className="text-sm text-green-600 dark:text-green-400">✓ {saveMessage}</span>}
            </div>
        </div>
    )
}
