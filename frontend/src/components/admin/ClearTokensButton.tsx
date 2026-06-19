/**
 * ClearTokensButton — action panel for clearing cached Cupra OAuth tokens.
 * Moved from SettingsPage.tsx so IntegrationCard doesn't depend on the page.
 */

import { useEffect, useState } from 'react'
import { ApiError, api } from '@/api/client'

interface ToastState {
  kind: 'success' | 'error'
  message: string
}

export function ClearTokensButton() {
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)

  useEffect(() => {
    if (toast === null) return
    const handle = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(handle)
  }, [toast])

  const handleClick = async () => {
    if (
      !window.confirm(
        "This will sign out all Cupra connections. You'll need to re-enter your credentials.",
      )
    ) {
      return
    }
    setBusy(true)
    try {
      await api.clearPycupraTokens()
      setToast({
        kind: 'success',
        message: 'Tokens cleared. Re-enter your password to reconnect.',
      })
    } catch (err) {
      setToast({
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Failed to clear tokens',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border-t border-slate-200 pt-4 dark:border-slate-700">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="rounded border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
        data-testid="clear-pycupra-tokens-button"
      >
        Clear cached Cupra tokens
      </button>
      <p className="mt-1 text-xs text-slate-500">
        Wipes the on-disk token cache. Use after a password change or if background sync starts
        failing with credentials_invalid.
      </p>
      {toast && (
        <p
          role="status"
          data-testid="clear-pycupra-tokens-toast"
          className={'mt-2 text-xs ' + (toast.kind === 'success' ? 'text-emerald-600' : 'text-red-600')}
        >
          {toast.message}
        </p>
      )}
    </div>
  )
}
