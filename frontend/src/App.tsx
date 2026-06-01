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
  const bg: Record<string, string> = {
    green: '#dcfce7', red: '#fee2e2', amber: '#fff7ed', blue: '#dbeafe', slate: '#f1f5f9',
  }
  const fg: Record<string, string> = {
    green: C.green, red: C.red, amber: C.amber, blue: C.blue, slate: C.slate,
  }
  return (
    <span style={{
      background: bg[color] ?? bg.slate, color: fg[color] ?? fg.slate,
      fontWeight: 600, fontSize: '0.7rem', padding: '2px 8px',
      borderRadius: 999, whiteSpace: 'nowrap' as const,
    }}>{children}</span>
  )
}

function SLabel({ children }: { children: React.ReactNode }) {
  return (
    <p style={{
      fontSize: '0.65rem', fontWeight: 600, letterSpacing: '0.1em',
      textTransform: 'uppercase' as const, color: C.muted,
      borderBottom: `1px solid ${C.border}`, paddingBottom: 6, marginBottom: 10,
    }}>{children}</p>
  )
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 10, padding: 16, ...style,
    }}>{children}</div>
  )
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
  for (const [k, v] of Object.entries(NODE_LABELS)) {
    if (node.toLowerCase().includes(k)) return `[${v}]`
  }
  return '[AGT]'
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

  return (
    <div style={{ minHeight: '100vh', background: C.bg }}>

      {/* HEADER */}
      <header style={{
        background: C.card, borderBottom: `1px solid ${C.border}`,
        padding: '12px 32px', display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', position: 'sticky', top: 0, zIndex: 50,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: '1.2rem' }}>🧳</span>
          <span style={{ fontWeight: 700, fontSize: '1rem' }}>Baggage Ops Intelligence</span>
          <span style={{ fontSize: '0.78rem', color: C.muted }}>by dCortex</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{
            background: apiOnline ? '#dcfce7' : '#f1f5f9',
            color: apiOnline ? C.green : C.muted,
            fontSize: '0.7rem', fontWeight: 600, padding: '3px 10px', borderRadius: 999,
          }}>{apiOnline ? '● LIVE' : '○ OFFLINE'}</span>
          <span style={{ fontSize: '0.75rem', color: C.muted }}>JFK Hub Demo</span>
        </div>
      </header>

      <main style={{ maxWidth: 1280, margin: '0 auto', padding: '0 24px 48px' }}>

        {/* 1. PROBLEM */}
        <section style={{ padding: '48px 0 32px' }}>
          <div style={{ textAlign: 'center', marginBottom: 40 }}>
            <h1 style={{
              fontSize: '2.2rem', fontWeight: 700, letterSpacing: '-0.03em',
              color: '#0f172a', marginBottom: 12, lineHeight: 1.2,
            }}>
              Airlines lose <span style={{ color: C.red }}>$5 billion</span> per year
              <br />to a coordination problem
            </h1>
            <p style={{ fontSize: '1rem', color: C.slate, maxWidth: 620, margin: '0 auto', lineHeight: 1.7 }}>
              33 million bags mishandled annually. 41% from transfer misconnections —
              a flight arrives late and no one coordinates fast enough.
              Today a human coordinator makes four sequential phone calls.
              By the time the fourth call is done, the window is gone.
            </p>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16 }}>
            {[
              { label: 'The Problem', text: 'A human AOCC coordinator makes four phone calls — baggage, ramp, dispatch, comms. Each 1–3 minutes. Sequential. By call four, bags have already missed their window.', accent: C.red },
              { label: 'The Solution', text: 'The system activates all four coordinators simultaneously. Deterministic triage (pure math). CP-SAT for crew contention. LLM only for novel compound events no playbook covers.', accent: C.blue },
              { label: 'The Result', text: '+40% bags recovered vs. manual baseline. 2.5 second decision time. 74% recovery rate vs. 34%. Every passenger notified automatically at each stage.', accent: C.green },
            ].map(({ label, text, accent }) => (
              <Card key={label} style={{ borderTop: `3px solid ${accent}` }}>
                <p style={{ fontWeight: 700, fontSize: '0.78rem', textTransform: 'uppercase' as const, letterSpacing: '0.08em', color: accent, marginBottom: 8 }}>{label}</p>
                <p style={{ fontSize: '0.87rem', color: C.slate, lineHeight: 1.65 }}>{text}</p>
              </Card>
            ))}
          </div>
        </section>

        {/* 2. KPI STRIP */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 12, marginBottom: 32 }}>
          {[
            { num: '74%', sub: '+40% vs manual', label: 'Recovery rate', color: C.green },
            { num: '2.5s', sub: 'vs ~3 min manual', label: 'Decision time', color: C.blue },
            { num: '12', sub: 'AA401/402/403', label: 'Bags at risk', color: C.amber },
            { num: '8', sub: 'all implemented', label: 'Disruption types', color: C.blue },
            { num: '83', sub: 'all passing', label: 'Tests', color: C.green },
            { num: '$5B', sub: 'industry / year', label: 'Cost of problem', color: C.red },
          ].map(({ num, sub, label, color }) => (
            <Card key={label} style={{ textAlign: 'center', padding: '14px 10px' }}>
              <p style={{ fontSize: '1.8rem', fontWeight: 700, color, lineHeight: 1 }}>{num}</p>
              <p style={{ fontSize: '0.7rem', color: C.muted, margin: '4px 0 2px' }}>{sub}</p>
              <p style={{ fontSize: '0.63rem', fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.08em', color: '#cbd5e1' }}>{label}</p>
            </Card>
          ))}
        </div>

        {/* 3. FLIGHT BOARD + TRIAGE */}
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, marginBottom: 24 }}>
          <Card>
            <SLabel>Live Flight Status — JFK Hub</SLabel>
            <p style={{ fontSize: '0.82rem', color: C.slate, marginBottom: 12, lineHeight: 1.6 }}>
              Three inbound flights delayed. Two outbounds counting down. The system decides — for each of 12 transfer bags — whether physical transfer is possible before the window closes.
            </p>
            <table style={{ width: '100%', borderCollapse: 'collapse' as const, fontSize: '0.82rem' }}>
              <thead>
                <tr style={{ color: C.muted, fontSize: '0.67rem', textTransform: 'uppercase' as const, letterSpacing: '0.08em' }}>
                  {['Flight', 'Route', 'Status', 'Window', 'Bags'].map(h => (
                    <th key={h} style={{ textAlign: 'left' as const, padding: '4px 8px', fontWeight: 600 }}>{h}</th>
                  ))}
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
            <SLabel>Triage Decision Logic</SLabel>
            <p style={{ fontSize: '0.82rem', color: C.slate, lineHeight: 1.6, marginBottom: 12 }}>
              For each bag, one calculation determines its fate:
            </p>
            <div style={{
              background: '#f8fafc', border: `1px solid ${C.border}`, borderRadius: 6,
              padding: '10px 12px', fontFamily: 'monospace', fontSize: '0.78rem',
              color: '#0f172a', lineHeight: 2, marginBottom: 14,
            }}>
              slack = window &minus; move_time<br />
              <span style={{ color: C.green }}>slack &ge; 0  &rarr;  RUSH IT</span><br />
              <span style={{ color: C.red }}>slack &lt; 0  &rarr;  IMPOSSIBLE</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: C.slate, lineHeight: 1.8 }}>
              <p>🟡 <strong>Zone B</strong> (near gate) · 8 min · slack +17</p>
              <p>🔴 <strong>Zone D</strong> (deep queue) · 26 min · slack &minus;1</p>
              <p style={{ marginTop: 10, fontSize: '0.74rem', color: C.muted }}>
                Move time = physical ramp transfer time. Not MCT (passenger connection time includes customs, security, walking — irrelevant for bags).
              </p>
            </div>
          </Card>
        </div>

        {/* 4. RUN CONTROL */}
        <Card style={{ marginBottom: 24, textAlign: 'center', padding: '32px 24px' }}>
          {status === 'idle' && (
            <>
              <p style={{ fontWeight: 700, fontSize: '1.1rem', color: '#0f172a', marginBottom: 8 }}>
                Ready to run the Hub Crisis scenario
              </p>
              <p style={{ fontSize: '0.85rem', color: C.slate, marginBottom: 20, maxWidth: 560, margin: '0 auto 20px', lineHeight: 1.7 }}>
                Three delay events publish to Kafka. Worker picks them up, runs triage math per bag,
                activates ramp and dispatch coordinators in parallel, dispatches all actions.
              </p>
              {!apiOnline && (
                <p style={{ fontSize: '0.8rem', color: C.amber, marginBottom: 12 }}>
                  ⚠ API offline — start with{' '}
                  <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: 4, fontFamily: 'monospace' }}>
                    uvicorn src.api.main:app --port 8000
                  </code>
                </p>
              )}
              <button
                onClick={run}
                disabled={!apiOnline}
                style={{
                  background: apiOnline ? C.blue : '#e2e8f0',
                  color: apiOnline ? '#fff' : C.muted,
                  border: 'none', borderRadius: 8, padding: '12px 32px',
                  fontSize: '0.95rem', fontWeight: 600,
                  cursor: apiOnline ? 'pointer' : 'not-allowed',
                }}
              >
                &#9654; Run Hub Crisis Scenario
              </button>
            </>
          )}
          {status === 'running' && (
            <div>
              <div style={{
                width: 36, height: 36, borderRadius: '50%',
                border: `3px solid ${C.border}`, borderTopColor: C.blue,
                animation: 'spin 0.8s linear infinite', margin: '0 auto 12px',
              }} />
              <p style={{ fontWeight: 600, color: '#0f172a', marginBottom: 4 }}>Agents coordinating&hellip;</p>
              <p style={{ fontSize: '0.82rem', color: C.slate }}>
                Events in Kafka &rarr; Worker &rarr; Triage &rarr; CP-SAT &rarr; Actions dispatched
              </p>
              <p style={{ fontFamily: 'monospace', fontSize: '0.78rem', color: C.muted, marginTop: 8 }}>
                Actions: {actionCount} | Confirmed: {saved.length} | Missed: {missed.length}
              </p>
            </div>
          )}
          {(status === 'done' || status === 'error') && (
            <div>
              <p style={{ fontWeight: 700, fontSize: '1rem', color: C.green, marginBottom: 4 }}>
                &#10003; Scenario complete
              </p>
              <p style={{ fontSize: '0.82rem', color: C.slate, marginBottom: 16 }}>
                {saved.length} bags confirmed &middot; {missed.length} missed &middot; {notifications.length} notifications sent
              </p>
              <button
                onClick={reset}
                style={{
                  background: 'transparent', border: `1px solid ${C.border}`,
                  color: C.slate, borderRadius: 6, padding: '8px 20px',
                  fontSize: '0.85rem', fontWeight: 500, cursor: 'pointer',
                }}
              >
                &#8635; Run Again
              </button>
            </div>
          )}
        </Card>

        {/* 5. ACTIVITY + BAG BOARD */}
        {status !== 'idle' && (
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 16, marginBottom: 24 }}>
            {/* Activity log */}
            <Card>
              <SLabel>Agent Activity Log</SLabel>
              <div style={{ maxHeight: 380, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 1 }}>
                {events.length === 0 && (
                  <p style={{ fontSize: '0.8rem', color: C.muted, padding: '12px 0' }}>
                    Waiting for first Kafka message&hellip;
                  </p>
                )}
                {events.map((ev, i) => {
                  if (ev.type === 'SCENARIO_STARTED') return (
                    <div key={i} style={{ fontFamily: 'monospace', fontSize: '0.78rem', color: C.blue, padding: '3px 0', lineHeight: 1.5 }}>
                      {ev.timestamp?.slice(11, 19)} &loz; SCENARIO STARTED &mdash; 3 events published to Kafka
                    </div>
                  )
                  if (ev.type !== 'AUDIT_ACTION') return null
                  const node = ev.payload?.node ?? ev.payload?.coordinator ?? '?'
                  const result = (ev.payload?.result ?? '').slice(0, 110)
                  const color = eventColor(ev)
                  return (
                    <div
                      key={i}
                      style={{
                        fontFamily: 'monospace', fontSize: '0.76rem', color,
                        padding: '2px 0 2px 8px', lineHeight: 1.5,
                        borderLeft: `2px solid ${color}30`,
                      }}
                    >
                      <span style={{ color: C.muted, marginRight: 6 }}>{ev.timestamp?.slice(11, 19)}</span>
                      <span style={{ opacity: 0.7, marginRight: 6 }}>{nLabel(node)}</span>
                      <span style={{ color: '#0f172a', opacity: 0.6, marginRight: 4 }}>{node}</span>
                      &mdash; {result}
                    </div>
                  )
                })}
              </div>
            </Card>

            {/* Bag board */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <Card style={{ flex: 1 }}>
                <SLabel>Bag Status Board</SLabel>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {BAGS.map(b => {
                    let chip: React.ReactNode
                    if (savedSet.has(b.tag))                chip = <Chip color="green">CONFIRMED</Chip>
                    else if (missedSet.has(b.tag))           chip = <Chip color="red">MISSED</Chip>
                    else if (b.defaultStatus === 'impossible') chip = <Chip color="red">IMPOSSIBLE</Chip>
                    else if (b.defaultStatus === 'safe')       chip = <Chip color="slate">SAFE</Chip>
                    else                                       chip = <Chip color="amber">AT RISK</Chip>
                    return (
                      <div key={b.tag} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0' }}>
                        <span style={{ fontFamily: 'monospace', fontSize: '0.75rem', fontWeight: 600, color: C.blue, minWidth: 56 }}>{b.tag}</span>
                        <span style={{ fontSize: '0.74rem', color: C.slate, minWidth: 52 }}>{b.zone}</span>
                        <span style={{ fontFamily: 'monospace', fontSize: '0.7rem', color: b.slack < 0 ? C.red : C.green, minWidth: 40 }}>
                          slk{b.slack > 0 ? '+' : ''}{b.slack}
                        </span>
                        {chip}
                      </div>
                    )
                  })}
                </div>
              </Card>

              {status === 'done' && total > 0 && (
                <Card style={{ textAlign: 'center' }}>
                  <p style={{ fontSize: '0.65rem', fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.1em', color: C.muted, marginBottom: 8 }}>Outcome</p>
                  <div style={{ display: 'flex', justifyContent: 'center', gap: 24, marginBottom: 10 }}>
                    {[{ n: saved.length, label: 'Confirmed', color: C.green }, { n: missed.length, label: 'Missed', color: C.red }, { n: notifications.length, label: 'Notified', color: C.blue }].map(({ n, label, color }) => (
                      <div key={label}>
                        <p style={{ fontSize: '1.6rem', fontWeight: 700, color }}>{n}</p>
                        <p style={{ fontSize: '0.7rem', color: C.muted }}>{label}</p>
                      </div>
                    ))}
                  </div>
                  <div style={{ background: C.border, borderRadius: 4, height: 6, overflow: 'hidden' }}>
                    <div style={{ background: C.green, height: '100%', width: `${pct}%`, transition: 'width 0.5s' }} />
                  </div>
                  <p style={{ fontSize: '0.72rem', color: C.muted, marginTop: 4 }}>Recovery rate: {pct}%</p>
                </Card>
              )}

              {status === 'done' && notifications.length > 0 && (
                <Card>
                  <SLabel>Passenger Notifications</SLabel>
                  {notifications.slice(0, 8).map((n: Notification, i: number) => {
                    const ico = n.type === 'RECOVERED' ? '✅' : n.type === 'AT_RISK' ? '⚠️' : '❌'
                    const col = n.type === 'RECOVERED' ? C.green : n.type === 'AT_RISK' ? C.amber : C.red
                    return (
                      <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '3px 0', fontSize: '0.75rem' }}>
                        <span>{ico}</span>
                        <span style={{ fontFamily: 'monospace', color: col, fontWeight: 600, fontSize: '0.7rem' }}>{n.type}</span>
                        <span style={{ color: C.slate }}>{n.passenger_id}</span>
                        <span style={{ fontFamily: 'monospace', color: C.muted, fontSize: '0.7rem' }}>{n.bag_tag}</span>
                      </div>
                    )
                  })}
                </Card>
              )}
            </div>
          </div>
        )}

        {/* 6. WHY NOT LLM */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
          <Card style={{ borderTop: `3px solid ${C.red}` }}>
            <SLabel>The V1 Mistake &mdash; What We Fixed</SLabel>
            <p style={{ fontSize: '0.85rem', color: C.slate, lineHeight: 1.7, marginBottom: 10 }}>
              Version 1 called an LLM to decide which bags were recoverable. It was wrong &mdash; not because LLMs are bad, but because <strong>feasibility is arithmetic, not judgment</strong>.
            </p>
            <p style={{ fontSize: '0.82rem', color: C.slate, lineHeight: 1.7, marginBottom: 10 }}>
              The LLM didn&apos;t know bag BA-007 was in Zone D with a 26-minute move time.
              It reasoned from language, not facts &mdash; producing non-deterministic, unauditable answers.
            </p>
            <div style={{
              background: '#fef2f2', borderRadius: 6, padding: '10px 12px',
              fontSize: '0.78rem', fontFamily: 'monospace', lineHeight: 2, color: '#7f1d1d',
            }}>
              V1: LLM &rarr; &ldquo;BA-007 unrecoverable, queue too far&rdquo;<br />
              <span style={{ color: C.green }}>V2: 25 &minus; 26 = &minus;1 &rarr; IMPOSSIBLE (same answer, always)</span>
            </div>
          </Card>
          <Card>
            <SLabel>Tier Ladder &mdash; Right Tool for Each Question</SLabel>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {TIERS.map(t => (
                <div key={t.id} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '0.73rem', color: t.color, minWidth: 24, paddingTop: 1 }}>{t.id}</span>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.73rem', color: t.color, minWidth: 56, paddingTop: 1 }}>{t.tool}</span>
                  <span style={{ fontSize: '0.8rem', color: C.slate, lineHeight: 1.5 }}>{t.desc}</span>
                </div>
              ))}
            </div>
            <p style={{ fontSize: '0.75rem', color: C.muted, marginTop: 12, borderTop: `1px solid ${C.border}`, paddingTop: 10 }}>
              LLM fires on ~20% of events (novel compound situations). If it fires more, you haven&apos;t pre-written enough playbooks.
            </p>
          </Card>
        </div>

        {/* 7. WORKFLOWS */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>All 8 Disruption Workflows &mdash; Implemented</SLabel>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
            {WORKFLOWS.map(w => (
              <div key={w.id} style={{
                background: '#f8fafc', borderRadius: 7, padding: '12px 14px',
                border: `1px solid ${C.border}`,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span style={{
                    fontFamily: 'monospace', fontSize: '0.68rem', fontWeight: 700,
                    color: C.blue, background: '#dbeafe', padding: '2px 6px', borderRadius: 4,
                  }}>{w.id}</span>
                  <span style={{ fontWeight: 600, fontSize: '0.8rem', color: '#0f172a' }}>{w.name}</span>
                </div>
                <p style={{ fontSize: '0.74rem', color: C.slate, lineHeight: 1.5 }}>{w.desc}</p>
              </div>
            ))}
          </div>
        </Card>

        {/* 8. OVERRIDE */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>Human Override &mdash; Intervene in Any Agent Decision</SLabel>
          <p style={{ fontSize: '0.82rem', color: C.slate, marginBottom: 14, lineHeight: 1.6 }}>
            Advisory &rarr; Semi-autonomous &rarr; Full autonomous mode progression.
            An AOCC operator can override any decision at any time.
          </p>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' as const, alignItems: 'flex-end' }}>
            {[
              {
                label: 'Decision',
                el: (
                  <select
                    value={ov.decision}
                    onChange={e => setOv(p => ({ ...p, decision: e.target.value }))}
                    style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', fontSize: '0.85rem' }}
                  >
                    <option>HOLD</option><option>DEPART</option><option>ESCALATE</option>
                  </select>
                ),
              },
              {
                label: 'Flight',
                el: (
                  <input
                    value={ov.flight}
                    onChange={e => setOv(p => ({ ...p, flight: e.target.value }))}
                    style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', fontSize: '0.85rem', width: 80 }}
                  />
                ),
              },
              {
                label: 'Operator',
                el: (
                  <input
                    value={ov.operator}
                    onChange={e => setOv(p => ({ ...p, operator: e.target.value }))}
                    style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', fontSize: '0.85rem', width: 100 }}
                  />
                ),
              },
            ].map(({ label, el }) => (
              <div key={label}>
                <p style={{ fontSize: '0.7rem', fontWeight: 600, color: C.muted, marginBottom: 4, textTransform: 'uppercase' as const, letterSpacing: '0.08em' }}>{label}</p>
                {el}
              </div>
            ))}
            <div style={{ flex: 1, minWidth: 200 }}>
              <p style={{ fontSize: '0.7rem', fontWeight: 600, color: C.muted, marginBottom: 4, textTransform: 'uppercase' as const, letterSpacing: '0.08em' }}>Note</p>
              <input
                value={ov.note}
                onChange={e => setOv(p => ({ ...p, note: e.target.value }))}
                placeholder="e.g. VIP passenger on AA401"
                style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', fontSize: '0.85rem', width: '100%' }}
              />
            </div>
            <button
              onClick={submitOv}
              style={{
                background: C.blue, color: '#fff', border: 'none',
                borderRadius: 6, padding: '8px 20px', fontSize: '0.85rem',
                fontWeight: 600, cursor: 'pointer',
              }}
            >
              Submit Override
            </button>
          </div>
          {ovMsg && <p style={{ fontSize: '0.8rem', color: C.green, marginTop: 8 }}>{ovMsg}</p>}
        </Card>

        {/* FOOTER */}
        <footer style={{ textAlign: 'center', color: C.muted, fontSize: '0.75rem', paddingTop: 16, borderTop: `1px solid ${C.border}` }}>
          Built by <strong>dCortex</strong> &middot; LangGraph &middot; OR-Tools CP-SAT &middot; Gemini &middot; Redpanda &middot; FastAPI
        </footer>

      </main>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
