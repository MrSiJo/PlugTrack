import { NavLink, useNavigate } from 'react-router-dom'
import { Search, Zap } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { Button } from '@/components/ui/button'
import { useCommandPalette } from '@/components/CommandPalette'

const links = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/cars', label: 'Cars' },
  { to: '/sessions', label: 'Sessions' },
  { to: '/locations', label: 'Locations' },
  { to: '/planner', label: 'Planner' },
  { to: '/settings', label: 'Settings' },
]

export default function NavBar() {
  const navigate = useNavigate()
  const logout = useAuthStore((s) => s.logout)
  const open = useCommandPalette((s) => s.open)

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <nav className="border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <span className="flex items-center gap-1.5 text-base font-bold tracking-tight">
            <Zap className="h-4 w-4 text-cyan-500" aria-hidden />
            <span className="text-gradient-electric">PlugTrack</span>
          </span>
          <ul className="flex gap-1">
            {links.map((link) => (
              <li key={link.to}>
                <NavLink
                  to={link.to}
                  className={({ isActive }) =>
                    `rounded-md px-3 py-1.5 text-sm transition ${
                      isActive
                        ? 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300'
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100'
                    }`
                  }
                >
                  {link.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => open()}
            className="gap-2 text-slate-500"
          >
            <Search className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden sm:inline">Search…</span>
            <kbd className="hidden rounded border border-slate-300 bg-slate-50 px-1.5 text-[10px] sm:inline dark:border-slate-700 dark:bg-slate-900">
              ⌘K
            </kbd>
          </Button>
          <button
            type="button"
            onClick={handleLogout}
            className="rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Log out
          </button>
        </div>
      </div>
    </nav>
  )
}
