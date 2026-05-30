/**
 * Typed API client for PlugTrack backend.
 *
 * - All requests carry credentials so the signed `plugtrack_session`
 *   cookie is sent.
 * - For mutating verbs (POST/PUT/PATCH/DELETE) the client reads the
 *   `plugtrack_csrf` cookie and echoes it as `X-CSRF-Token` (double-
 *   submit pattern; backend compares with constant-time equality).
 * - Non-2xx responses throw `ApiError` carrying status + parsed body.
 */

const CSRF_COOKIE = 'plugtrack_csrf'
const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export class ApiError<TBody = unknown> extends Error {
  readonly status: number
  readonly body: TBody | null

  constructor(status: number, message: string, body: TBody | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${name}=`
  const parts = document.cookie ? document.cookie.split('; ') : []
  for (const part of parts) {
    if (part.startsWith(prefix)) {
      return decodeURIComponent(part.slice(prefix.length))
    }
  }
  return null
}

export interface FetchOpts {
  method?: string
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

export async function fetchJSON<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const method = (opts.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = { ...(opts.headers ?? {}) }

  let body: BodyInit | undefined
  if (opts.body !== undefined && opts.body !== null) {
    headers['Content-Type'] = headers['Content-Type'] ?? 'application/json'
    body = JSON.stringify(opts.body)
  }

  if (MUTATING.has(method)) {
    const csrf = readCookie(CSRF_COOKIE)
    if (csrf) {
      headers['X-CSRF-Token'] = csrf
    }
  }

  const response = await fetch(path, {
    method,
    headers,
    body,
    credentials: 'include',
    signal: opts.signal,
  })

  // 204 No Content
  if (response.status === 204) {
    return undefined as T
  }

  const contentType = response.headers.get('Content-Type') ?? ''
  let parsed: unknown = null
  if (contentType.includes('application/json')) {
    try {
      parsed = await response.json()
    } catch {
      parsed = null
    }
  } else {
    try {
      parsed = await response.text()
    } catch {
      parsed = null
    }
  }

  if (!response.ok) {
    const rawDetail =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? (parsed as { detail: unknown }).detail
        : null
    let detail: string
    if (Array.isArray(rawDetail)) {
      // Pydantic validation errors: [{loc:[...], msg:"...", type:"..."}, ...]
      detail = rawDetail
        .map((e) => {
          if (e && typeof e === 'object') {
            const item = e as { loc?: unknown[]; msg?: string }
            const field = Array.isArray(item.loc)
              ? item.loc.filter((p) => p !== 'body').join('.')
              : ''
            const msg = item.msg ?? JSON.stringify(e)
            return field ? `${field}: ${msg}` : msg
          }
          return String(e)
        })
        .join('; ')
    } else if (rawDetail !== null && rawDetail !== undefined) {
      detail = String(rawDetail)
    } else {
      detail = `HTTP ${response.status}`
    }
    throw new ApiError(response.status, detail, parsed)
  }

  return parsed as T
}

// ---------------------------------------------------------------------------
// Typed wrappers — one per backend route.
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string
  commit: string
}

export interface SetupStatusResponse {
  setup_needed: boolean
}

export interface SetupRequest {
  username: string
  password: string
}

export interface SetupResponse {
  user_id: number
  username: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  user_id: number
  username: string
}

export type SettingValueType = 'string' | 'int' | 'float' | 'bool' | 'enum'

export interface SettingPayload {
  key: string
  value: string | null
  value_type: SettingValueType
  group_name: string
  label: string
  description: string | null
  is_secret: boolean
}

export type SettingsMap = Record<string, SettingPayload>

export interface ClearTokensResponse {
  cleared: boolean
  count: number
}

// ---------------------------------------------------------------------------
// Cars
// ---------------------------------------------------------------------------

export interface CarPayload {
  id: number
  make: string
  model: string
  vin: string | null
  battery_kwh: number
  nominal_efficiency_mi_per_kwh: number
  provider: string
  provider_vehicle_id: string | null
  active: boolean
}

export interface CarCreateRequest {
  make: string
  model: string
  vin?: string | null
  battery_kwh: number
  nominal_efficiency_mi_per_kwh: number
  provider?: string
  provider_vehicle_id?: string | null
  active?: boolean
}

export type CarUpdateRequest = Partial<CarCreateRequest>

export interface DiscoveredVehicle {
  vin: string
  model: string | null
  year: string | null
}

// ---------------------------------------------------------------------------
// Mileage tracking
// ---------------------------------------------------------------------------

export interface MileagePeriodPayload {
  period_start_date: string
  period_end_date: string
  opening_odometer_km: number
  closing_odometer_km: number | null
  annual_mileage_target_km: number | null
}

export interface CurrentMileagePeriodPayload {
  period_start_date: string
  period_end_date: string
  opening_odometer_km: number
  current_odometer_km: number
  annual_mileage_target_km: number | null
}

export interface MileageStatusPayload {
  enabled: boolean
  current_period: CurrentMileagePeriodPayload | null
  history: MileagePeriodPayload[]
}

export interface MileageConfigRequest {
  start_date: string
  opening_miles: number
  annual_mileage_target_miles?: number | null
}

// ---------------------------------------------------------------------------
// Sessions + Locations
// ---------------------------------------------------------------------------

export type CostBasis =
  | 'override_total'
  | 'override_per_kwh'
  | 'location_free'
  | 'location_rate'
  | 'home_rate'
  | 'unknown'

export interface ChargingSessionPayload {
  id: number
  user_id: number
  car_id: number
  plug_in_record_id: number | null
  date: string
  charge_start_at: string | null
  charge_end_at: string | null
  start_soc: number
  end_soc: number
  kwh_added: number
  kwh_calculated: number | null
  odometer_at_session_km: number | null
  charging_type: string
  charging_mode: string
  battery_care: boolean | null
  max_charge_current: string | null
  interrupted: boolean
  cost_pence: number | null
  cost_basis: CostBasis
  tariff_p_per_kwh: number | null
  cost_per_kwh_override_p: number | null
  total_cost_pence_override: number | null
  location_id: number | null
  location_name: string | null
  location_address: string | null
  location_lat: number | null
  location_lng: number | null
  user_label: string | null
  charge_network: string | null
  notes: string | null
  source: string
  telematics_session_id: string | null
  // [[delta_seconds, soc, power_kw], ...] — live during charge.
  power_curve?: number[][] | null
  metrics?: SessionMetricsPayload | null
}

export interface SessionMetricsPayload {
  miles_since_previous: number | null
  cost_per_mile_p: number | null
  petrol_ppm: number | null
  petrol_equivalent_cost_p: number | null
  savings_vs_petrol_p: number | null
  petrol_price_p_per_litre: number | null
  petrol_mpg: number | null
  comparison_basis: string | null
  chain_session_ids: number[]
  chain_total_cost_pence: number | null
  chain_anchor_id: number | null
  range_added_miles: number | null
  duration_minutes: number | null
  average_power_kw: number | null
  peak_power_kw: number | null
  efficiency_percent: number | null
}

export interface SessionCreateRequest {
  car_id: number
  date: string
  start_soc: number
  end_soc: number
  kwh_added: number
  odometer_at_session_km?: number | null
  charge_start_at?: string | null
  charge_end_at?: string | null
  location_id?: number | null
  charging_type?: string
  charging_mode?: string
  battery_care?: boolean | null
  max_charge_current?: string | null
  cost_per_kwh_override_p?: number | null
  total_cost_pence_override?: number | null
  charge_network?: string | null
  notes?: string | null
  user_label?: string | null
}

export type SessionUpdateRequest = Partial<SessionCreateRequest>

export interface LocationPayload {
  id: number
  name: string | null
  centroid_lat: number
  centroid_lng: number
  radius_m: number
  is_home: boolean
  is_free: boolean
  default_cost_per_kwh_p: number | null
  default_charge_network: string | null
  address: string | null
}

export interface LocationListPayload extends LocationPayload {
  visit_count: number
  total_kwh: number
  total_cost_pence: number
  last_visited_at: string | null
}

export interface LocationLabelRequest {
  name: string
  is_home: boolean
  is_free: boolean
  default_cost_per_kwh_p: number | null
  default_charge_network?: string | null
}

export interface LocationLabelResponse {
  location: LocationPayload
  sessions_recomputed_count: number
}

export interface LocationUpdateRequest {
  name?: string | null
  is_home?: boolean
  is_free?: boolean
  default_cost_per_kwh_p?: number | null
  default_charge_network?: string | null
  radius_m?: number
}

export interface RecalculateLocationResponse {
  sessions_recomputed_count: number
}

export interface MergeLocationResponse {
  sessions_redirected: number
  plug_ins_redirected: number
  sessions_recomputed_count: number
}

export const api = {
  health: (): Promise<HealthResponse> => fetchJSON<HealthResponse>('/api/health'),

  setupStatus: (): Promise<SetupStatusResponse> =>
    fetchJSON<SetupStatusResponse>('/api/setup'),

  setup: (req: SetupRequest): Promise<SetupResponse> =>
    fetchJSON<SetupResponse>('/api/setup', { method: 'POST', body: req }),

  login: (req: LoginRequest): Promise<LoginResponse> =>
    fetchJSON<LoginResponse>('/api/auth/login', { method: 'POST', body: req }),

  logout: (): Promise<{ ok: boolean }> =>
    fetchJSON<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),

  getSettings: (): Promise<SettingsMap> => fetchJSON<SettingsMap>('/api/settings'),

  putSetting: (key: string, value: string | null): Promise<{ key: string; status: string }> =>
    fetchJSON<{ key: string; status: string }>('/api/settings', {
      method: 'PUT',
      body: { key, value },
    }),

  clearPycupraTokens: (): Promise<ClearTokensResponse> =>
    fetchJSON<ClearTokensResponse>('/api/settings/clear-pycupra-tokens', {
      method: 'POST',
    }),

  // ----- Cars -----

  discoverVehicles: (): Promise<DiscoveredVehicle[]> =>
    fetchJSON<DiscoveredVehicle[]>('/api/cars/discover'),

  getCars: (): Promise<CarPayload[]> => fetchJSON<CarPayload[]>('/api/cars'),

  getCar: (id: number): Promise<CarPayload> => fetchJSON<CarPayload>(`/api/cars/${id}`),

  createCar: (req: CarCreateRequest): Promise<CarPayload> =>
    fetchJSON<CarPayload>('/api/cars', { method: 'POST', body: req }),

  updateCar: (id: number, req: CarUpdateRequest): Promise<CarPayload> =>
    fetchJSON<CarPayload>(`/api/cars/${id}`, { method: 'PUT', body: req }),

  deleteCar: (id: number): Promise<void> =>
    fetchJSON<void>(`/api/cars/${id}`, { method: 'DELETE' }),

  /** URL of the cached pycupra image for this car. Returns 404 when the
   *  image isn't on disk yet (frontend renders a placeholder).
   *  Not a fetch — this URL is fed straight to <img src="…">. */
  carImageUrl: (id: number, view = 'front_cropped'): string =>
    `/api/cars/${id}/image?view=${view}`,

  getCarMileage: (carId: number): Promise<MileageStatusPayload> =>
    fetchJSON<MileageStatusPayload>(`/api/cars/${carId}/mileage`),

  setCarMileage: (
    carId: number,
    req: MileageConfigRequest,
  ): Promise<MileageStatusPayload> =>
    fetchJSON<MileageStatusPayload>(`/api/cars/${carId}/mileage`, {
      method: 'PUT',
      body: req,
    }),

  clearCarMileage: (carId: number): Promise<void> =>
    fetchJSON<void>(`/api/cars/${carId}/mileage`, { method: 'DELETE' }),

  // ----- Sessions -----

  getSessions: (
    filtersOrCarId?: number | string,
  ): Promise<ChargingSessionPayload[]> => {
    let path = '/api/sessions'
    if (typeof filtersOrCarId === 'number') {
      path = `/api/sessions?car_id=${filtersOrCarId}`
    } else if (typeof filtersOrCarId === 'string' && filtersOrCarId) {
      // Caller provides a leading-`?` query string.
      path = `/api/sessions${filtersOrCarId}`
    }
    return fetchJSON<ChargingSessionPayload[]>(path)
  },

  getSession: (id: number): Promise<ChargingSessionPayload> =>
    fetchJSON<ChargingSessionPayload>(`/api/sessions/${id}`),

  createSession: (req: SessionCreateRequest): Promise<ChargingSessionPayload> =>
    fetchJSON<ChargingSessionPayload>('/api/sessions', { method: 'POST', body: req }),

  updateSession: (
    id: number,
    req: SessionUpdateRequest,
  ): Promise<ChargingSessionPayload> =>
    fetchJSON<ChargingSessionPayload>(`/api/sessions/${id}`, {
      method: 'PUT',
      body: req,
    }),

  deleteSession: (id: number): Promise<void> =>
    fetchJSON<void>(`/api/sessions/${id}`, { method: 'DELETE' }),

  // ----- Locations -----

  labelLocation: (
    id: number,
    req: LocationLabelRequest,
  ): Promise<LocationLabelResponse> =>
    fetchJSON<LocationLabelResponse>(`/api/locations/${id}/label`, {
      method: 'PATCH',
      body: req,
    }),

  getLocations: (): Promise<LocationListPayload[]> =>
    fetchJSON<LocationListPayload[]>('/api/locations'),

  updateLocation: (
    id: number,
    req: LocationUpdateRequest,
  ): Promise<LocationPayload> =>
    fetchJSON<LocationPayload>(`/api/locations/${id}`, {
      method: 'PUT',
      body: req,
    }),

  recalculateLocationPastCosts: (
    id: number,
  ): Promise<RecalculateLocationResponse> =>
    fetchJSON<RecalculateLocationResponse>(
      `/api/locations/${id}/recalculate-past-costs`,
      { method: 'POST' },
    ),

  mergeLocations: (
    id: number,
    target_id: number,
  ): Promise<MergeLocationResponse> =>
    fetchJSON<MergeLocationResponse>(`/api/locations/${id}/merge`, {
      method: 'POST',
      body: { target_id },
    }),

  deleteLocation: (id: number): Promise<void> =>
    fetchJSON<void>(`/api/locations/${id}`, { method: 'DELETE' }),

  // ----- Sync -----

  syncCar: (carId: number): Promise<SyncJobResponse> =>
    fetchJSON<SyncJobResponse>(`/api/sync/${carId}`, { method: 'POST' }),

  wakeCar: (carId: number): Promise<WakeResponse> =>
    fetchJSON<WakeResponse>(`/api/sync/${carId}/wake`, { method: 'POST' }),

  getSyncStatus: (): Promise<SyncStatusResponse> =>
    fetchJSON<SyncStatusResponse>('/api/sync/status'),

  // ----- Dashboard -----

  getDashboard: (): Promise<DashboardSummary> =>
    fetchJSON<DashboardSummary>('/api/dashboard'),

  getSpendTrend: (days = 30): Promise<SpendTrendDay[]> =>
    fetchJSON<SpendTrendDay[]>(`/api/dashboard/spend-trend?days=${days}`),
}

export interface SpendTrendDay {
  date: string
  cost_pence: number
}

// ---------------------------------------------------------------------------
// Sync types
// ---------------------------------------------------------------------------

export interface SyncJobResponse {
  job_id: string
  stream_url: string
  kind: string
  status: string
}

export interface WakeResponse {
  woken: boolean
  car_id: number
  reason?: string
  retry_after?: number
}

export interface CarSyncStatus {
  last_state: string | null
  last_soc: number | null
  next_poll_at: string | null
  last_error: string | null
  active_job_id: string | null
  consecutive_failures: number
  auth_invalid: boolean
}

export interface SyncStatusResponse {
  cars: Record<string, CarSyncStatus>
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export interface DashboardMileageYear {
  period_start_date: string
  period_end_date: string
  opening_odometer_km: number
  current_odometer_km: number
  annual_mileage_target_km: number | null
}

export interface DashboardCarPanel {
  id: number
  make: string
  model: string
  battery_level: number | null
  charging_cable_connected: boolean
  last_connected: string | null
  next_poll_at: string | null
  last_state: string | null
  last_soc: number | null
  active_job_id: string | null
  location_name: string | null
  location_address: string | null
  electric_range_km: number | null
  charging_power_kw: number | null
  target_soc: number | null
  battery_care: boolean | null
  max_charge_current: string | null
  charging_estimated_end_at: string | null
  nominal_efficiency_mi_per_kwh: number | null
  mileage_year: DashboardMileageYear | null
}

export interface DashboardSessionRow {
  id: number
  car_id: number
  car_label: string
  date: string
  kwh_added: number
  cost_pence: number | null
  cost_basis: CostBasis
  location_id: number | null
  location_name: string | null
  charge_network: string | null
  source: string
}

export interface DashboardLifetimeTotals {
  kwh: number
  cost_pence: number
  distance_km: number
  sessions_count: number
}

export interface DashboardLocationStat {
  id: number
  name: string | null
  charge_count: number
  total_kwh: number
  total_cost_pence: number
}

export interface DashboardSummary {
  cars: DashboardCarPanel[]
  recent_sessions: DashboardSessionRow[]
  lifetime_totals: DashboardLifetimeTotals
  top_locations: DashboardLocationStat[]
}
