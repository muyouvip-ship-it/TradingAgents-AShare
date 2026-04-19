import { create } from 'zustand'
import type { AuthUser } from '@/types'
import { api } from '@/services/api'
import { useAnalysisStore } from '@/stores/analysisStore'

interface AuthState {
    user: AuthUser | null
    token: string | null
    loading: boolean
    hydrated: boolean
    setAuth: (token: string, user: AuthUser) => void
    logout: () => void
    hydrate: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
    user: null,
    token: null,
    loading: false,
    hydrated: false,

    setAuth: (token, user) => {
        localStorage.setItem('ta-access-token', token)
        localStorage.setItem('ta-user', JSON.stringify(user))
        useAnalysisStore.getState().clearSession()
        set({ token, user, hydrated: true })
    },

    logout: () => {
        localStorage.removeItem('ta-access-token')
        localStorage.removeItem('ta-user')
        useAnalysisStore.getState().clearSession()
        set({ token: null, user: null, hydrated: true })
    },

    hydrate: async () => {
        const token = localStorage.getItem('ta-access-token')
        const userRaw = localStorage.getItem('ta-user')
        
        // 开发模式：如果没有token，设置一个测试token
        if (!token) {
            const devToken = 'dev-test-token-001'
            localStorage.setItem('ta-access-token', devToken)
            set({ token: devToken, user: null, hydrated: true, loading: false })
            return
        }
        
        if (!token || !userRaw) {
            set({ token: null, user: null, hydrated: true })
            return
        }

        set({ loading: true })
        try {
            const user = await api.getMe()
            localStorage.setItem('ta-user', JSON.stringify(user))
            set({ token, user, hydrated: true, loading: false })
        } catch {
            localStorage.removeItem('ta-access-token')
            localStorage.removeItem('ta-user')
            set({ token: null, user: null, hydrated: true, loading: false })
        }
    },
}))
