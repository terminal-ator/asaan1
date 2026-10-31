// Mirrors catalogue/schemes.py: the scheme comes off the line before rounding,
// and only the best scheme applies (the API already picks it per product).
export type PricedLine = { quantity: number; rate: number; scheme?: number }

export const schemeOf = (product: { schemePercent?: string }) => Math.min(100, Math.max(0, Number(product.schemePercent) || 0))

export const lineAmount = (line: PricedLine) => Math.round(line.quantity * line.rate * (100 - (line.scheme ?? 0)) / 100)

export function cartTotals(lines: PricedLine[]) {
  const gross = lines.reduce((sum, line) => sum + line.quantity * line.rate, 0)
  const total = lines.reduce((sum, line) => sum + lineAmount(line), 0)
  return { gross, total, savings: gross - total }
}
