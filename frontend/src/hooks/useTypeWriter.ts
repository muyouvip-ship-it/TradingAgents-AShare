import { useEffect, useRef, useState } from 'react'

interface UseTypeWriterOptions {
    speed?: number        // 每字符间隔(ms)，默认30ms
    onComplete?: () => void
}

interface UseTypeWriterReturn {
    displayed: string     // 已显示的文本
    isTyping: boolean     // 是否正在打字
    progress: number      // 进度 0-1
}

/**
 * 打字机效果 Hook
 * 
 * @param text 要显示的完整文本
 * @param isActive 是否开始打字
 * @param options 配置选项
 * @returns 打字机状态和进度
 * 
 * @example
 * const { displayed, isTyping, progress } = useTypeWriter(
 *     fullText, 
 *     isActive, 
 *     { speed: 30 }
 * )
 */
export function useTypeWriter(
    text: string,
    isActive: boolean,
    options: UseTypeWriterOptions = {}
): UseTypeWriterReturn {
    const { speed = 30, onComplete } = options
    const [displayed, setDisplayed] = useState('')
    const [isTyping, setIsTyping] = useState(false)
    const [hasCompleted, setHasCompleted] = useState(false)
    const displayedRef = useRef('')
    const hasCompletedRef = useRef(false)
    const timeoutRef = useRef<number | null>(null)
    const intervalRef = useRef<number | null>(null)

    useEffect(() => {
        displayedRef.current = displayed
    }, [displayed])

    useEffect(() => {
        hasCompletedRef.current = hasCompleted
    }, [hasCompleted])

    useEffect(() => {
        if (timeoutRef.current != null) {
            window.clearTimeout(timeoutRef.current)
            timeoutRef.current = null
        }
        if (intervalRef.current != null) {
            window.clearInterval(intervalRef.current)
            intervalRef.current = null
        }

        timeoutRef.current = window.setTimeout(() => {
            timeoutRef.current = null

            if (!isActive) {
                displayedRef.current = ''
                hasCompletedRef.current = false
                setDisplayed('')
                setIsTyping(false)
                setHasCompleted(false)
                return
            }

            if (hasCompletedRef.current && displayedRef.current === text) {
                return
            }

            if (!text) {
                setIsTyping(false)
                if (!hasCompletedRef.current) {
                    hasCompletedRef.current = true
                    setHasCompleted(true)
                    onComplete?.()
                }
                return
            }

            setIsTyping(true)
            displayedRef.current = ''
            setDisplayed('')
            let index = 0
            intervalRef.current = window.setInterval(() => {
                if (index < text.length) {
                    const next = text.slice(0, index + 1)
                    displayedRef.current = next
                    setDisplayed(next)
                    index++
                } else {
                    if (intervalRef.current != null) {
                        window.clearInterval(intervalRef.current)
                        intervalRef.current = null
                    }
                    setIsTyping(false)
                    hasCompletedRef.current = true
                    setHasCompleted(true)
                    onComplete?.()
                }
            }, speed)
        }, speed)

        return () => {
            if (timeoutRef.current != null) {
                window.clearTimeout(timeoutRef.current)
                timeoutRef.current = null
            }
            if (intervalRef.current != null) {
                window.clearInterval(intervalRef.current)
                intervalRef.current = null
            }
        }
    }, [text, isActive, speed, onComplete])

    const progress = text.length > 0 ? displayed.length / text.length : 0

    return { displayed, isTyping, progress }
}

/**
 * 多段落打字机效果 Hook
 * 用于报告章节的流式渲染
 */
interface UseStreamingSectionOptions {
    speed?: number
}

interface UseStreamingSectionReturn {
    displayed: string
    isTyping: boolean
    isComplete: boolean
}

export function useStreamingSection(
    chunks: string[],      // 文本片段数组
    isActive: boolean,
    options: UseStreamingSectionOptions = {}
): UseStreamingSectionReturn {
    const { speed = 30 } = options
    const [displayed, setDisplayed] = useState('')
    const [isTyping, setIsTyping] = useState(false)
    const [isComplete, setIsComplete] = useState(false)
    const displayedRef = useRef('')
    const completeRef = useRef(false)
    const timeoutRef = useRef<number | null>(null)
    const intervalRef = useRef<number | null>(null)

    useEffect(() => {
        displayedRef.current = displayed
    }, [displayed])

    useEffect(() => {
        completeRef.current = isComplete
    }, [isComplete])

    useEffect(() => {
        if (timeoutRef.current != null) {
            window.clearTimeout(timeoutRef.current)
            timeoutRef.current = null
        }
        if (intervalRef.current != null) {
            window.clearInterval(intervalRef.current)
            intervalRef.current = null
        }

        timeoutRef.current = window.setTimeout(() => {
            timeoutRef.current = null
            if (!isActive || chunks.length === 0) {
                if (!isActive) {
                    displayedRef.current = ''
                    setDisplayed('')
                }
                setIsTyping(false)
                setIsComplete(false)
                completeRef.current = false
                return
            }

            const fullText = chunks.join('')
            if (displayedRef.current === fullText && fullText.length > 0) {
                setIsTyping(false)
                setIsComplete(true)
                completeRef.current = true
                return
            }

            setIsTyping(true)
            setIsComplete(false)
            completeRef.current = false

            let index = 0
            displayedRef.current = ''
            setDisplayed('')
            intervalRef.current = window.setInterval(() => {
                if (index < fullText.length) {
                    const next = fullText.slice(0, index + 1)
                    displayedRef.current = next
                    setDisplayed(next)
                    index++
                    return
                }
                if (intervalRef.current != null) {
                    window.clearInterval(intervalRef.current)
                    intervalRef.current = null
                }
                setIsTyping(false)
                setIsComplete(true)
                completeRef.current = true
            }, speed)
        }, 0)

        return () => {
            if (timeoutRef.current != null) {
                window.clearTimeout(timeoutRef.current)
                timeoutRef.current = null
            }
            if (intervalRef.current != null) {
                window.clearInterval(intervalRef.current)
                intervalRef.current = null
            }
        }
    }, [chunks, isActive, speed])

    return { displayed, isTyping, isComplete }
}

export default useTypeWriter
