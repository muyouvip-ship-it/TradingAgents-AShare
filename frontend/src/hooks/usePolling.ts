import { useEffect, useRef, useState } from 'react'

interface UsePollingOptions {
  enabled?: boolean
  intervalMs: number
  pauseWhenHidden?: boolean
  runImmediately?: boolean
}

export function usePolling(
  callback: () => Promise<unknown> | unknown,
  {
    enabled = true,
    intervalMs,
    pauseWhenHidden = true,
    runImmediately = true,
  }: UsePollingOptions,
) {
  const callbackRef = useRef(callback)
  const inFlightRef = useRef(false)
  const hasActivatedRef = useRef(false)
  const isVisibleByDefault = typeof document === 'undefined' ? true : document.visibilityState === 'visible'
  const [isDocumentVisible, setIsDocumentVisible] = useState(isVisibleByDefault)

  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  useEffect(() => {
    if (!pauseWhenHidden || typeof document === 'undefined') return undefined

    const handleVisibilityChange = () => {
      setIsDocumentVisible(document.visibilityState === 'visible')
    }

    handleVisibilityChange()
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [pauseWhenHidden])

  useEffect(() => {
    if (!enabled || intervalMs <= 0 || (pauseWhenHidden && !isDocumentVisible)) {
      return undefined
    }

    const runOnce = async () => {
      if (inFlightRef.current) return
      inFlightRef.current = true
      try {
        await callbackRef.current()
      } finally {
        inFlightRef.current = false
      }
    }

    const shouldRunImmediately = runImmediately || hasActivatedRef.current
    hasActivatedRef.current = true

    if (shouldRunImmediately) {
      void runOnce()
    }

    const timer = window.setInterval(() => {
      void runOnce()
    }, intervalMs)

    return () => {
      window.clearInterval(timer)
    }
  }, [enabled, intervalMs, isDocumentVisible, pauseWhenHidden, runImmediately])
}
