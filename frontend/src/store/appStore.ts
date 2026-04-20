import { create } from 'zustand'

type AppState = {
  loading: boolean
  setLoading: (loading: boolean) => void
}

export const useAppStore = create<AppState>((set) => ({
  loading: false,
  setLoading: (loading: boolean) => set({ loading }),
}))
