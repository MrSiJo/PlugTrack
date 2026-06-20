import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import * as clientModule from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import SettingsPage from '@/pages/SettingsPage'

/**
 * Settings payload exercising the standalone/ingestion groups:
 * - `telegram` group (incl. an encrypted/secret bot token),
 * - `openai` group.
 */
const sample: clientModule.SettingsMap = {
  telegram_bot_enabled: {
    key: 'telegram_bot_enabled',
    value: 'false',
    value_type: 'bool',
    group_name: 'telegram',
    label: 'Telegram bot enabled',
    description: null,
    is_secret: false,
  },
  telegram_bot_token: {
    key: 'telegram_bot_token',
    value: '***',
    value_type: 'string',
    group_name: 'telegram',
    label: 'Telegram bot token',
    description: null,
    is_secret: true,
  },
  openai_api_key: {
    key: 'openai_api_key',
    value: null,
    value_type: 'string',
    group_name: 'openai',
    label: 'OpenAI API key',
    description: null,
    is_secret: true,
  },
  openai_model: {
    key: 'openai_model',
    value: 'gpt-5.5',
    value_type: 'string',
    group_name: 'openai',
    label: 'OpenAI vision model',
    description: null,
    is_secret: false,
  },
}

beforeEach(() => {
  useSettingsStore.setState({
    settings: sample,
    loaded: true,
    loading: false,
    error: null,
  })
  if (!window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: () => ({
        matches: false,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    })
  }
})

describe('SettingsPage new groups', () => {
  it('renders telegram + openai group tabs', async () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('settings-tab-telegram')).toBeInTheDocument()
    expect(screen.getByTestId('settings-tab-openai')).toBeInTheDocument()
  })

  it('masks the telegram bot token as a secret field', async () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByTestId('settings-tab-telegram'))
    // A redacted secret renders as *** with a "Set new value" affordance.
    expect(screen.getByText('Telegram bot token')).toBeInTheDocument()
    expect(screen.getByText('***')).toBeInTheDocument()
    const setNew = screen.getByRole('button', { name: /set new value/i })
    await userEvent.click(setNew)
    // After choosing to set a new value, the input is a password field.
    const input = screen.getByLabelText(/telegram bot token/i) as HTMLInputElement
    expect(input.type).toBe('password')
  })
})
