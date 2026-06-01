import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../lib/api'
import type { ScenarioStatus, AuditEvent, ScenarioState, Notification } from '../types'

export function useScenario() {
  const [status, setStatus] = useState<ScenarioStatus>('idle')
  const [apiOnline, setApiOnline] = useState(false)
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [saved, setSaved] = useState<string[]>([])
  const [missed, setMissed] = useState<string[]>([])
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [actionCount, setActionCount] = useState(0)
  const wsRef = useRef<WebSocket | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Health check
  useEffect(() => {
    const check = async () => {
      try { await api.health(); setApiOnline(true) }
      catch { setApiOnline(false) }
    }
    check()
    const t = setInterval(check, 5000)
    return () => clearInterval(t)
  }, [])

  // WebSocket for real-time events
  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    const ws = new WebSocket(`ws://${location.host}/ws/events`)
    ws.onmessage = (e) => {
      try {
        const ev: AuditEvent = JSON.parse(e.data)
        if (ev.type === 'PING') return
        setEvents(prev => [ev, ...prev].slice(0, 200))
      } catch {}
    }
    ws.onclose = () => setTimeout(connectWs, 3000)
    wsRef.current = ws
  }, [])

  // Polling for state (fallback + confirming completion)
  const startPolling = useCallback(() => {
    if (pollRef.current) return
    pollRef.current = setInterval(async () => {
      try {
        const s: ScenarioState = await api.getState()
        setSaved(s.saved ?? [])
        setMissed(s.missed ?? [])
        setNotifications(s.notifications ?? [])
        setActionCount(s.action_count ?? 0)
        if (s.action_count >= 3 && status === 'running') {
          setStatus('done')
          clearInterval(pollRef.current!)
          pollRef.current = null
        }
      } catch {}
    }, 1500)
  }, [status])

  const run = useCallback(async () => {
    setStatus('running')
    setEvents([])
    setSaved([])
    setMissed([])
    setNotifications([])
    setActionCount(0)
    connectWs()
    try {
      await api.runScenario()
      startPolling()
      // Auto-complete after 90s safety timeout
      setTimeout(() => {
        if (status === 'running') setStatus('done')
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      }, 90_000)
    } catch { setStatus('error') }
  }, [connectWs, startPolling, status])

  const reset = useCallback(() => {
    setStatus('idle')
    setEvents([])
    setSaved([])
    setMissed([])
    setNotifications([])
    setActionCount(0)
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  return { status, apiOnline, events, saved, missed, notifications, actionCount, run, reset }
}
