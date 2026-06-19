/**
 * MaintenancePanel — informational panel listing CLI maintenance commands.
 *
 * The CSV import and location backfill remain server-side CLI operations.
 * Backup & Export actions are planned for a future spec.
 *
 * Used in AdminPage's Maintenance section.
 */

export function MaintenancePanel() {
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

      <p className="mt-6 text-sm text-slate-400 dark:text-slate-500">
        Backup &amp; Export actions will appear here in a future release.
      </p>
    </div>
  )
}
