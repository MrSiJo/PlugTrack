import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { api } from '@/api/client'
import { MaintenancePanel } from './MaintenancePanel'

// Mock api so no real fetches happen
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      backupNow: vi.fn(),
      listBackups: vi.fn(),
      backupDownloadUrl: vi.fn(
        (name: string) =>
          `/api/maintenance/backups/${encodeURIComponent(name)}/download`,
      ),
      exportSessions: vi.fn(),
    },
  }
})

const MOCK_BACKUP = {
  name: 'plugtrack-2026-06-19T120000.db',
  size_bytes: 204800,
  created_at: '2026-06-19T12:00:00Z',
}

describe('MaintenancePanel', () => {
  beforeEach(() => {
    vi.mocked(api.listBackups).mockResolvedValue([])
    vi.mocked(api.backupNow).mockResolvedValue(MOCK_BACKUP)
    vi.mocked(api.exportSessions).mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  // --- Existing tests must keep passing ---

  it('renders the panel with the maintenance-panel testid', () => {
    render(<MaintenancePanel />)
    expect(screen.getByTestId('maintenance-panel')).toBeInTheDocument()
  })

  it('shows the MyCupra CSV import command', () => {
    render(<MaintenancePanel />)
    expect(
      screen.getByText('python -m plugtrack.scripts.import_mycupra_csv'),
    ).toBeInTheDocument()
  })

  it('shows the location backfill command', () => {
    render(<MaintenancePanel />)
    expect(
      screen.getByText('python -m plugtrack.scripts.backfill_import_locations'),
    ).toBeInTheDocument()
  })

  // --- New backup tests ---

  it('calls api.listBackups on mount', async () => {
    render(<MaintenancePanel />)
    await waitFor(() => expect(vi.mocked(api.listBackups)).toHaveBeenCalledTimes(1))
  })

  it('shows empty-state text when no backups exist', async () => {
    vi.mocked(api.listBackups).mockResolvedValue([])
    render(<MaintenancePanel />)
    await waitFor(() =>
      expect(screen.getByText(/no backups yet/i)).toBeInTheDocument(),
    )
  })

  it('renders a backup row with name, size, date, and download link when backups exist', async () => {
    vi.mocked(api.listBackups).mockResolvedValue([MOCK_BACKUP])
    render(<MaintenancePanel />)

    await waitFor(() =>
      expect(screen.getByTestId('backups-list')).toBeInTheDocument(),
    )

    const list = screen.getByTestId('backups-list')
    expect(list).toHaveTextContent('plugtrack-2026-06-19T120000.db')
    // Human-readable size (200 KB)
    expect(list).toHaveTextContent('KB')

    // Download link href should contain the backup name
    const link = screen.getByRole('link', { name: /download/i })
    expect(link.getAttribute('href')).toContain('plugtrack-2026-06-19T120000.db')
  })

  it('clicking backup-now-button calls api.backupNow then api.listBackups', async () => {
    vi.mocked(api.listBackups).mockResolvedValue([])
    render(<MaintenancePanel />)

    // Wait for mount list call
    await waitFor(() => expect(vi.mocked(api.listBackups)).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByTestId('backup-now-button'))

    await waitFor(() => expect(vi.mocked(api.backupNow)).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(vi.mocked(api.listBackups)).toHaveBeenCalledTimes(2))
  })

  // --- Export tests ---

  it('clicking export-sessions-csv calls api.exportSessions with csv', async () => {
    render(<MaintenancePanel />)
    fireEvent.click(screen.getByTestId('export-sessions-csv'))
    await waitFor(() =>
      expect(vi.mocked(api.exportSessions)).toHaveBeenCalledWith('csv'),
    )
  })

  it('clicking export-sessions-json calls api.exportSessions with json', async () => {
    render(<MaintenancePanel />)
    fireEvent.click(screen.getByTestId('export-sessions-json'))
    await waitFor(() =>
      expect(vi.mocked(api.exportSessions)).toHaveBeenCalledWith('json'),
    )
  })
})
