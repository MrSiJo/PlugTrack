/**
 * MaintenancePanel — informational panel listing CLI maintenance commands,
 * plus Backup & Export UI.
 *
 * The CSV import and location backfill remain server-side CLI operations.
 *
 * Used in AdminPage's Maintenance section.
 */

import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import { Button } from '@/components/ui/button'

interface BackupEntry {
  name: string
  size_bytes: number
  created_at: string
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

function formatDate(iso: string): string {
  // Format as YYYY-MM-DD HH:MM in local time
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    ` ${pad(d.getHours())}:${pad(d.getMinutes())}`
  )
}

export function MaintenancePanel() {
  const [backups, setBackups] = useState<BackupEntry[]>([])
  const [backupsLoading, setBackupsLoading] = useState(true)
  const [backingUp, setBackingUp] = useState(false)
  const [backupResult, setBackupResult] = useState<string | null>(null)
  const [backupError, setBackupError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  async function loadBackups() {
    setBackupsLoading(true)
    try {
      const list = await api.listBackups()
      setBackups(list)
    } catch {
      // Non-fatal — leave list empty
    } finally {
      setBackupsLoading(false)
    }
  }

  useEffect(() => {
    void loadBackups()
  }, [])

  async function handleBackupNow() {
    setBackingUp(true)
    setBackupResult(null)
    setBackupError(null)
    try {
      const result = await api.backupNow()
      setBackupResult(`Backup created: ${result.name}`)
      await loadBackups()
    } catch (err) {
      setBackupError(err instanceof Error ? err.message : 'Backup failed')
    } finally {
      setBackingUp(false)
    }
  }

  async function handleExport(format: 'csv' | 'json') {
    setExportError(null)
    try {
      await api.exportSessions(format)
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Export failed')
    }
  }

  return (
    <div
      className="rounded border border-slate-200 p-4 dark:border-slate-700"
      data-testid="maintenance-panel"
    >
      <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
        The following operations are run directly on the server as CLI commands.
        They are not available through the UI.
      </p>

      <ul className="space-y-4">
        <li>
          <p className="mb-1 text-sm font-medium text-slate-700 dark:text-slate-300">
            MyCupra CSV import
          </p>
          <code className="block rounded bg-slate-100 px-3 py-2 font-mono text-xs text-slate-800 dark:bg-slate-800 dark:text-slate-200">
            python -m plugtrack.scripts.import_mycupra_csv
          </code>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Imports charging sessions from a MyCupra CSV export. Runs dry-run by
            default; pass <code className="font-mono">--commit</code> to write.
          </p>
        </li>

        <li>
          <p className="mb-1 text-sm font-medium text-slate-700 dark:text-slate-300">
            Location backfill
          </p>
          <code className="block rounded bg-slate-100 px-3 py-2 font-mono text-xs text-slate-800 dark:bg-slate-800 dark:text-slate-200">
            python -m plugtrack.scripts.backfill_import_locations
          </code>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Re-clusters and geocodes session coordinates to regenerate location
            records. Useful after importing historical data.
          </p>
        </li>
      </ul>

      {/* Backups subsection */}
      <div className="mt-6 border-t border-slate-200 pt-4 dark:border-slate-700">
        <div className="mb-3 flex items-center gap-3">
          <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Backups
          </h3>
          <Button
            size="sm"
            variant="outline"
            data-testid="backup-now-button"
            onClick={() => void handleBackupNow()}
            disabled={backingUp}
          >
            {backingUp ? 'Backing up…' : 'Back up now'}
          </Button>
        </div>

        {backupResult && (
          <p className="mb-2 text-xs text-green-600 dark:text-green-400">{backupResult}</p>
        )}
        {backupError && (
          <p className="mb-2 text-xs text-red-600 dark:text-red-400">{backupError}</p>
        )}

        {backupsLoading ? (
          <p className="text-xs text-slate-400 dark:text-slate-500">Loading backups…</p>
        ) : backups.length === 0 ? (
          <p className="text-xs text-slate-400 dark:text-slate-500">No backups yet.</p>
        ) : (
          <ul
            className="divide-y divide-slate-100 rounded border border-slate-200 dark:divide-slate-700 dark:border-slate-700"
            data-testid="backups-list"
          >
            {backups.map((b) => (
              <li
                key={b.name}
                className="flex items-center justify-between gap-4 px-3 py-2 text-xs"
              >
                <span className="flex-1 truncate font-mono text-slate-700 dark:text-slate-300">
                  {b.name}
                </span>
                <span className="text-slate-500 dark:text-slate-400 shrink-0">
                  {formatBytes(b.size_bytes)}
                </span>
                <span className="text-slate-500 dark:text-slate-400 shrink-0">
                  {formatDate(b.created_at)}
                </span>
                <a
                  href={api.backupDownloadUrl(b.name)}
                  className="shrink-0 text-blue-600 underline hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
                  download
                >
                  Download
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Export subsection */}
      <div className="mt-6 border-t border-slate-200 pt-4 dark:border-slate-700">
        <h3 className="mb-3 text-sm font-medium text-slate-700 dark:text-slate-300">
          Export sessions
        </h3>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            data-testid="export-sessions-csv"
            onClick={() => void handleExport('csv')}
          >
            Export CSV
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid="export-sessions-json"
            onClick={() => void handleExport('json')}
          >
            Export JSON
          </Button>
        </div>
        {exportError && (
          <p className="mt-2 text-xs text-red-600 dark:text-red-400">{exportError}</p>
        )}
      </div>
    </div>
  )
}
