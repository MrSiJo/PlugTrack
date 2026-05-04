import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ApiError, fetchJSON, api } from './client'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('fetchJSON', () => {
  const fetchSpy = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchSpy)
    document.cookie = 'plugtrack_csrf=test-csrf-token; path=/'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchSpy.mockReset()
    // Wipe csrf cookie between tests.
    document.cookie = 'plugtrack_csrf=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  })

  it('does NOT add CSRF header on GET', async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse(200, { ok: true }))

    await fetchJSON('/api/health')

    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const init = fetchSpy.mock.calls[0]![1] as RequestInit
    const headers = (init.headers ?? {}) as Record<string, string>
    expect(headers['X-CSRF-Token']).toBeUndefined()
    expect(init.credentials).toBe('include')
    expect(init.method).toBe('GET')
  })

  it('adds CSRF header on POST and sets JSON content-type', async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse(200, { user_id: 1, username: 'a' }))

    await api.login({ username: 'a', password: 'b' })

    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [path, init] = fetchSpy.mock.calls[0]!
    expect(path).toBe('/api/auth/login')
    const headers = (init?.headers ?? {}) as Record<string, string>
    expect(headers['X-CSRF-Token']).toBe('test-csrf-token')
    expect(headers['Content-Type']).toBe('application/json')
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe(JSON.stringify({ username: 'a', password: 'b' }))
  })

  it('throws ApiError on 401', async () => {
    fetchSpy.mockResolvedValue(
      jsonResponse(401, { detail: 'Authentication required' }),
    )

    let caught: unknown = null
    try {
      await api.getSettings()
    } catch (err) {
      caught = err
    }

    expect(caught).toBeInstanceOf(ApiError)
    const apiErr = caught as ApiError
    expect(apiErr.status).toBe(401)
    expect(apiErr.body).toEqual({ detail: 'Authentication required' })
    expect(apiErr.message).toBe('Authentication required')
  })

  it('parses 200 JSON body', async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse(200, { setup_needed: true }))
    const result = await api.setupStatus()
    expect(result).toEqual({ setup_needed: true })
  })

  it('returns undefined on 204 No Content', async () => {
    fetchSpy.mockResolvedValueOnce(new Response(null, { status: 204 }))
    const result = await fetchJSON<undefined>('/api/something', { method: 'DELETE' })
    expect(result).toBeUndefined()
  })
})
