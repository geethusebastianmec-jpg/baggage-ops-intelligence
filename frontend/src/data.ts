import type { Flight, BagRow } from './types'

export const FLIGHTS: Flight[] = [
  { id:'AA401', route:'ORD → JFK', status:'DELAYED', delta:'+32 min', bags:'7 bags → AA501', cssClass:'delayed' },
  { id:'AA402', route:'LAX → JFK', status:'DELAYED', delta:'+18 min', bags:'3 bags → AA501', cssClass:'delayed' },
  { id:'AA403', route:'MIA → JFK', status:'DELAYED', delta:'+11 min', bags:'2 bags → AA502', cssClass:'ok' },
  { id:'AA501', route:'JFK → LHR', status:'ON_TIME',  delta:'25 min',  bags:'outbound · London', cssClass:'ok' },
  { id:'AA502', route:'JFK → CDG', status:'ON_TIME',  delta:'40 min',  bags:'outbound · Paris',  cssClass:'ok' },
]

export const BAGS: BagRow[] = [
  { tag:'BA-001', zone:'Zone B', moveMins:8,  slack:17,  outbound:'AA501', defaultStatus:'at-risk' },
  { tag:'BA-002', zone:'Zone B', moveMins:8,  slack:17,  outbound:'AA501', defaultStatus:'at-risk' },
  { tag:'BA-003', zone:'Zone B', moveMins:8,  slack:17,  outbound:'AA501', defaultStatus:'at-risk' },
  { tag:'BA-004', zone:'Zone B', moveMins:8,  slack:17,  outbound:'AA501', defaultStatus:'at-risk' },
  { tag:'BA-005', zone:'Zone B', moveMins:8,  slack:17,  outbound:'AA501', defaultStatus:'at-risk' },
  { tag:'BA-006', zone:'Zone D', moveMins:26, slack:-1,  outbound:'AA501', defaultStatus:'impossible' },
  { tag:'BA-007', zone:'Zone D', moveMins:26, slack:-1,  outbound:'AA501', defaultStatus:'impossible' },
  { tag:'BA-008', zone:'Zone B', moveMins:8,  slack:17,  outbound:'AA501', defaultStatus:'at-risk' },
  { tag:'BA-009', zone:'Zone B', moveMins:8,  slack:17,  outbound:'AA501', defaultStatus:'at-risk' },
  { tag:'BA-010', zone:'Zone B', moveMins:8,  slack:17,  outbound:'AA501', defaultStatus:'at-risk' },
  { tag:'BA-011', zone:'Zone C', moveMins:10, slack:30,  outbound:'AA502', defaultStatus:'safe' },
  { tag:'BA-012', zone:'Zone C', moveMins:10, slack:30,  outbound:'AA502', defaultStatus:'safe' },
  { tag:'BA-013', zone:'Zone C', moveMins:10, slack:30,  outbound:'LH dep', defaultStatus:'safe' },   // interline → LH
  { tag:'BA-014', zone:'Zone C', moveMins:10, slack:30,  outbound:'LH dep', defaultStatus:'safe' },   // interline → LH
]

export const WORKFLOWS = [
  { id:'W1', name:'Flight delay',        desc:'Triage (slack math) → CP-SAT if crew contended → exception routing → confirming scan' },
  { id:'W2', name:'Gate change',         desc:'Find bags sorted to old chute → BHS divert → crew reassignment → load plan' },
  { id:'W3', name:'Cancellation',        desc:'MIP rebook on next flight ‖ off-load bags already in hold → MISSED notify' },
  { id:'W4', name:'Equipment failure',   desc:'Identify impacted bags → alternate BHS path → maintenance alert → re-triage' },
  { id:'W5', name:'Loading failure',     desc:'Locate bag → check if flight still at gate → emergency load or MIP rebook' },
  { id:'W6', name:'Crew shortage',       desc:'Check adjacent zones (B↔C↔D) before escalating to AOCC supervisor' },
  { id:'W7', name:'Security hold',       desc:'Place hold → notify passenger + baggage service → HITL: cleared→rebook / rejected→law enforcement' },
  { id:'W8', name:'Network cascade',     desc:'Joint CP-SAT across ALL at-risk bags from multiple delayed inbounds under shared crew constraint' },
  { id:'W9', name:'Interline bags',      desc:'IATA Type B alert to partner airline · transfer desk alert · passengers flagged even with positive slack (no direct BHS control cross-airline)' },
  { id:'W10', name:'GSP coordination',  desc:'Airline-direct vs Swissport/Menzies/dnata dispatch routing · GSP zones have longer ETA and probabilistic SLA' },
]

export const TIERS = [
  { id:'T0',  tool:'DB read',  color:'#64748b', desc:'Where is bag X? Crew status? GSP or airline-direct?' },
  { id:'T1',  tool:'Rules',    color:'#64748b', desc:'slack = window − move_time · Hold vs depart cost ($150/bag vs $500/min)' },
  { id:'T2a', tool:'CP-SAT',   color:'#0066cc', desc:'Which bags to rush under crew contention? CREW bags prioritised (IATA P1)' },
  { id:'T2b', tool:'MIP',      color:'#0284c7', desc:'Which flight for each missed bag? Capacity-constrained, priority-weighted' },
  { id:'T3',  tool:'Agent',    color:'#7c3aed', desc:'Sequences T1/T2 · Routes to GSP or airline-direct · Activates interline coordinator' },
  { id:'T4',  tool:'LLM',      color:'#d97706', desc:'Novel compound events no playbook covers — routing only, never computes' },
]

export const NODE_LABELS: Record<string, string> = {
  prepare_context:'QRY', fetch_departure:'CLK', fetch_ramp:'CRW',
  triage_and_optimize:'TRG', close_loop:'CNF', route_bags:'RTE',
  flag_missed:'MSD', check_crew:'CRW', pull_adjacent_crew:'ADJ',
  assign_task:'TSK', escalate:'ESC', decide_hold:'HLD',
  fetch_load_plan:'LDP', send_notifications:'SMS',
  find_affected_bags:'QRY', divert_bags:'DVT', reassign_crew:'ADJ',
  rebook_bags:'RBK', offload_loaded:'OFL', locate_bag:'LOC',
  emergency_load:'EMG', place_hold:'HLD', escalate_to_authority:'SEC',
  alert_maintenance:'MNT', assess_impact:'TRG',
  aggregate_cascade:'AGG', joint_triage:'TRG', joint_optimize:'OPT', dispatch_all:'RTE',
}
