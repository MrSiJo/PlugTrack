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

// ---------------------------------------------------------------------------
// Telegram health + OpenAI models
// ---------------------------------------------------------------------------

export interface HealthCheck {
  name: string
  ok: boolean
  detail: string
}

export interface HealthReport {
  all_ok: boolean
  checks: HealthCheck[]
  usage_this_month: {
    input_tokens: number
    output_tokens: number
    reasoning_tokens: number
    cost_pence: number | null
  } | null
}

export interface OpenAiModelsResponse {
  models: { id: string; recommended: boolean }[]
  current: string | null
}

// ---------------------------------------------------------------------------
// Cars
// ---------------------------------------------------------------------------

export interface CarPayload {
  id: number
  make: string
  model: string
  name: string | null
  display_name: string
  /** Now masked in list/get payloads (e.g. "········XYZ12"). Use revealCarVin() for the full value. */
  vin: string | null
  battery_kwh: number
  nominal_efficiency_mi_per_kwh: number
  max_ac_kw: number | null
  max_dc_kw: number | null
  provider: string
  provider_vehicle_id: string | null
  active: boolean
}

export interface CarCreateRequest {
  make: string
  model: string
  name?: string | null
  vin?: string | null
  battery_kwh: number
  nominal_efficiency_mi_per_kwh: number
  max_ac_kw?: number | null
  max_dc_kw?: number | null
  provider?: string
  provider_vehicle_id?: string | null
  active?: boolean
}

export type CarUpdateRequest = Partial<CarCreateRequest>

export interface CarLifetimeHomepublic {
  home: InsightsSplitBucket
  public: InsightsSplitBucket
}

export interface CarLifetimePayload {
  ownership_span: { first: string | null; last: string | null }
  total_sessions: number
  total_kwh: number
  total_cost_pence: number
  lifetime_avg_p_per_kwh: number | null
  lifetime_mi_per_kwh: number | null
  home_public: CarLifetimeHomepublic
  estimated_usable_kwh: number | null
  seasonal_range_span: { min_km: number | null; max_km: number | null; avg_km: number | null } | null
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
  actual_charge_seconds: number | null
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
  saved_vs_petrol_p: number | null
  comparison_basis: string | null
  breakeven_p_per_kwh: number | null
  efficiency_mi_per_kwh: number | null
  efficiency_basis: string | null
  // [[delta_seconds, soc, power_kw], ...] — live during charge.
  power_curve?: number[][] | null
  // True when power_curve is vision-extracted (source != 'synthesis').
  power_curve_approximate?: boolean
  metrics?: SessionMetricsPayload | null
}

export interface SessionMetricsPayload {
  miles_since_previous: number | null
  measured_miles_since_previous: number | null
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
  breakeven_p_per_kwh: number | null
  efficiency_mi_per_kwh: number | null
  efficiency_basis: string | null
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

// `interrupted` is editable on update only (create always defaults it to
// false server-side); everything else mirrors the create payload.
export type SessionUpdateRequest = Partial<SessionCreateRequest> & {
  interrupted?: boolean | null
}

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

export interface LocationCreateRequest {
  name?: string | null
  centroid_lat: number
  centroid_lng: number
  radius_m?: number
  is_home?: boolean
  is_free?: boolean
  default_cost_per_kwh_p?: number | null
  default_charge_network?: string | null
}

export interface RecalculateLocationResponse {
  sessions_recomputed_count: number
}

export interface GeocodeResult {
  address: string
  lat: number
  lng: number
  provider: string
}

export interface MergeLocationResponse {
  sessions_redirected: number
  plug_ins_redirected: number
  sessions_recomputed_count: number
}

export interface InsightsLocationRow {
  location_id: number | null
  name: string | null
  is_home: boolean
  is_free: boolean
  spend_pence: number
  kwh: number
  sessions: number
  avg_p_per_kwh: number | null
  first_at: string | null
  last_at: string | null
  pct_of_spend: number
}

export interface InsightsByLocationResponse {
  rows: InsightsLocationRow[]
  totals: { spend_pence: number; kwh: number; sessions: number }
}

export interface InsightsOverTimePoint {
  period: string
  spend_pence: number
  kwh: number
  sessions: number
}

export interface InsightsSplitBucket {
  spend_pence: number
  kwh: number
  sessions: number
  avg_p_per_kwh: number | null
}

export interface InsightsNetworkRow {
  network: string
  spend_pence: number
  kwh: number
  sessions: number
  avg_p_per_kwh: number | null
}

export interface InsightsEfficiencyPoint {
  period: string
  observed_mi_per_kwh: number | null
  rolling_mi_per_kwh: number | null
  cost_per_mile_p: number | null
}

export interface SeasonalEfficiencyPoint {
  /** "YYYY-MM" */
  period: string
  mi_per_kwh: number | null
  derived_range_km: number | null
  low_confidence: boolean
}

export interface CapacityTrendPoint {
  /** "YYYY-MM-DD" */
  date: string
  usable_kwh: number
  charging_type: 'ac' | 'dc' | 'unknown'
  low_confidence: boolean
}

export interface BatteryHealth {
  estimated_usable_kwh: number
  nominal_kwh: number
  /** DISPLAY value, already capped at 100 by backend */
  soh_pct: number
  /** uncapped, e.g. 104 */
  soh_pct_raw: number
  qualifying_count: number
  /** true when qualifying_count < 3 */
  low_confidence: boolean
}

export interface SeasonalDelta {
  best: SeasonalEfficiencyPoint
  worst: SeasonalEfficiencyPoint
  pct: number
  abs_mi_per_kwh: number
}

export interface InsightsOverviewResponse {
  granularity: 'daily' | 'weekly' | 'monthly'
  over_time: InsightsOverTimePoint[]
  split: { home: InsightsSplitBucket; public: InsightsSplitBucket }
  by_network: InsightsNetworkRow[]
  efficiency: InsightsEfficiencyPoint[]
  seasonal_efficiency?: SeasonalEfficiencyPoint[]
  capacity_trend?: CapacityTrendPoint[]
  battery_health: BatteryHealth | null
  seasonal_delta?: SeasonalDelta | null
}

export interface InsightsMileageResponse {
  enabled: boolean
  car_id: number
  period_start: string | null
  period_end: string | null
  opening_km: number | null
  current_km: number | null
  target_km: number | null
  used_km: number | null
  remaining_km: number | null
  days_elapsed: number | null
  days_total: number | null
  projected_year_end_km: number | null
  pace: 'on' | 'under' | 'over' | null
}

// ---------------------------------------------------------------------------
// MCP / API tokens
// ---------------------------------------------------------------------------

export interface McpTokenListItem {
  id: number
  name: string
  scope: string
  created_at: string
  last_used_at: string | null
}

export interface McpTokenCreateResponse {
  id: number
  name: string
  scope: string
  created_at: string
  /** Plaintext token — shown ONCE. Store immediately. */
  token: string
}

// ---------------------------------------------------------------------------
// Charge Planner
// ---------------------------------------------------------------------------

export type ScenarioSourceTag = 'history' | 'spec' | 'curve' | 'average' | 'modelled'

export interface ScenarioRow {
  label: string
  power_kw: number
  minutes: number
  source_tag: ScenarioSourceTag
  finish_at: string | null
  nights: number | null
  note: string | null
}

export interface ScenarioPlanResponse {
  car_id: number
  start_soc: number
  target_soc: number
  battery_kwh: number
  loss_factor: number
  home_rate_p_per_kwh: number
  is_free: boolean
  rows: ScenarioRow[]
}

export interface BlendedPhase {
  kwh: number
  minutes: number
  cost_pence: number
}

export interface BlendedTotal {
  kwh: number
  minutes: number
  cost_pence: number
  cost_per_mile_p: number | null
  mi_per_kwh: number | null
}

export interface BlendedPlanResponse {
  car_id: number
  start_soc: number
  dc_stop_soc: number
  target_soc: number
  battery_kwh: number
  loss_factor: number
  dc_rate_p: number
  home_rate_p_per_kwh: number
  is_free: boolean
  dc_phase: BlendedPhase
  home_phase: BlendedPhase
  total: BlendedTotal
}

// ---------------------------------------------------------------------------
// File download helper — fetch with cookie credentials, convert to blob,
// trigger an anchor-click download, then revoke the object URL.
// ---------------------------------------------------------------------------

export async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await fetch(path, { credentials: 'include' })
  if (!response.ok) {
    throw new ApiError(response.status, `HTTP ${response.status}`, null)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
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

  testTelegram: (): Promise<HealthReport> =>
    fetchJSON<HealthReport>('/api/telegram/test', { method: 'POST' }),

  getOpenAiModels: (): Promise<OpenAiModelsResponse> =>
    fetchJSON<OpenAiModelsResponse>('/api/openai/models'),

  // ----- Cars -----

  getCars: (): Promise<CarPayload[]> => fetchJSON<CarPayload[]>('/api/cars'),

  getCar: (id: number): Promise<CarPayload> => fetchJSON<CarPayload>(`/api/cars/${id}`),

  createCar: (req: CarCreateRequest): Promise<CarPayload> =>
    fetchJSON<CarPayload>('/api/cars', { method: 'POST', body: req }),

  updateCar: (id: number, req: CarUpdateRequest): Promise<CarPayload> =>
    fetchJSON<CarPayload>(`/api/cars/${id}`, { method: 'PUT', body: req }),

  deleteCar: (id: number): Promise<void> =>
    fetchJSON<void>(`/api/cars/${id}`, { method: 'DELETE' }),

  /** Reveal the full (unmasked) VIN for a car the caller owns.
   *  The list/get payload now returns a masked VIN; call this to get the
   *  full plaintext value (e.g. when opening the edit form). */
  revealCarVin: (id: number): Promise<{ vin: string | null }> =>
    fetchJSON<{ vin: string | null }>(`/api/cars/${id}/vin`),

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

  getCarLifetime: (id: number): Promise<CarLifetimePayload> =>
    fetchJSON<CarLifetimePayload>(`/api/cars/${id}/lifetime`),

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

  createLocation: (req: LocationCreateRequest): Promise<LocationPayload> =>
    fetchJSON<LocationPayload>('/api/locations', { method: 'POST', body: req }),

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

  geocode: (q: string): Promise<GeocodeResult> =>
    fetchJSON<GeocodeResult>(`/api/geocode?q=${encodeURIComponent(q)}`),

  getInsightsByLocation: (
    dateFrom?: string,
    dateTo?: string,
    carId?: number,
  ): Promise<InsightsByLocationResponse> => {
    const params = new URLSearchParams()
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    if (carId != null) params.set('car_id', String(carId))
    const qs = params.toString()
    return fetchJSON<InsightsByLocationResponse>(
      `/api/insights/by-location${qs ? `?${qs}` : ''}`,
    )
  },

  getInsightsOverview: (
    dateFrom?: string,
    dateTo?: string,
    carId?: number,
  ): Promise<InsightsOverviewResponse> => {
    const params = new URLSearchParams()
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    if (carId != null) params.set('car_id', String(carId))
    const qs = params.toString()
    return fetchJSON<InsightsOverviewResponse>(
      `/api/insights/overview${qs ? `?${qs}` : ''}`,
    )
  },

  getInsightsMileage: (carId: number): Promise<InsightsMileageResponse> =>
    fetchJSON<InsightsMileageResponse>(`/api/insights/mileage?car_id=${carId}`),

  // ----- Dashboard -----

  getDashboard: (): Promise<DashboardSummary> =>
    fetchJSON<DashboardSummary>('/api/dashboard'),

  getSpendTrend: (days = 30): Promise<SpendTrendDay[]> =>
    fetchJSON<SpendTrendDay[]>(`/api/dashboard/spend-trend?days=${days}`),

  // ----- Maintenance: Backup & Export -----

  backupNow: (): Promise<{ name: string; size_bytes: number; created_at: string }> =>
    fetchJSON<{ name: string; size_bytes: number; created_at: string }>(
      '/api/maintenance/backup',
      { method: 'POST' },
    ),

  listBackups: (): Promise<{ name: string; size_bytes: number; created_at: string }[]> =>
    fetchJSON<{ name: string; size_bytes: number; created_at: string }[]>(
      '/api/maintenance/backups',
    ),

  /** Returns the URL for downloading a backup by name (same-origin GET, cookie auth). */
  backupDownloadUrl: (name: string): string =>
    `/api/maintenance/backups/${encodeURIComponent(name)}/download`,

  /** Triggers a browser download of the sessions export file. */
  exportSessions: async (format: 'csv' | 'json'): Promise<void> => {
    const ext = format === 'json' ? 'json' : 'csv'
    await downloadFile(
      `/api/maintenance/export/sessions?format=${format}`,
      `plugtrack-sessions.${ext}`,
    )
  },

  // ----- Charge Planner -----

  getChargePlan: (
    carId: number,
    startSoc: number,
    targetSoc: number,
    customKw?: number,
  ): Promise<ScenarioPlanResponse> => {
    let path = `/api/charge-plan?car_id=${carId}&start_soc=${startSoc}&target_soc=${targetSoc}`
    if (customKw !== undefined) path += `&custom_kw=${customKw}`
    return fetchJSON<ScenarioPlanResponse>(path)
  },

  getBlendedChargePlan: (
    carId: number,
    startSoc: number,
    dcStopSoc: number,
    homeTargetSoc: number,
    dcRateP?: number,
    dcChargerCapKw?: number,
  ): Promise<BlendedPlanResponse> => {
    let path =
      `/api/charge-plan/blended?car_id=${carId}` +
      `&start_soc=${startSoc}&dc_stop_soc=${dcStopSoc}&home_target_soc=${homeTargetSoc}`
    if (dcRateP !== undefined) path += `&dc_rate_p=${dcRateP}`
    if (dcChargerCapKw !== undefined) path += `&dc_charger_cap_kw=${dcChargerCapKw}`
    return fetchJSON<BlendedPlanResponse>(path)
  },

  // ----- MCP / API tokens -----

  listMcpTokens: (): Promise<McpTokenListItem[]> =>
    fetchJSON<McpTokenListItem[]>('/api/mcp/tokens'),

  createMcpToken: (
    name: string,
    scope: 'read' | 'readwrite',
  ): Promise<McpTokenCreateResponse> =>
    fetchJSON<McpTokenCreateResponse>('/api/mcp/tokens', {
      method: 'POST',
      body: { name, scope },
    }),

  revokeMcpToken: (id: number): Promise<void> =>
    fetchJSON<void>(`/api/mcp/tokens/${id}`, { method: 'DELETE' }),
}

export interface SpendTrendDay {
  date: string
  cost_pence: number
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

export interface DashboardCostPerMile {
  lifetime_pence: number | null
  rolling_30d_pence: number | null
}

export interface DashboardSummary {
  cars: DashboardCarPanel[]
  recent_sessions: DashboardSessionRow[]
  lifetime_totals: DashboardLifetimeTotals
  top_locations: DashboardLocationStat[]
  cost_per_mile: DashboardCostPerMile
}
