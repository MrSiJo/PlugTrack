import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'

export default function SetupPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const login = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.setup({ username, password })
      // Auto-login after setup so the cookie is set.
      await login({ username, password })
      navigate('/settings', { replace: true })
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Setup failed'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="mb-2 text-2xl font-semibold">Welcome to PlugTrack</h1>
      <p className="mb-6 text-sm text-slate-600 dark:text-slate-400">
        Create the single administrator account for this instance.
      </p>
      <form onSubmit={handleSubmit} className="space-y-4">
        <label className="block">
          <span className="block text-sm font-medium">Username</span>
          <input
            type="text"
            required
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
        <label className="block">
          <span className="block text-sm font-medium">Password</span>
          <input
            type="password"
            required
            minLength={12}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 dark:border-slate-700 dark:bg-slate-800"
          />
          <span className="mt-1 block text-xs text-slate-500">
            Minimum 12 characters.
          </span>
        </label>
        {error && (
          <div role="alert" className="text-sm text-red-600">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-indigo-600 px-4 py-2 text-white disabled:opacity-50"
        >
          {submitting ? 'Creating…' : 'Create account'}
        </button>
      </form>
    </div>
  )
}
