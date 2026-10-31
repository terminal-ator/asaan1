import assert from 'node:assert/strict'
import test from 'node:test'
import { recommendedProducts, resolveBundles } from '../src/bundles.ts'

const products = [
  { id: 'soap', sku: 'SOAP', name: 'Soap', unit: 'case', rate: 10000, rateInclusive: 11800 },
  { id: 'tea', sku: 'TEA', name: 'Tea', unit: 'box', rate: 20000, gstRate: '5' },
  { id: 'cream', sku: 'CREAM', name: 'Cream', unit: 'pcs', rate: 3000 },
]
const bundles = [
  { id: 'care', name: 'Care', shopType: 'kirana', description: '', items: [{ productId: 'soap', quantity: 2 }] },
  { id: 'essentials', name: 'Essentials', shopType: 'kirana', description: '', items: [{ productId: 'soap', quantity: 1 }, { productId: 'tea', quantity: 3 }, { productId: 'removed', quantity: 1 }] },
  { id: 'beauty', name: 'Beauty', shopType: 'cosmetics', description: '', items: [{ productId: 'cream', quantity: 2 }] },
]

test('selected bundles recommend unique available products for the chosen shop type', () => {
  const snapshot = JSON.stringify({ products, bundles })
  assert.deepEqual(recommendedProducts(bundles, products, 'kirana', ['care', 'essentials', 'beauty']).map(product => product.id), ['soap', 'tea'])
  assert.equal(JSON.stringify({ products, bundles }), snapshot)
})

test('no selection, stale selection, and wrong shop type produce no recommendations', () => {
  for (const [type, ids] of [['kirana', []], ['kirana', ['deleted']], ['cosmetics', ['care']], ['', ['care']]]) {
    assert.deepEqual(recommendedProducts(bundles, products, type, ids), [])
  }
})

test('bundle previews use tax-inclusive prices and ignore unavailable products', () => {
  const preview = resolveBundles(bundles, products, 'kirana')
  assert.equal(preview[0].total, 23600)
  assert.equal(preview[1].total, 11800 + 3 * 21000)
  assert.equal(preview[1].items.length, 2)
})

test('removed products and invalid quantities cannot produce recommendations', () => {
  const invalid = { id: 'invalid', name: 'Invalid', shopType: 'kirana', description: '', items: [
    { productId: 'removed', quantity: 1 }, { productId: 'soap', quantity: 0 },
    { productId: 'tea', quantity: 1.5 }, { productId: 'cream', quantity: 100001 },
  ] }
  assert.deepEqual(resolveBundles([invalid], products, 'kirana'), [])
  assert.deepEqual(recommendedProducts(bundles, products.slice(1), 'kirana', ['care']), [])
})
