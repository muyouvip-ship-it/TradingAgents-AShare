import { describe, expect, it } from 'vitest'

import { navItems } from '@/components/sidebarNav'

describe('sidebarNav', () => {
    it('includes a dedicated tracking board entry in the sidebar', () => {
        const dashboardIndex = navItems.findIndex(item => item.path === '/')
        const trackingBoardIndex = navItems.findIndex(item => item.path === '/tracking-board')

        expect(trackingBoardIndex).toBeGreaterThan(0)
        expect(dashboardIndex).toBe(0)
        expect(navItems[trackingBoardIndex]).toMatchObject({
            path: '/tracking-board',
            label: '跟踪看板',
        })
        expect(trackingBoardIndex).toBeGreaterThan(dashboardIndex)
    })

    it('includes a debug logs entry in the sidebar', () => {
        const debugIndex = navItems.findIndex(item => item.path === '/debug/logs')

        expect(debugIndex).toBeGreaterThan(0)
        expect(navItems[debugIndex]).toMatchObject({
            path: '/debug/logs',
            label: '日志调试',
        })
    })

    it('keeps virtual, live and tracking warehouses as separate entries', () => {
        expect(navItems.find(item => item.path === '/virtual-warehouse')).toMatchObject({ label: '虚拟仓' })
        expect(navItems.find(item => item.path === '/live-warehouse')).toMatchObject({ label: '实盘仓' })
        expect(navItems.find(item => item.path === '/tracking-board')).toMatchObject({ label: '跟踪看板' })
    })
})
