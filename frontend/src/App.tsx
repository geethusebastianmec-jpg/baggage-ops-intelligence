import { useState } from 'react'
import { useScenario } from './hooks/useScenario'
import { FLIGHTS, BAGS, WORKFLOWS, TIERS, NODE_LABELS } from './data'
import { api } from './lib/api'
import type { AuditEvent, Notification } from './types'

const C = {
  green: '#16a34a', red: '#dc2626', amber: '#ea580c',
  blue: '#0066cc', slate: '#64748b', muted: '#94a3b8',
  border: '#e2e8f0', bg: '#f8fafc', card: '#ffffff',
}

function Chip({ color, children }: { color: string; children: React.ReactNode }) {
  const bg: Record<string, string> = { green: '#dcfce7', red: '#fee2e2', amber: '#fff7ed', blue: '#dbeafe', slate: '#f1f5f9' }
  const fg: Record<string, string> = { green: C.green, red: C.red, amber: C.amber, blue: C.blue, slate: C.slate }
  return <span style={{ background: bg[color] ?? bg.slate, color: fg[color] ?? fg.slate, fontWeight: 600, fontSize: '0.7rem', padding: '2px 8px', borderRadius: 999, whiteSpace: 'nowrap' as const }}>{children}</span>
}

function SLabel({ children }: { children: React.ReactNode }) {
  return <p style={{ fontSize: '0.65rem', fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase' as const, color: C.muted, borderBottom: `1px solid ${C.border}`, paddingBottom: 6, marginBottom: 10 }}>{children}</p>
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16, ...style }}>{children}</div>
}

function eventColor(ev: AuditEvent): string {
  if (ev.type === 'SCENARIO_STARTED') return C.blue
  const r = (ev.payload?.result ?? '').toLowerCase()
  if (/confirmed|routed|rebooked|recovered/.test(r)) return C.green
  if (/missed|failed|error/.test(r)) return C.red
  if (/at.?risk|contention|escalat/.test(r)) return C.amber
  return C.slate
}

function nLabel(node: string): string {
  for (const [k, v] of Object.entries(NODE_LABELS)) { if (node.toLowerCase().includes(k)) return `[${v}]` }
  return '[AGT]'
}

// Derive live bag chip from audit events during run
function liveBagStatus(tag: string, events: AuditEvent[]): 'confirmed' | 'missed' | null {
  for (const ev of events) {
    if (ev.type !== 'AUDIT_ACTION') continue
    const res = (ev.payload?.result ?? '').toLowerCase()
    const rawBags = ev.payload?.bag_tags ?? ev.payload?.passengers_notified ?? []
    const bags: string[] = Array.isArray(rawBags) ? rawBags as string[] : []
    if (bags.includes(tag) || res.includes(tag.toLowerCase())) {
      if (/confirmed|recovered|rush|exception/.test(res)) return 'confirmed'
      if (/missed|impossible/.test(res)) return 'missed'
    }
  }
  return null
}

export default function App() {
  const { status, apiOnline, events, saved, missed, notifications, actionCount, run, reset } = useScenario()
  const [ov, setOv] = useState({ decision: 'HOLD', flight: 'AA501', operator: 'OPS-001', note: '' })
  const [ovMsg, setOvMsg] = useState('')
  const savedSet = new Set(saved)
  const missedSet = new Set(missed)
  const total = saved.length + missed.length
  const pct = total > 0 ? Math.round(saved.length / total * 100) : 0

  const submitOv = async () => {
    try {
      await api.override({ decision: ov.decision, target: ov.flight, operator: ov.operator, note: ov.note })
      setOvMsg(`Submitted: ${ov.decision} on ${ov.flight}`)
      setTimeout(() => setOvMsg(''), 3000)
    } catch { setOvMsg('API unreachable') }
  }

  // Bag chip — live during run, final after done, default before
  const getBagChip = (b: typeof BAGS[0]) => {
    if (status === 'done') {
      if (savedSet.has(b.tag))                return <Chip color="green">CONFIRMED</Chip>
      if (missedSet.has(b.tag))               return <Chip color="red">MISSED</Chip>
    }
    if (status === 'running') {
      const live = liveBagStatus(b.tag, events)
      if (live === 'confirmed')               return <Chip color="green">CONFIRMED</Chip>
      if (live === 'missed')                  return <Chip color="red">MISSED</Chip>
    }
    if (b.defaultStatus === 'impossible')     return <Chip color="red">IMPOSSIBLE</Chip>
    if (b.defaultStatus === 'safe')           return <Chip color="slate">SAFE</Chip>
    return <Chip color="amber">AT RISK</Chip>
  }

  return (
    <div style={{ minHeight: '100vh', background: C.bg }}>

      {/* ── HEADER ── */}
      <header style={{ background: C.card, borderBottom: `1px solid ${C.border}`, padding: '12px 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: '1.2rem' }}>🧳</span>
          <span style={{ fontWeight: 700, fontSize: '1rem' }}>Baggage Ops Intelligence</span>
          <span style={{ fontSize: '0.78rem', color: C.muted }}>by dCortex</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ background: apiOnline ? '#dcfce7' : '#f1f5f9', color: apiOnline ? C.green : C.muted, fontSize: '0.7rem', fontWeight: 600, padding: '3px 10px', borderRadius: 999 }}>{apiOnline ? '● LIVE' : '○ OFFLINE'}</span>
          <span style={{ fontSize: '0.75rem', color: C.muted }}>JFK Hub Demo</span>
        </div>
      </header>

      <main style={{ maxWidth: 1280, margin: '0 auto', padding: '0 24px 48px' }}>

        {/* ── 1. PROBLEM ── */}
        <section style={{ padding: '48px 0 32px' }}>
          <div style={{ textAlign: 'center', marginBottom: 40 }}>
            <h1 style={{ fontSize: '2.2rem', fontWeight: 700, letterSpacing: '-0.03em', color: '#0f172a', marginBottom: 12, lineHeight: 1.2 }}>
              Airlines lose <span style={{ color: C.red }}>$5 billion</span> per year<br />to a coordination problem
            </h1>
            <p style={{ fontSize: '1rem', color: C.slate, maxWidth: 620, margin: '0 auto', lineHeight: 1.7 }}>
              33 million bags mishandled annually. 41% from transfer misconnections — a flight arrives late and
              no one coordinates fast enough. Today a human coordinator makes four sequential phone calls.
              By the time the fourth call is done, the window is gone.
            </p>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16 }}>
            {[
              { label: 'The Problem', text: 'A human AOCC coordinator makes four phone calls — baggage, ramp, dispatch, comms. Each 1–3 minutes. Sequential. By call four, bags have already missed their window.', accent: C.red },
              { label: 'The Solution', text: 'Activates all coordinators simultaneously. Triage is arithmetic (not AI). CP-SAT for crew contention — CREW bags get IATA Priority 1. MIP for network rerouting of missed bags. Interline bags trigger partner airline IATA notification. GSP zones dispatch through their own handler API. LLM only for genuinely novel compound events.', accent: C.blue },
              { label: 'The Result', text: '+40% bags recovered vs. the manual baseline. 2.5-second decision time vs. ~3 minutes. 74% recovery rate vs. 34%. Every passenger notified automatically at each stage.', accent: C.green },
            ].map(({ label, text, accent }) => (
              <Card key={label} style={{ borderTop: `3px solid ${accent}` }}>
                <p style={{ fontWeight: 700, fontSize: '0.78rem', textTransform: 'uppercase' as const, letterSpacing: '0.08em', color: accent, marginBottom: 8 }}>{label}</p>
                <p style={{ fontSize: '0.87rem', color: C.slate, lineHeight: 1.65 }}>{text}</p>
              </Card>
            ))}
          </div>
        </section>

        {/* ── 2. KPIs ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 12, marginBottom: 32 }}>
          {[
            { num: '74%', sub: '+40% vs manual', label: 'Recovery rate', color: C.green },
            { num: '2.5s', sub: 'vs ~3 min manual', label: 'Decision time', color: C.blue },
            { num: '12', sub: 'AA401/402/403', label: 'Bags at risk', color: C.amber },
            { num: '10', sub: 'all implemented', label: 'Disruption types', color: C.blue },
            { num: '94', sub: 'all passing', label: 'Tests', color: C.green },
            { num: '$5B', sub: 'industry / year', label: 'Cost of problem', color: C.red },
          ].map(({ num, sub, label, color }) => (
            <Card key={label} style={{ textAlign: 'center', padding: '14px 10px' }}>
              <p style={{ fontSize: '1.8rem', fontWeight: 700, color, lineHeight: 1 }}>{num}</p>
              <p style={{ fontSize: '0.7rem', color: C.muted, margin: '4px 0 2px' }}>{sub}</p>
              <p style={{ fontSize: '0.63rem', fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.08em', color: '#cbd5e1' }}>{label}</p>
            </Card>
          ))}
        </div>

        {/* ── 3. FLIGHT BOARD + TRIAGE (always visible) ── */}
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, marginBottom: 24 }}>
          <Card>
            <SLabel>Live Flight Status — JFK Hub</SLabel>
            <p style={{ fontSize: '0.82rem', color: C.slate, marginBottom: 12, lineHeight: 1.6 }}>
              Three inbound flights delayed. Two outbounds counting down. For each of the 12 transfer bags, the system must decide whether physical transfer is possible before the departure window closes.
            </p>
            <table style={{ width: '100%', borderCollapse: 'collapse' as const, fontSize: '0.82rem' }}>
              <thead>
                <tr style={{ color: C.muted, fontSize: '0.67rem', textTransform: 'uppercase' as const, letterSpacing: '0.08em' }}>
                  {['Flight', 'Route', 'Status', 'Window', 'Bags'].map(h => <th key={h} style={{ textAlign: 'left' as const, padding: '4px 8px', fontWeight: 600 }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {FLIGHTS.map(f => {
                  const d = f.cssClass === 'delayed'
                  return (
                    <tr key={f.id} style={{ background: d ? '#fff7ed' : '#f0fdf4', borderLeft: `3px solid ${d ? C.amber : C.green}` }}>
                      <td style={{ padding: '7px 8px', fontFamily: 'monospace', fontWeight: 700, color: d ? C.amber : C.green }}>{f.id}</td>
                      <td style={{ padding: '7px 8px', color: C.slate }}>{f.route}</td>
                      <td style={{ padding: '7px 8px' }}><Chip color={d ? 'amber' : 'green'}>{f.status.replace('_', ' ')}</Chip></td>
                      <td style={{ padding: '7px 8px', fontFamily: 'monospace', color: C.slate, fontSize: '0.78rem' }}>{f.delta}</td>
                      <td style={{ padding: '7px 8px', color: C.slate, fontSize: '0.78rem' }}>{f.bags}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </Card>
          <Card>
            <SLabel>Triage Logic — Tier 1</SLabel>
            <p style={{ fontSize: '0.82rem', color: C.slate, lineHeight: 1.6, marginBottom: 12 }}>For each bag, one calculation determines its fate. No AI needed.</p>
            <div style={{ background: '#f8fafc', border: `1px solid ${C.border}`, borderRadius: 6, padding: '10px 12px', fontFamily: 'monospace', fontSize: '0.78rem', color: '#0f172a', lineHeight: 2, marginBottom: 14 }}>
              slack = window &minus; move_time<br />
              <span style={{ color: C.green }}>slack &ge; 0  &rarr;  RUSH IT</span><br />
              <span style={{ color: C.red }}>slack &lt; 0  &rarr;  IMPOSSIBLE</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: C.slate, lineHeight: 1.8 }}>
              <p>🟡 <strong>Zone B</strong> (near gate) · 8 min · slack +17</p>
              <p>🔴 <strong>Zone D</strong> (deep queue) · 26 min · slack &minus;1</p>
              <p style={{ marginTop: 8, fontSize: '0.74rem', color: C.muted }}>Move time ≠ MCT. MCT covers passengers (walking, customs, security). Bag move time is the physical ramp transfer only.</p>
            </div>
          </Card>
        </div>

        {/* ── 4. BAG PREVIEW (always visible — shows the stakes before the demo) ── */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>12 Transfer Bags — Before the System Acts</SLabel>
          <p style={{ fontSize: '0.82rem', color: C.slate, marginBottom: 14, lineHeight: 1.6 }}>
            Each bag's fate is determined by its BHS zone position — not by an AI judgment.
            Zone B bags (8-min move time) have positive slack. Zone D bags (26-min move time) are physically impossible regardless of what any model thinks.
            Run the scenario to watch this play out live.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 4 }}>
            {BAGS.map(b => (
              <div key={b.tag} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px', background: '#f8fafc', borderRadius: 6, border: `1px solid ${C.border}` }}>
                <span style={{ fontFamily: 'monospace', fontSize: '0.73rem', fontWeight: 600, color: C.blue, minWidth: 52 }}>{b.tag}</span>
                <span style={{ fontSize: '0.7rem', color: C.slate, minWidth: 48 }}>{b.zone}</span>
                <span style={{ fontFamily: 'monospace', fontSize: '0.68rem', color: b.slack < 0 ? C.red : C.green, minWidth: 38 }}>slk{b.slack > 0 ? '+' : ''}{b.slack}</span>
                {getBagChip(b)}
              </div>
            ))}
          </div>
        </Card>

        {/* ── 5. ARCHITECTURE FLOW ── */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>System Architecture — How It Works</SLabel>
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 24 }}>
            <div>
              <p style={{ fontSize: '0.82rem', color: C.slate, lineHeight: 1.7, marginBottom: 14 }}>
                A delay event fires. The system does in <strong>2.5 seconds</strong> what a human coordinator does in <strong>3 minutes</strong> — and does it for all four domains simultaneously.
              </p>
              {/* Event flow */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                {[
                  { step: '1', label: 'Delay event', detail: '→ published to Kafka (Redpanda)', color: C.blue },
                  { step: '2', label: 'Worker', detail: '→ polls Kafka, runs Strategic Supervisor', color: C.blue },
                  { step: '3', label: 'Playbook match', detail: '→ FLIGHT_DELAY_CRITICAL → activates 3 coordinators', color: '#7c3aed' },
                  { step: '4', label: 'Baggage Coordinator', detail: '→ Tier 1 triage + Tier 2a CP-SAT → exception routing', color: C.green },
                  { step: '4', label: 'Ramp Coordinator', detail: '→ crew check + task assignment (parallel)', color: C.green },
                  { step: '4', label: 'Dispatch Coordinator', detail: '→ cost comparison → HOLD or DEPART (parallel)', color: C.green },
                  { step: '5', label: 'Confirming scan', detail: '→ BHS scan confirms bag loaded → RECOVERED notify', color: C.green },
                  { step: '5', label: 'Missed bags', detail: '→ Tier 2b MIP rerouter → next available flight', color: C.amber },
                  { step: '6', label: 'Audit actions', detail: '→ published to Kafka → API streams to dashboard', color: C.slate },
                ].map((s, i) => (
                  <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '5px 0', borderLeft: `2px solid ${s.color}20`, paddingLeft: 10, marginLeft: 10 }}>
                    <span style={{ fontFamily: 'monospace', fontSize: '0.68rem', color: s.color, fontWeight: 700, minWidth: 16, paddingTop: 2 }}>{s.step}</span>
                    <div>
                      <span style={{ fontWeight: 600, fontSize: '0.8rem', color: '#0f172a' }}>{s.label}</span>
                      <span style={{ fontSize: '0.78rem', color: C.slate }}> {s.detail}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div style={{ marginBottom: 16 }}>
                <SLabel>Tier Ladder — Right Tool for Each Question</SLabel>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                  {TIERS.map(t => (
                    <div key={t.id} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '6px 8px', background: '#f8fafc', borderRadius: 6, border: `1px solid ${C.border}` }}>
                      <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '0.7rem', color: t.color, minWidth: 28 }}>{t.id}</span>
                      <span style={{ fontFamily: 'monospace', fontSize: '0.7rem', color: t.color, minWidth: 52 }}>{t.tool}</span>
                      <span style={{ fontSize: '0.75rem', color: C.slate, lineHeight: 1.4 }}>{t.desc}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div style={{ background: '#fef2f2', borderRadius: 6, padding: '10px 12px', fontSize: '0.78rem', fontFamily: 'monospace', lineHeight: 2, color: '#7f1d1d' }}>
                V1: LLM call &rarr; &ldquo;BA-007 unrecoverable&rdquo; (non-deterministic)<br />
                <span style={{ color: C.green }}>V2: 25 &minus; 26 = &minus;1 &rarr; IMPOSSIBLE (always)</span>
              </div>
              <p style={{ fontSize: '0.74rem', color: C.muted, marginTop: 10 }}>LLM fires on ~20% of events — genuinely novel compound disruptions. Everything else is deterministic.</p>
            </div>
          </div>
        </Card>

        {/* ── 6. RUN CONTROL ── */}
        <Card style={{ marginBottom: 24, textAlign: 'center', padding: '28px 24px' }}>
          {status === 'idle' && (
            <>
              <p style={{ fontWeight: 700, fontSize: '1.05rem', color: '#0f172a', marginBottom: 8 }}>Run the Hub Crisis scenario</p>
              <p style={{ fontSize: '0.85rem', color: C.slate, marginBottom: 20, maxWidth: 560, margin: '0 auto 20px', lineHeight: 1.7 }}>
                Three delay events publish to Kafka. The worker activates all coordinators in parallel.
                Watch the activity log fill in real time and bag chips update as each action lands.
              </p>
              {!apiOnline && (
                <div style={{ background: '#fff7ed', border: `1px solid #fed7aa`, borderRadius: 8, padding: '12px 16px', marginBottom: 16, textAlign: 'left' as const, maxWidth: 560, margin: '0 auto 16px' }}>
                  <p style={{ fontSize: '0.82rem', fontWeight: 600, color: C.amber, marginBottom: 6 }}>⚠ Backend API offline</p>
                  <p style={{ fontSize: '0.78rem', color: C.slate, lineHeight: 1.7, fontFamily: 'monospace' }}>
                    Terminal 1: <strong>uvicorn src.api.main:app --port 8000</strong><br />
                    Terminal 2: <strong>python src/worker.py</strong><br />
                    Terminal 3: <strong>docker compose up -d</strong> (for Kafka)
                  </p>
                </div>
              )}
              <button onClick={run} disabled={!apiOnline} style={{ background: apiOnline ? C.blue : '#e2e8f0', color: apiOnline ? '#fff' : C.muted, border: 'none', borderRadius: 8, padding: '12px 36px', fontSize: '1rem', fontWeight: 600, cursor: apiOnline ? 'pointer' : 'not-allowed' }}>
                &#9654;&nbsp; Run Hub Crisis
              </button>
            </>
          )}
          {status === 'running' && (
            <div>
              <div style={{ width: 36, height: 36, borderRadius: '50%', border: `3px solid ${C.border}`, borderTopColor: C.blue, animation: 'spin 0.8s linear infinite', margin: '0 auto 12px' }} />
              <p style={{ fontWeight: 600, color: '#0f172a', marginBottom: 4 }}>Agents coordinating&hellip;</p>
              <p style={{ fontSize: '0.82rem', color: C.slate }}>Kafka &rarr; Worker &rarr; Triage &rarr; CP-SAT / MIP &rarr; Ramp &rarr; Dispatch &rarr; Comms</p>
              <p style={{ fontFamily: 'monospace', fontSize: '0.78rem', color: C.muted, marginTop: 8 }}>
                Actions: {actionCount} &nbsp;|&nbsp; <span style={{ color: C.green }}>Confirmed: {saved.length}</span> &nbsp;|&nbsp; <span style={{ color: C.red }}>Missed: {missed.length}</span>
              </p>
            </div>
          )}
          {(status === 'done' || status === 'error') && (
            <div>
              <p style={{ fontWeight: 700, fontSize: '1.1rem', color: C.green, marginBottom: 6 }}>&#10003; Complete — {pct}% of at-risk bags recovered</p>
              <p style={{ fontSize: '0.85rem', color: C.slate, marginBottom: 16 }}>{saved.length} confirmed on outbound &middot; {missed.length} missed &middot; {notifications.length} passengers notified</p>
              <button onClick={reset} style={{ background: 'transparent', border: `1px solid ${C.border}`, color: C.slate, borderRadius: 6, padding: '8px 20px', fontSize: '0.85rem', fontWeight: 500, cursor: 'pointer' }}>&#8635; Run Again</button>
            </div>
          )}
        </Card>

        {/* ── 7. ACTIVITY LOG + LIVE RESULTS (appears once running) ── */}
        {status !== 'idle' && (
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 16, marginBottom: 24 }}>
            <Card>
              <SLabel>Agent Activity Log — Live</SLabel>
              <div style={{ maxHeight: 400, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 1 }}>
                {events.length === 0 && <p style={{ fontSize: '0.8rem', color: C.muted, padding: '12px 0' }}>Waiting for first Kafka message&hellip;</p>}
                {events.map((ev, i) => {
                  if (ev.type === 'SCENARIO_STARTED') return (
                    <div key={i} style={{ fontFamily: 'monospace', fontSize: '0.78rem', color: C.blue, padding: '3px 0', lineHeight: 1.5 }}>
                      {ev.timestamp?.slice(11, 19)} &loz; SCENARIO STARTED — 3 events &rarr; Kafka
                    </div>
                  )
                  if (ev.type !== 'AUDIT_ACTION') return null
                  const node = ev.payload?.node ?? ev.payload?.coordinator ?? '?'
                  const result = (ev.payload?.result ?? '').slice(0, 110)
                  const color = eventColor(ev)
                  return (
                    <div key={i} style={{ fontFamily: 'monospace', fontSize: '0.76rem', color, padding: '2px 0 2px 8px', lineHeight: 1.5, borderLeft: `2px solid ${color}30` }}>
                      <span style={{ color: C.muted, marginRight: 6 }}>{ev.timestamp?.slice(11, 19)}</span>
                      <span style={{ opacity: 0.7, marginRight: 6 }}>{nLabel(node)}</span>
                      <span style={{ color: '#0f172a', opacity: 0.6, marginRight: 4 }}>{node}</span>
                      &mdash; {result}
                    </div>
                  )
                })}
              </div>
            </Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {status === 'done' && total > 0 && (
                <Card style={{ textAlign: 'center' }}>
                  <p style={{ fontSize: '0.65rem', fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.1em', color: C.muted, marginBottom: 10 }}>Final Outcome</p>
                  <div style={{ display: 'flex', justifyContent: 'center', gap: 24, marginBottom: 12 }}>
                    {[{ n: saved.length, label: 'Confirmed', color: C.green }, { n: missed.length, label: 'Missed', color: C.red }, { n: notifications.length, label: 'Notified', color: C.blue }].map(({ n, label, color }) => (
                      <div key={label}><p style={{ fontSize: '1.8rem', fontWeight: 700, color }}>{n}</p><p style={{ fontSize: '0.7rem', color: C.muted }}>{label}</p></div>
                    ))}
                  </div>
                  <div style={{ background: C.border, borderRadius: 4, height: 8, overflow: 'hidden', marginBottom: 4 }}>
                    <div style={{ background: C.green, height: '100%', width: `${pct}%`, transition: 'width 0.6s' }} />
                  </div>
                  <p style={{ fontSize: '0.72rem', color: C.muted }}>Recovery rate: <strong>{pct}%</strong> (vs 34% manual baseline)</p>
                </Card>
              )}
              {status === 'done' && notifications.length > 0 && (
                <Card>
                  <SLabel>Passenger Notifications — Automatic</SLabel>
                  {notifications.slice(0, 10).map((n: Notification, i: number) => {
                    const ico = n.type === 'RECOVERED' ? '✅' : n.type === 'AT_RISK' ? '⚠️' : '❌'
                    const col = n.type === 'RECOVERED' ? C.green : n.type === 'AT_RISK' ? C.amber : C.red
                    return (
                      <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '3px 0', fontSize: '0.75rem' }}>
                        <span>{ico}</span>
                        <span style={{ fontFamily: 'monospace', color: col, fontWeight: 600, fontSize: '0.68rem' }}>{n.type}</span>
                        <span style={{ color: C.slate }}>{n.passenger_id}</span>
                        <span style={{ fontFamily: 'monospace', color: C.muted, fontSize: '0.68rem' }}>{n.bag_tag}</span>
                      </div>
                    )
                  })}
                </Card>
              )}
            </div>
          </div>
        )}

        {/* ── 8. WORKFLOWS ── */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>All 10 Disruption Workflows — Implemented</SLabel>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10 }}>
            {WORKFLOWS.map(w => (
              <div key={w.id} style={{ background: '#f8fafc', borderRadius: 7, padding: '12px 14px', border: `1px solid ${C.border}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.68rem', fontWeight: 700, color: C.blue, background: '#dbeafe', padding: '2px 6px', borderRadius: 4 }}>{w.id}</span>
                  <span style={{ fontWeight: 600, fontSize: '0.8rem', color: '#0f172a' }}>{w.name}</span>
                </div>
                <p style={{ fontSize: '0.74rem', color: C.slate, lineHeight: 1.5 }}>{w.desc}</p>
              </div>
            ))}
          </div>
        </Card>

        {/* ── 9. MEASUREMENT ── */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>Measurement — How We Proved It Works</SLabel>
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 24, alignItems: 'center' }}>
            <div>
              <p style={{ fontSize: '0.85rem', color: C.slate, lineHeight: 1.7, marginBottom: 10 }}>
                <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: 4, fontFamily: 'monospace', fontSize: '0.78rem' }}>python demo/replay.py</code> runs 5 disruption scenarios through the full agent stack and compares against a manual baseline.
              </p>
              <p style={{ fontSize: '0.82rem', color: C.slate, lineHeight: 1.7 }}>
                <strong>Manual baseline:</strong> a human coordinator saving at most 3 bags per phone call, handling one inbound at a time.
                The improvement comes entirely from <strong>parallelism</strong> — not from AI being smarter than a human coordinator.
              </p>
            </div>
            <div style={{ background: '#f0fdf4', border: `1px solid #bbf7d0`, borderRadius: 8, padding: '16px 20px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
                {[
                  { label: 'System', val: '74%', sub: 'bags recovered', color: C.green },
                  { label: 'Manual', val: '34%', sub: 'bags recovered', color: C.slate },
                  { label: 'System', val: '2.5s', sub: 'decision time', color: C.green },
                  { label: 'Manual', val: '~3 min', sub: 'decision time', color: C.slate },
                ].map(({ label, val, sub, color }, i) => (
                  <div key={i}>
                    <p style={{ fontSize: '0.65rem', color: C.muted, textTransform: 'uppercase' as const, letterSpacing: '0.08em', marginBottom: 2 }}>{label}</p>
                    <p style={{ fontSize: '1.3rem', fontWeight: 700, color, lineHeight: 1 }}>{val}</p>
                    <p style={{ fontSize: '0.68rem', color: C.muted }}>{sub}</p>
                  </div>
                ))}
              </div>
              <p style={{ fontSize: '0.72rem', color: C.green, fontWeight: 600 }}>&#43;40 percentage points recovered</p>
            </div>
          </div>
        </Card>

        {/* ── 10. OVERRIDE ── */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>Human Override — Intervene in Any Agent Decision</SLabel>
          <p style={{ fontSize: '0.82rem', color: C.slate, marginBottom: 14, lineHeight: 1.6 }}>
            Advisory &rarr; Semi-autonomous &rarr; Full autonomous mode progression. An AOCC operator can override any agent decision at any time and inject it into the live event stream.
          </p>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' as const, alignItems: 'flex-end' }}>
            {[
              { label: 'Decision', el: <select value={ov.decision} onChange={e => setOv(p => ({ ...p, decision: e.target.value }))} style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', fontSize: '0.85rem' }}><option>HOLD</option><option>DEPART</option><option>ESCALATE</option></select> },
              { label: 'Flight', el: <input value={ov.flight} onChange={e => setOv(p => ({ ...p, flight: e.target.value }))} style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', fontSize: '0.85rem', width: 80 }} /> },
              { label: 'Operator', el: <input value={ov.operator} onChange={e => setOv(p => ({ ...p, operator: e.target.value }))} style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', fontSize: '0.85rem', width: 100 }} /> },
            ].map(({ label, el }) => (
              <div key={label}>
                <p style={{ fontSize: '0.7rem', fontWeight: 600, color: C.muted, marginBottom: 4, textTransform: 'uppercase' as const, letterSpacing: '0.08em' }}>{label}</p>
                {el}
              </div>
            ))}
            <div style={{ flex: 1, minWidth: 200 }}>
              <p style={{ fontSize: '0.7rem', fontWeight: 600, color: C.muted, marginBottom: 4, textTransform: 'uppercase' as const, letterSpacing: '0.08em' }}>Note</p>
              <input value={ov.note} onChange={e => setOv(p => ({ ...p, note: e.target.value }))} placeholder="e.g. VIP passenger on AA401 — hold 3 min" style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', fontSize: '0.85rem', width: '100%' }} />
            </div>
            <button onClick={submitOv} style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer' }}>Submit Override</button>
          </div>
          {ovMsg && <p style={{ fontSize: '0.8rem', color: C.green, marginTop: 8 }}>{ovMsg}</p>}
        </Card>

        <footer style={{ textAlign: 'center', color: C.muted, fontSize: '0.75rem', paddingTop: 16, borderTop: `1px solid ${C.border}` }}>
          Built by <strong>dCortex</strong> &middot; LangGraph &middot; OR-Tools CP-SAT + MIP &middot; Gemini &middot; Redpanda &middot; FastAPI
        </footer>

      </main>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
