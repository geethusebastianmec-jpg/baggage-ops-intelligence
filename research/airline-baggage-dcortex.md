# Airline Baggage Handling — Current State & dCortex Opportunity

## 1. How Baggage Handling Works Today

Baggage handling is a multi-step physical and digital chain:

1. **Check-in** — bag tagged with barcode/RFID, weight checked, destination encoded
2. **Screening** — CT scanners for security (TSA-mandated)
3. **Sorting** — conveyor belts route bags to the correct flight via automated sorting systems (BEUMER, Vanderlande)
4. **Loading** — ground crews load bags into aircraft holds manually
5. **Transfer** — for connecting flights, bags must be physically moved between aircraft, often within tight time windows
6. **Claim** — bags routed to the correct carousel via BHS (Baggage Handling System) software

---

## 2. The Core Problems

| Problem | Scale |
|---|---|
| Total mishandled bags (2024) | 33.4 million |
| Industry cost | ~$5 billion/year |
| Cost per mishandled bag | ~$150 |
| Biggest cause | Transfer misconnections (41%) |
| Loading failures | 16% |

- ~74% of mishandled bags are delayed (not permanently lost)
- International flights have significantly higher mishandling rates than domestic
- A single delayed bag can require reopening an aircraft hold, adjusting load data, and stalling the entire turnaround — cascading into gate delays, crew schedule conflicts, and network-wide disruptions

### Hidden Costs Beyond Claims

The visible $5B/year figure masks larger losses scattered across:
- Unplanned labor for bag searches and recovery
- Contractor coordination and courier services
- Productivity loss from staff diverted to exceptions
- Turnaround delays and downstream network disruptions
- Injury risk from heavy manual handling
- Brand damage and passenger retention losses

---

## 3. Current Technology Landscape

| Technology | Description | Limitation |
|---|---|---|
| RFID tracking | ~80% read accuracy | Not universal; siloed per airport |
| BHS software (SITA WorldTracer, Amadeus, IBS) | Tracks bags per airport/airline | No real-time cross-airline visibility |
| CT scanners | Automated security screening | Still generates false alarms needing human review |
| Robotics (Aurrigo, Journey Robotics) | Autonomous bag tractors at select airports | Early-stage, hardware-specific |
| Passenger notifications | Real-time bag location updates | Only 42% of passengers receive them (2024) |

### The Fundamental Gap

All these systems are **fragmented**. The airline operations control center (AOCC), ground handlers, ramp crew, and baggage service offices each operate separate tools that don't communicate in real time. Decisions happen **reactively** — after a problem has already cascaded through the operation.

---

## 4. dCortex.ai — Company Overview

- **Stage:** Stealth-mode startup
- **Location:** San Francisco Bay Area
- **Team size:** 11–50 people
- **Mission:** Building "operational superintelligence" — coordinated multi-agent AI that reasons and acts across complex operations in real time
- **Target market:** $1 trillion addressable market; enterprise operations
- **Live deployments:** Already deployed in large-scale airline environments
- **Target verticals:** Enterprise Software, General Aviation

dCortex is a multi-agent system where agents operate in tandem, continuously sensing, reasoning, and evolving with the environment. It is designed for environments where complexity is inherent, decisions are continuous, and outcomes cannot be predefined upfront.

---

## 5. How dCortex Addresses the Baggage Problem

### The Coordination Failure dCortex Targets

The 41% of mishandling from transfer failures is almost entirely a **coordination and timing problem**, not a hardware problem. A bag gets left behind because no single system connected the flight delay, the transfer bag manifest, the ramp crew schedule, and the departure gate status in time for a human to act.

### How the Multi-Agent Approach Works

Instead of isolated tools, dCortex deploys a multi-agent coordinator that:

- **Senses** across systems simultaneously — flight delays, load plans, transfer windows, ramp status, equipment state
- **Reasons** over interdependencies — e.g., Flight A is delayed 20 min → 3 bags on transfer to Flight B → Flight B departs in 25 min → initiate exception routing + notify ramp + flag load plan update, all automatically
- **Acts** in real time — coordinating across agents that own different domains (dispatch, ramp, baggage service, customer comms) without human handoffs between fragmented tools

### Competitive Differentiation

| | Traditional BHS (SITA, Amadeus) | Robotics (Aurrigo, Journey) | dCortex |
|---|---|---|---|
| **Focus** | Tracking & record-keeping | Physical automation | Real-time operational coordination |
| **Response style** | Reactive (report after event) | Automates fixed physical tasks | Proactive (acts before cascade) |
| **Cross-system** | Siloed per airport/airline | Hardware-specific | Multi-system, multi-agent |
| **Adapts to disruption** | Minimal | No | Core capability |

---

## 6. Market Context

- Airport baggage handling systems market: **$2.46B (2025)**, projected to reach **$4.21B by 2031**
- Long-term market: **$13.64B by 2033** (driven by regulatory mandates for hardware upgrades)
- SITA's Modern Baggage Messaging (MBM) v2 standard (approved 2025) expected to reduce mishandling by another 5%
- Industry trend: shift from hardware investment toward AI/software coordination layer

---

## 7. Key Insight

The airline baggage industry's $5B/year problem is primarily a **coordination failure**, not a hardware failure. The physical infrastructure (conveyors, scanners, RFID) exists. What's missing is an intelligence layer that operates across all systems simultaneously and acts before problems cascade. That is precisely the gap dCortex is positioned to fill.

---

## Sources

- [SITA Baggage IT Insights 2025](https://www.sita.aero/resources/surveys-reports/sita-baggage-it-insights-2025)
- [Mishandled Baggage Costs — Quantum Aero](https://quantum.aero/mishandled-baggage-costs-2/)
- [Infosys: How Agentic AI Can Improve Airline Baggage Handling](https://blogs.infosys.com/digital-experience/emerging-technologies/how-agentic-ai-can-improve-airline-baggage-handling.html)
- [Airport Baggage Handling Market Report — GlobeNewswire (2024–2030)](https://www.globenewswire.com/news-release/2025/01/22/3013314/28124/en/Airport-Baggage-Handling-Systems-Global-Analysis-Report-2024-2030-Rising-Focus-on-Minimizing-Baggage-Mishandling-Accelerates-Adoption-of-Innovative-Baggage-Tracking-Systems.html)
- [Airport Baggage Handling Market — Astute Analytica (to 2033)](https://www.globenewswire.com/news-release/2025/12/08/3201723/0/en/Airport-Baggage-Handling-Systems-Market-Set-to-Reach-US-13-64-Billion-by-2033-as-Global-Regulatory-Mandates-Drive-Capital-Intensive-Hardware-Upgrades-Says-Astute-Analytica.html)
- [dCortex website](https://dcortex.ai/)
- [dCortex — LinkedIn](https://www.linkedin.com/company/dcortex)
- [dCortex — Wellfound](https://wellfound.com/company/dcortex)
