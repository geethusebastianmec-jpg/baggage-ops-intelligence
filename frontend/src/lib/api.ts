import axios from 'axios'
import type { ScenarioState } from '../types'

const BASE = '/api'

export const api = {
  health: () => axios.get(`${BASE}/health`).then(r => r.data),
  runScenario: () => axios.post(`${BASE}/scenario/run`).then(r => r.data),
  getState: (): Promise<ScenarioState> => axios.get(`${BASE}/scenario/state`).then(r => r.data),
  override: (payload: object) => axios.post(`${BASE}/override`, payload).then(r => r.data),
}
