/**
 * Sync store — placeholder.
 *
 * TODO Phase 4: wire to GET /api/sync/stream (SSE) for live status, and
 * POST /api/sync/refresh for manual triggers. Will track:
 *   - last successful sync timestamp
 *   - current state (idle | plugged | charging)
 *   - in-flight refresh requests
 */
import { create } from 'zustand'

export type SyncState = 'idle' | 'plugged' | 'charging' | 'unknown'

export interface SyncStoreState {
  // TODO Phase 4 — populate from SSE stream.
  state: SyncState
  lastSyncAt: string | null
}

export const useSyncStore = create<SyncStoreState>(() => ({
  state: 'unknown',
  lastSyncAt: null,
}))
