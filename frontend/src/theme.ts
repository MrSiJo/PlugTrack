/**
 * Theme management — wires the `theme` setting to:
 *   1. <html data-theme="light|dark"> attribute
 *   2. the `dark` class on <html> for Tailwind v4's prefers-color-scheme
 *      override.
 *
 * Resolves 'system' against `prefers-color-scheme: dark` at apply time.
 */
import { useCallback, useEffect } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'

export type ThemeChoice = 'system' | 'light' | 'dark'

function resolveTheme(choice: ThemeChoice): 'light' | 'dark' {
  if (choice === 'light' || choice === 'dark') return choice
  if (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  ) {
    return 'dark'
  }
  return 'light'
}

export function applyThemeToDocument(choice: ThemeChoice): void {
  if (typeof document === 'undefined') return
  const resolved = resolveTheme(choice)
  document.documentElement.dataset.theme = resolved
  document.documentElement.classList.toggle('dark', resolved === 'dark')
}

export function useTheme(): {
  theme: ThemeChoice
  setTheme: (next: ThemeChoice) => Promise<void>
} {
  const stored = useSettingsStore((s) => s.settings['theme']?.value) as
    | ThemeChoice
    | undefined
  const setSetting = useSettingsStore((s) => s.set)
  const theme: ThemeChoice = stored ?? 'system'

  // Re-apply whenever the stored value changes.
  useEffect(() => {
    applyThemeToDocument(theme)
  }, [theme])

  const setTheme = useCallback(
    async (next: ThemeChoice) => {
      // Optimistic apply so the toggle feels instant.
      applyThemeToDocument(next)
      await setSetting('theme', next)
    },
    [setSetting],
  )

  return { theme, setTheme }
}
