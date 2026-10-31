export type ShopType = { id: string; name: string }
export type ProductBundle = { id: string; name: string; shopType: string; description: string; items: { productId: string; quantity: number }[] }
export type BundleProduct = { id: string; sku: string; name: string; simpleName?: string; unit: string; packing?: string; rate: number; rateInclusive?: number; gstRate?: string }

// New catalogue prices include tax explicitly. Older offline copies need conversion.
export const inclusiveRate = (product: { rate: number; rateInclusive?: number; gstRate?: string }) => product.rateInclusive ?? product.rate + Math.round(product.rate * (Number(product.gstRate) || 0) / 100)

export function resolveBundles(bundles: ProductBundle[], products: BundleProduct[], shopType: string) {
  const byId = new Map(products.map(product => [product.id, product]))
  return bundles.filter(bundle => bundle.shopType === shopType).flatMap(bundle => {
    const items = bundle.items.flatMap(item => {
      const product = byId.get(item.productId)
      return product && Number.isInteger(item.quantity) && item.quantity > 0 && item.quantity <= 100_000
        ? [{ product, quantity: item.quantity }] : []
    })
    return items.length ? [{ ...bundle, items, total: items.reduce((sum, item) => sum + inclusiveRate(item.product) * item.quantity, 0) }] : []
  })
}

export function recommendedProducts<T extends BundleProduct>(bundles: ProductBundle[], products: T[], shopType: string, selectedIds: string[]): T[] {
  const ids = new Set(resolveBundles(bundles, products, shopType)
    .filter(bundle => selectedIds.includes(bundle.id))
    .flatMap(bundle => bundle.items.map(item => item.product.id)))
  return products.filter(product => ids.has(product.id))
}
