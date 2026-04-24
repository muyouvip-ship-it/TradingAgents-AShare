import { BrowserRouter, Navigate, Routes, Route } from 'react-router-dom'
import { Suspense, lazy, useEffect } from 'react'
import { SpeedInsights } from '@vercel/speed-insights/react'
import Layout from './components/Layout'
import { useAuthStore } from './stores/authStore'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const NewsEye = lazy(() => import('./pages/NewsEye'))
const StockMarket = lazy(() => import('./pages/StockMarket'))
const Analysis = lazy(() => import('./pages/Analysis'))
const Reports = lazy(() => import('./pages/Reports'))
const Settings = lazy(() => import('./pages/Settings'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const TrackingBoard = lazy(() => import('./pages/TrackingBoard'))
const Login = lazy(() => import('./pages/Login'))
const Feedback = lazy(() => import('./pages/Feedback'))
const DebugLogs = lazy(() => import('./pages/DebugLogs'))
const Sponsor = lazy(() => import('./pages/Sponsor'))
const Thanks = lazy(() => import('./pages/Thanks'))
const StrategiesV2 = lazy(() => import('./pages/StrategiesV2'))
const StrategyCreate = lazy(() => import('./pages/StrategyCreate'))
const Backtest = lazy(() => import('./pages/Backtest'))
const BacktestResult = lazy(() => import('./pages/BacktestResult'))
const RealtimeMonitor = lazy(() => import('./pages/RealtimeMonitor'))
const VirtualWarehouse = lazy(() => import('./pages/VirtualWarehouse'))
const LiveWarehouse = lazy(() => import('./pages/LiveWarehouse'))

const ONLINE_HOST = 'app.510168.xyz'
const isOnline = typeof window !== 'undefined' && window.location.hostname === ONLINE_HOST

function ExternalRedirect({ to, fallback }: { to: string; fallback: JSX.Element }) {
  if (isOnline) return fallback
  window.location.href = to
  return null
}

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, hydrated, hydrate } = useAuthStore()

  useEffect(() => {
    if (!hydrated) void hydrate()
  }, [hydrated, hydrate])

  if (!hydrated) {
    return <div className="min-h-screen flex items-center justify-center text-slate-500">加载中...</div>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return children
}

function PageLoading() {
  return <div className="min-h-screen flex items-center justify-center text-slate-500">加载中...</div>
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageLoading />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/sponsor" element={<ExternalRedirect to={`https://${ONLINE_HOST}/sponsor`} fallback={<Sponsor />} />} />
          <Route path="/thanks" element={<ExternalRedirect to={`https://${ONLINE_HOST}/thanks`} fallback={<Thanks />} />} />
          <Route
            path="*"
            element={
              <RequireAuth>
                <Layout>
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/news-eye" element={<NewsEye />} />
                    <Route path="/stock-market" element={<StockMarket />} />
                    <Route path="/tracking-board" element={<TrackingBoard />} />
                    <Route path="/analysis" element={<Analysis />} />
                    <Route path="/reports" element={<Reports />} />
                    <Route path="/portfolio" element={<Portfolio />} />
                    <Route path="/strategies" element={<StrategiesV2 />} />
                    <Route path="/strategies/create" element={<StrategyCreate />} />
                    <Route path="/strategies/:id" element={<StrategyCreate />} />
                    <Route path="/strategies/:id/edit" element={<StrategyCreate />} />
                    <Route path="/backtest" element={<Backtest />} />
                    <Route path="/backtest/runs/:runId" element={<BacktestResult />} />
                    <Route path="/realtime" element={<RealtimeMonitor />} />
                    <Route path="/virtual-warehouse" element={<VirtualWarehouse />} />
                    <Route path="/live-warehouse" element={<LiveWarehouse />} />
                    <Route path="/debug/logs" element={<DebugLogs />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="/feedback" element={<Feedback />} />
                  </Routes>
                </Layout>
              </RequireAuth>
            }
          />
        </Routes>
      </Suspense>
      <SpeedInsights />
    </BrowserRouter>
  )
}

export default App
