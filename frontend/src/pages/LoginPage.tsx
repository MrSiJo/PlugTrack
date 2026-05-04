import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'

export default function LoginPage() {
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
      await login({ username, password })
      navigate('/settings', { replace: true })
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Login failed'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="mb-6 text-2xl font-semibold">Sign in to PlugTrack</h1>
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
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 dark:border-slate-700 dark:bg-slate-800"
          />
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
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
