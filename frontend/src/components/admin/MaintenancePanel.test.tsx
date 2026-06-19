import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MaintenancePanel } from './MaintenancePanel'

describe('MaintenancePanel', () => {
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

  it('mentions that backup and export will appear in a future release', () => {
    render(<MaintenancePanel />)
    expect(
      screen.getByText(/backup & export actions will appear here/i),
    ).toBeInTheDocument()
  })
})
