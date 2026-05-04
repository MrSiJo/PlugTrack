/**
 * Auth-failure banner (Phase 5.4).
 *
 * Reads the syncStore's lastErrorByCarId. For any car whose error is
 * `credentials_invalid`, render a persistent banner with a CTA that
 * deep-links to /settings.
 *
 * Mounted in App.tsx above the routes outlet so it's always visible
 * once the user is authenticated.
 */
import { useNavigate } from 'react-router-dom'
import { useSyncStore } from '@/stores/syncStore'

export default function AuthFailureBanner() {
  const errors = useSyncStore((s) => s.lastErrorByCarId)
  const navigate = useNavigate()

  const failingCarIds = Object.entries(errors)
    .filter(([, msg]) => msg === 'credentials_invalid')
    .map(([carId]) => Number(carId))

  if (failingCarIds.length === 0) return null

  return (
    <div
      role="alert"
      data-testid="auth-failure-banner"
      className="border-b border-red-300 bg-red-50 px-6 py-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
    >
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
        <p>
          Cupra Connect credentials invalid for{' '}
          {failingCarIds.length === 1
            ? `car #${failingCarIds[0]}`
            : `${failingCarIds.length} cars`}
          . Update them in Settings &rarr; Cupra Connect.
        </p>
        <button
          type="button"
          onClick={() => navigate('/settings')}
          className="shrink-0 rounded border border-red-400 px-3 py-1 text-xs font-medium hover:bg-red-100 dark:border-red-600 dark:hover:bg-red-900"
          data-testid="auth-failure-open-settings"
        >
          Open Settings
        </button>
      </div>
    </div>
  )
}
