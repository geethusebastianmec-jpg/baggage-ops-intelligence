export type ScenarioStatus = 'idle' | 'running' | 'done' | 'error'

export interface Flight {
  id: string
  route: string
  status: 'DELAYED' | 'ON_TIME'
  delta: string
  bags: string
  cssClass: 'delayed' | 'ok'
}

export interface BagRow {
  tag: string
  zone: string
  moveMins: number
  slack: number
  outbound: string
  defaultStatus: 'at-risk' | 'impossible' | 'safe'
  liveStatus?: 'confirmed' | 'missed' | null
}

export interface AuditEvent {
  type: 'SCENARIO_STARTED' | 'AUDIT_ACTION' | 'PING' | 'SNAPSHOT' | 'OVERRIDE'
  payload: Record<string, string>
  timestamp: string
}

export interface Notification {
  passenger_id: string
  bag_tag: string
  type: 'AT_RISK' | 'RECOVERED' | 'MISSED'
  message: string
}

export interface ScenarioState {
  scenario_running: boolean
  saved: string[]
  missed: string[]
  saved_count: number
  missed_count: number
  notifications: Notification[]
  recent_events: AuditEvent[]
  action_count: number
}
