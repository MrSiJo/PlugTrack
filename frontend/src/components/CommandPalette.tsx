import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { create } from 'zustand'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { useTheme } from '@/theme'

interface CommandPaletteState {
  isOpen: boolean
  open: () => void
  close: () => void
}

export const useCommandPalette = create<CommandPaletteState>((set) => ({
  isOpen: false,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
}))

const NAV_ENTRIES = [
  { label: 'Dashboard', path: '/dashboard' },
  { label: 'Cars', path: '/cars' },
  { label: 'Sessions', path: '/sessions' },
  { label: 'Locations', path: '/locations' },
  { label: 'Settings', path: '/settings' },
] as const

export default function CommandPalette() {
  const navigate = useNavigate()
  const isOpen = useCommandPalette((s) => s.isOpen)
  const close = useCommandPalette((s) => s.close)
  const open = useCommandPalette((s) => s.open)
  const { theme, setTheme } = useTheme()

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        open()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  function go(path: string) {
    navigate(path)
    close()
  }

  return (
    <CommandDialog
      open={isOpen}
      onOpenChange={(v) => (v ? open() : close())}
      title="Command palette"
      description="Search and navigate"
    >
      <CommandInput placeholder="Type a command or search…" />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        <CommandGroup heading="Navigate">
          {NAV_ENTRIES.map((e) => (
            <CommandItem key={e.path} onSelect={() => go(e.path)}>
              {e.label}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Theme">
          <CommandItem
            onSelect={() => {
              void setTheme(theme === 'dark' ? 'light' : 'dark')
              close()
            }}
          >
            Toggle theme (current: {theme})
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}
