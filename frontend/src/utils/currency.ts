/**
 * Currency formatting helpers.
 *
 * The backend stores all money as integer pence (or whatever the
 * minor-unit equivalent is for the user's chosen currency). The UI
 * converts on display only. We default to GBP/£; other ISO 4217 codes
 * fall back to `Intl.NumberFormat` so the symbol is correct.
 */

const MINOR_UNIT_DIVISOR = 100

export interface CurrencyInfo {
  code: string
  symbol: string
}

const KNOWN: Record<string, CurrencyInfo> = {
  GBP: { code: 'GBP', symbol: '£' },
  USD: { code: 'USD', symbol: '$' },
  EUR: { code: 'EUR', symbol: '€' },
}

export function getCurrencyInfo(code: string | null | undefined): CurrencyInfo {
  const upper = (code ?? 'GBP').toUpperCase()
  return KNOWN[upper] ?? { code: upper, symbol: upper + ' ' }
}

/**
 * Format a pence (minor-unit) value in the user's chosen currency.
 *
 * - `null` / `undefined` → `'—'`
 * - 0 pence → renders as e.g. `'£0.00'`
 * - non-GBP falls back to Intl.NumberFormat for the correct symbol.
 */
export function formatCurrency(
  pence: number | null | undefined,
  code: string | null | undefined = 'GBP',
): string {
  if (pence === null || pence === undefined) return '—'
  const info = getCurrencyInfo(code)
  const value = pence / MINOR_UNIT_DIVISOR
  if (info.code === 'GBP') {
    return `£${value.toFixed(2)}`
  }
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: info.code,
    }).format(value)
  } catch {
    return `${info.symbol}${value.toFixed(2)}`
  }
}
