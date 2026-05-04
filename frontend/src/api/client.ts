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
    const detail =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : `HTTP ${response.status}`
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
}
