import { useEffect, useState, type ReactNode } from 'react'
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom'
import { ApiError, api } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { useSettingsStore } from '@/stores/settingsStore'
import { applyThemeToDocument } from '@/theme'
import AdminPage from '@/pages/AdminPage'
import Cars from '@/pages/Cars'
import Dashboard from '@/pages/Dashboard'
import Insights from '@/pages/Insights'
import LocationDetail from '@/pages/LocationDetail'
import Locations from '@/pages/Locations'
import LoginPage from '@/pages/LoginPage'
import Planner from '@/pages/Planner'
import SessionDetail from '@/pages/SessionDetail'
import Sessions from '@/pages/Sessions'
import SetupPage from '@/pages/SetupPage'
import AuthFailureBanner from '@/components/AuthFailureBanner'
import CommandPalette from '@/components/CommandPalette'
import NavBar from '@/components/NavBar'
import SyncStreamSubscriber from '@/components/SyncStreamSubscriber'

interface BootstrapResult {
  setupNeeded: boolean
  authed: boolean
}

async function probeBootstrap(): Promise<BootstrapResult> {
  // /api/setup is unauthenticated.
  const status = await api.setupStatus()
  if (status.setup_needed) {
    return { setupNeeded: true, authed: false }
  }
  // Try to load settings — 200 means session cookie is valid, 401 not.
  try {
    await api.getSettings()
    return { setupNeeded: false, authed: true }
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      return { setupNeeded: false, authed: false }
    }
    throw err
  }
}

function AppRoutes({ result }: { result: BootstrapResult }) {
  const location = useLocation()
  const userInState = useAuthStore((s) => s.user)
  const settingsLoaded = useSettingsStore((s) => s.loaded)
  const reload = useSettingsStore((s) => s.reload)
  const authed = result.authed || userInState !== null

  // If we became authed (after login) and settings haven't loaded yet,
  // pull them in so the SettingsPage has data and theme is applied.
  useEffect(() => {
    if (authed && !settingsLoaded) {
      void reload()
    }
  }, [authed, settingsLoaded, reload])

  // Pages that should NOT show the nav bar (pre-auth flows).
  const showNav = authed && !result.setupNeeded
  const path = location.pathname
  const hideNavForPath = path === '/setup' || path === '/login'

  return (
    <>
      {showNav && !hideNavForPath && <NavBar />}
    <Routes>
      <Route
        path="/setup"
        element={
          result.setupNeeded ? (
            <SetupPage />
          ) : (
            <Navigate to={authed ? '/settings' : '/login'} replace />
          )
        }
      />
      <Route
        path="/login"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : authed ? (
            <Navigate to="/dashboard" replace />
          ) : (
            <LoginPage />
          )
        }
      />
      <Route
        path="/dashboard"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <Dashboard />
          )
        }
      />
      <Route
        path="/settings"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <Navigate to="/admin" replace />
          )
        }
      />
      <Route
        path="/admin"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <AdminPage />
          )
        }
      />
      <Route
        path="/sessions"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <Sessions />
          )
        }
      />
      <Route
        path="/sessions/:id"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <SessionDetail />
          )
        }
      />
      <Route
        path="/insights"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <Insights />
          )
        }
      />
      <Route
        path="/locations"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <Locations />
          )
        }
      />
      <Route
        path="/locations/:id"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <LocationDetail />
          )
        }
      />
      <Route
        path="/cars"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <Cars />
          )
        }
      />
      <Route
        path="/planner"
        element={
          result.setupNeeded ? (
            <Navigate to="/setup" replace />
          ) : !authed ? (
            <Navigate to="/login" replace state={{ from: location }} />
          ) : (
            <Planner />
          )
        }
      />
      <Route
        path="*"
        element={
          <Navigate
            to={
              result.setupNeeded
                ? '/setup'
                : authed
                  ? '/dashboard'
                  : '/login'
            }
            replace
          />
        }
      />
    </Routes>
    </>
  )
}

interface BootstrapState {
  loading: boolean
  result: BootstrapResult | null
  error: string | null
}

function useBootstrap(): BootstrapState {
  const [state, setState] = useState<BootstrapState>({
    loading: true,
    result: null,
    error: null,
  })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const result = await probeBootstrap()
        if (!cancelled) setState({ loading: false, result, error: null })
      } catch (err) {
        if (!cancelled) {
          setState({
            loading: false,
            result: null,
            error: err instanceof Error ? err.message : 'Bootstrap failed',
          })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return state
}

function AppShell({ children }: { children: ReactNode }) {
  const themeValue = useSettingsStore((s) => s.settings['theme']?.value)
  useEffect(() => {
    applyThemeToDocument(
      (themeValue === 'dark' || themeValue === 'light' ? themeValue : 'system'),
    )
  }, [themeValue])
  return <>{children}</>
}

export default function App() {
  const { loading, result, error } = useBootstrap()

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-slate-500">Loading…</p>
      </main>
    )
  }
  if (error || !result) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div role="alert" className="text-sm text-red-600">
          Failed to contact PlugTrack: {error}
        </div>
      </main>
    )
  }

  return (
    <BrowserRouter>
      <AppShell>
        <SyncStreamSubscriber />
        <CommandPalette />
        <AuthFailureBanner />
        <AppRoutes result={result} />
      </AppShell>
    </BrowserRouter>
  )
}
