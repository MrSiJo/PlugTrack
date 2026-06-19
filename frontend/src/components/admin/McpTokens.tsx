/**
 * McpTokens — Admin panel for managing MCP / API bearer tokens.
 *
 * Users can:
 * - List their existing MCP tokens (id, name, scope, created, last-used).
 * - Mint a new token (name + scope). The plaintext token is shown ONCE with
 *   a copy button and a "store now" warning.
 * - Revoke any of their tokens.
 *
 * Security: the list endpoint never returns the token or hash. The plaintext
 * is held in local state only until the user dismisses it.
 */

import { useEffect, useState, useCallback } from 'react'
import { api } from '@/api/client'
import type { McpTokenListItem } from '@/api/client'
import { Button } from '@/components/ui/button'

function formatDate(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    ` ${pad(d.getHours())}:${pad(d.getMinutes())}`
  )
}

export function McpTokens() {
  const [tokens, setTokens] = useState<McpTokenListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Create form state
  const [name, setName] = useState('')
  const [scope, setScope] = useState<'read' | 'readwrite'>('read')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Once-shown plaintext token after mint
  const [newToken, setNewToken] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const loadTokens = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const rows = await api.listMcpTokens()
      setTokens(rows)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tokens')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadTokens()
  }, [loadTokens])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    setCreateError(null)
    setNewToken(null)
    try {
      const result = await api.createMcpToken(name.trim(), scope)
      setNewToken(result.token)
      setName('')
      setScope('read')
      await loadTokens()
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create token')
    } finally {
      setCreating(false)
    }
  }

  async function handleRevoke(id: number) {
    try {
      await api.revokeMcpToken(id)
      await loadTokens()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke token')
    }
  }

  async function handleCopy() {
    if (!newToken) return
    try {
      await navigator.clipboard.writeText(newToken)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard API not available in tests / some environments
    }
  }

  return (
    <section
      data-testid="mcp-tokens-panel"
      className="rounded-lg border border-slate-200 dark:border-slate-700 p-6 space-y-6"
    >
      <div>
        <h2 className="text-lg font-semibold">MCP / API tokens</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Bearer tokens for remote MCP clients (e.g. Claude Desktop). Each token
          is shown once at creation and hashed at rest.
        </p>
      </div>

      {/* Once-shown new token box */}
      {newToken && (
        <div className="rounded-md border border-amber-300 bg-amber-50 dark:border-amber-600 dark:bg-amber-900/20 p-4 space-y-3">
          <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">
            Store this token now — it won&apos;t be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code
              data-testid="mcp-token-new-value"
              className="flex-1 rounded bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 px-3 py-2 text-sm font-mono break-all"
            >
              {newToken}
            </code>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void handleCopy()}
            >
              {copied ? 'Copied!' : 'Copy'}
            </Button>
          </div>
          <button
            type="button"
            className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 underline"
            onClick={() => setNewToken(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Token list */}
      <div>
        <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
          Your tokens
        </h3>
        {loading && (
          <p className="text-sm text-slate-400">Loading...</p>
        )}
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        )}
        {!loading && tokens.length === 0 && (
          <p className="text-sm text-slate-400 dark:text-slate-500">No tokens yet.</p>
        )}
        {tokens.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
                  <th className="pb-2 pr-4 font-medium">Name</th>
                  <th className="pb-2 pr-4 font-medium">Scope</th>
                  <th className="pb-2 pr-4 font-medium">Created</th>
                  <th className="pb-2 pr-4 font-medium">Last used</th>
                  <th className="pb-2 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {tokens.map((tok) => (
                  <tr key={tok.id}>
                    <td className="py-2 pr-4 font-medium">{tok.name}</td>
                    <td className="py-2 pr-4">
                      <span className="rounded-full px-2 py-0.5 text-xs bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                        {tok.scope}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-slate-500 dark:text-slate-400">
                      {formatDate(tok.created_at)}
                    </td>
                    <td className="py-2 pr-4 text-slate-500 dark:text-slate-400">
                      {tok.last_used_at ? formatDate(tok.last_used_at) : '—'}
                    </td>
                    <td className="py-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        data-testid={`mcp-token-revoke-${tok.id}`}
                        onClick={() => void handleRevoke(tok.id)}
                        className="text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 border-red-200 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-900/20"
                      >
                        Revoke
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create token form */}
      <form
        data-testid="mcp-token-create"
        onSubmit={(e) => void handleCreate(e)}
        className="border-t border-slate-200 dark:border-slate-700 pt-6 space-y-4"
      >
        <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300">
          Create token
        </h3>
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            data-testid="mcp-token-name"
            type="text"
            placeholder="Token name (e.g. Claude Desktop)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="flex-1 rounded-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500 dark:text-slate-100"
          />
          <select
            data-testid="mcp-token-scope"
            value={scope}
            onChange={(e) => setScope(e.target.value as 'read' | 'readwrite')}
            className="rounded-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500 dark:text-slate-100"
          >
            <option value="read">read</option>
            <option value="readwrite">readwrite</option>
          </select>
          <Button type="submit" disabled={creating || !name.trim()}>
            {creating ? 'Creating…' : 'Create token'}
          </Button>
        </div>
        {createError && (
          <p className="text-sm text-red-600 dark:text-red-400">{createError}</p>
        )}
      </form>
    </section>
  )
}
