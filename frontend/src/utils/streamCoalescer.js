/**
 * Lightweight, frame-synced token coalescer for progressive AI stream rendering.
 *
 * Incoming tokens from NDJSON streaming arrive in rapid, arbitrary chunks (often 1-5 chars).
 * Coalescing them onto animation frame intervals (~16ms) prevents React from triggering
 * 50-100 state updates and markdown re-parses per second, eliminating UI render thrashing
 * while preserving smooth, real-time progressive text appearance.
 */

export function createTokenCoalescer(onFlush, options = {}) {
  const maxDelayMs = options.maxDelayMs || 32
  let buffer = ''
  let rafId = null
  let timeoutId = null

  const flush = () => {
    if (rafId !== null) {
      if (typeof window !== 'undefined' && window.cancelAnimationFrame) {
        window.cancelAnimationFrame(rafId)
      }
      rafId = null
    }
    if (timeoutId !== null) {
      clearTimeout(timeoutId)
      timeoutId = null
    }
    if (buffer.length > 0) {
      const chunk = buffer
      buffer = ''
      onFlush(chunk)
    }
  }

  const push = (token) => {
    if (!token) return
    buffer += token

    // Schedule frame flush if not already pending
    if (rafId === null && typeof window !== 'undefined' && window.requestAnimationFrame) {
      rafId = window.requestAnimationFrame(() => {
        rafId = null
        if (timeoutId !== null) {
          clearTimeout(timeoutId)
          timeoutId = null
        }
        flush()
      })
    }

    // Fallback timer ensures tokens are flushed even if the tab is hidden or rAF is throttled
    if (timeoutId === null) {
      timeoutId = setTimeout(() => {
        timeoutId = null
        flush()
      }, maxDelayMs)
    }
  }

  return {
    push,
    flush,
  }
}
