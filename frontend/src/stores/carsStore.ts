/**
 * Cars store — placeholder.
 *
 * TODO Phase 3: list/create/update/delete cars, store baseline session
 * link, and surface "active car" selection used by other pages.
 */
import { create } from 'zustand'

export interface CarStub {
  id: number
  // TODO Phase 3 — full shape per backend Car model.
}

export interface CarsStoreState {
  cars: CarStub[]
  activeCarId: number | null
  loaded: boolean
}

export const useCarsStore = create<CarsStoreState>(() => ({
  cars: [],
  activeCarId: null,
  loaded: false,
}))
