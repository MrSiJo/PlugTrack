/**
 * Sessions store — placeholder.
 *
 * TODO Phase 3: list/create/update/delete charging sessions, paginate,
 * and cache derived metrics from the backend so the UI doesn't have to
 * recompute pence-per-mile etc.
 */
import { create } from 'zustand'

export interface ChargingSessionStub {
  id: number
  // TODO Phase 3 — full shape per backend ChargingSession model.
}

export interface SessionsStoreState {
  sessions: ChargingSessionStub[]
  loaded: boolean
}

export const useSessionsStore = create<SessionsStoreState>(() => ({
  sessions: [],
  loaded: false,
}))
