import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as settingsStoreModule from '@/stores/settingsStore'
import { IntegrationCard } from './IntegrationCard'
import type { IntegrationDef } from '@/config/integrations'
import type { SettingsMap } from '@/api/client'

// Minimal AI integration definition for tests.
const AI_DEF: IntegrationDef = {
  key: 'ai',
  label: 'AI',
  masterKey: 'ai_enabled',
  settingKeys: ['ai_provider', 'openai_model'],
  actions: ['testOpenai'],
}

/** Build a minimal SettingsMap for the AI integration. */
function makeSettings(masterValue: string): SettingsMap {
  return {
    ai_enabled: {
      key: 'ai_enabled',
      value: masterValue,
      value_type: 'bool',
      group_name: 'ai',
      label: 'AI features enabled',
      description: 'Master switch for AI features.',
      is_secret: false,
    },
    ai_provider: {
      key: 'ai_provider',
      value: 'openai',
      value_type: 'enum',
      group_name: 'ai',
      label: 'AI provider',
      description: null,
      is_secret: false,
    },
    openai_model: {
      key: 'openai_model',
      value: 'gpt-4o-mini',
      value_type: 'string',
      group_name: 'ai',
      label: 'OpenAI vision model',
      description: null,
      is_secret: false,
    },
  }
}

describe('IntegrationCard', () => {
  let mockSet: ReturnType<typeof vi.fn>

  beforeEach(() => {
    mockSet = vi.fn().mockResolvedValue(undefined)

    // Mock getOpenAiModels so ModelSelect doesn't error in tests
    vi.mock('@/api/client', async (importOriginal) => {
      const actual = await importOriginal<typeof import('@/api/client')>()
      return {
        ...actual,
        api: {
          ...actual.api,
          getOpenAiModels: vi.fn().mockRejectedValue(new Error('no key')),
          testTelegram: vi.fn(),
        },
      }
    })
  })

  it('greys member settings (disabled) when master toggle is off', () => {
    settingsStoreModule.useSettingsStore.setState(
      { settings: makeSettings('false'), loaded: true, loading: false, error: null, set: mockSet } as unknown as Parameters<typeof settingsStoreModule.useSettingsStore.setState>[0],
    )

    render(<IntegrationCard def={AI_DEF} />)

    // The ai_provider select should be disabled when master is off
    const providerSelect = screen.getByLabelText(/AI provider/i)
    expect(providerSelect).toBeDisabled()
  })

  it('un-greys member settings when master toggle is clicked on', async () => {
    settingsStoreModule.useSettingsStore.setState(
      { settings: makeSettings('false'), loaded: true, loading: false, error: null, set: mockSet } as unknown as Parameters<typeof settingsStoreModule.useSettingsStore.setState>[0],
    )

    render(<IntegrationCard def={AI_DEF} />)

    // Master toggle is a checkbox
    const masterCheckbox = screen.getByRole('checkbox', { name: /AI features enabled/i })
    expect(screen.getByLabelText(/AI provider/i)).toBeDisabled()

    fireEvent.click(masterCheckbox)

    // After toggling on, the member field should be enabled
    await waitFor(() => {
      expect(screen.getByLabelText(/AI provider/i)).not.toBeDisabled()
    })
  })

  it('Save persists master + dirty members', async () => {
    settingsStoreModule.useSettingsStore.setState(
      { settings: makeSettings('false'), loaded: true, loading: false, error: null, set: mockSet } as unknown as Parameters<typeof settingsStoreModule.useSettingsStore.setState>[0],
    )

    render(<IntegrationCard def={AI_DEF} />)

    // Toggle master on
    fireEvent.click(screen.getByRole('checkbox', { name: /AI features enabled/i }))

    // Click Save
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    // Should call set with the master key
    await waitFor(() => {
      expect(mockSet).toHaveBeenCalledWith('ai_enabled', 'true')
    })
  })

  it('shows Saved. feedback after successful save', async () => {
    settingsStoreModule.useSettingsStore.setState(
      { settings: makeSettings('true'), loaded: true, loading: false, error: null, set: mockSet } as unknown as Parameters<typeof settingsStoreModule.useSettingsStore.setState>[0],
    )

    render(<IntegrationCard def={AI_DEF} />)

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(screen.getByText('Saved.')).toBeInTheDocument()
    })
  })
})
