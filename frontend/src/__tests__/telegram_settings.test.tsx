import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { TestConnectionPanel, ModelSelect } from '@/pages/SettingsPage'
import { api } from '@/api/client'

vi.mock('@/api/client', async (orig) => {
  const mod = await orig<typeof import('@/api/client')>()
  return { ...mod, api: { ...mod.api } }
})

describe('telegram settings additions', () => {
  it('TestConnectionPanel renders ✓/✗ results', async () => {
    vi.spyOn(api, 'testTelegram').mockResolvedValue({
      all_ok: true, usage_this_month: null,
      checks: [{ name: 'Telegram', ok: true, detail: 'connected as @plugbot' }],
    })
    render(<TestConnectionPanel />)
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }))
    await waitFor(() => expect(screen.getByText(/connected as @plugbot/i)).toBeInTheDocument())
  })

  it('ModelSelect lists models from the API', async () => {
    vi.spyOn(api, 'getOpenAiModels').mockResolvedValue({
      current: 'gpt-5-mini',
      models: [{ id: 'gpt-5-nano', recommended: true }, { id: 'gpt-5.5', recommended: false }],
    })
    render(<ModelSelect value="gpt-5-mini" onChange={() => {}} />)
    await waitFor(() => expect(screen.getByRole('option', { name: /gpt-5-nano/i })).toBeInTheDocument())
  })
})
