import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Zap } from 'lucide-react'
import { ApiError, api } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
      <div className="mb-6 flex items-center gap-2 text-2xl font-bold tracking-tight">
        <Zap className="h-5 w-5 text-cyan-500" aria-hidden />
        <span className="text-gradient-electric">PlugTrack</span>
      </div>
      <Card variant="hero">
        <h1 className="mb-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
          Welcome
        </h1>
        <p className="mb-5 text-sm text-slate-500 dark:text-slate-400">
          Create the administrator account for this instance.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="setup-username">Username</Label>
            <Input
              id="setup-username"
              type="text"
              required
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="setup-password">Password</Label>
            <Input
              id="setup-password"
              type="password"
              required
              minLength={12}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Minimum 12 characters.
            </p>
          </div>
          {error && (
            <div role="alert" className="text-sm text-red-600">
              {error}
            </div>
          )}
          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? 'Creating…' : 'Create account'}
          </Button>
        </form>
      </Card>
    </div>
  )
}
