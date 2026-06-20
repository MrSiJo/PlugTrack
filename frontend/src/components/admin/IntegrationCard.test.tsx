import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as settingsStoreModule from '@/stores/settingsStore'
import { IntegrationCard } from './IntegrationCard'
import type { IntegrationDef } from '@/config/integrations'
import { INTEGRATIONS } from '@/config/integrations'
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

  it('Telegram integration card config includes all three digest setting keys', () => {
    const telegramDef = INTEGRATIONS.find((d) => d.key === 'telegram')
    expect(telegramDef).toBeDefined()
    expect(telegramDef!.settingKeys).toContain('digest_weekly_enabled')
    expect(telegramDef!.settingKeys).toContain('digest_monthly_enabled')
    expect(telegramDef!.settingKeys).toContain('digest_send_hour')
    // Confirm hidden markers are NOT present
    expect(telegramDef!.settingKeys).not.toContain('digest_last_weekly_sent')
    expect(telegramDef!.settingKeys).not.toContain('digest_last_monthly_sent')
  })

  it('renders digest fields under Telegram card when bot is enabled', () => {
    const telegramDef = INTEGRATIONS.find((d) => d.key === 'telegram')!
    const settings: SettingsMap = {
      telegram_bot_enabled: {
        key: 'telegram_bot_enabled',
        value: 'true',
        value_type: 'bool',
        group_name: 'telegram',
        label: 'Telegram bot enabled',
        description: null,
        is_secret: false,
      },
      telegram_bot_token: {
        key: 'telegram_bot_token',
        value: '',
        value_type: 'string',
        group_name: 'telegram',
        label: 'Bot token',
        description: null,
        is_secret: true,
      },
      telegram_allowed_user_ids: {
        key: 'telegram_allowed_user_ids',
        value: '',
        value_type: 'string',
        group_name: 'telegram',
        label: 'Allowed user IDs',
        description: null,
        is_secret: false,
      },
      digest_weekly_enabled: {
        key: 'digest_weekly_enabled',
        value: 'false',
        value_type: 'bool',
        group_name: 'telegram',
        label: 'Weekly digest enabled',
        description: null,
        is_secret: false,
      },
      digest_monthly_enabled: {
        key: 'digest_monthly_enabled',
        value: 'false',
        value_type: 'bool',
        group_name: 'telegram',
        label: 'Monthly digest enabled',
        description: null,
        is_secret: false,
      },
      digest_send_hour: {
        key: 'digest_send_hour',
        value: '8',
        value_type: 'int',
        group_name: 'telegram',
        label: 'Digest send hour',
        description: null,
        is_secret: false,
      },
    }

    settingsStoreModule.useSettingsStore.setState(
      { settings, loaded: true, loading: false, error: null, set: mockSet } as unknown as Parameters<typeof settingsStoreModule.useSettingsStore.setState>[0],
    )

    render(<IntegrationCard def={telegramDef} />)

    expect(screen.getByLabelText(/Weekly digest enabled/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Monthly digest enabled/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Digest send hour/i)).toBeInTheDocument()
  })

  it('master toggle syncs to true when store hydrates after mount (empty → true)', async () => {
    // Start with an empty settings store (simulates the card mounting before
    // the async settings load has completed — masterStoredValue is undefined).
    // When settings is empty, masterEntry is undefined so the aria-label falls
    // back to the def.label + " enabled" fallback → "AI enabled".
    settingsStoreModule.useSettingsStore.setState(
      { settings: {}, loaded: false, loading: true, error: null, set: mockSet } as unknown as Parameters<typeof settingsStoreModule.useSettingsStore.setState>[0],
    )

    render(<IntegrationCard def={AI_DEF} />)

    // Initially the master toggle must be unchecked (store empty → no value → false).
    // The aria-label at this point is the fallback "AI enabled" (no catalogue label yet).
    const masterCheckbox = screen.getByRole('checkbox', { name: /AI enabled/i })
    expect(masterCheckbox).not.toBeChecked()

    // Simulate the store hydrating: settings arrive with ai_enabled = 'true'.
    await act(async () => {
      settingsStoreModule.useSettingsStore.setState(
        { settings: makeSettings('true'), loaded: true, loading: false, error: null, set: mockSet } as unknown as Parameters<typeof settingsStoreModule.useSettingsStore.setState>[0],
      )
    })

    // After hydration the toggle must now be checked.
    // aria-label is now "AI features enabled" (from the catalogue entry label).
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: /AI features enabled/i })).toBeChecked()
    })

    // And the member field must be enabled (un-greyed).
    await waitFor(() => {
      expect(screen.getByLabelText(/AI provider/i)).not.toBeDisabled()
    })
  })
})
