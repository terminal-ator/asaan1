import assert from 'node:assert/strict'
import test from 'node:test'
import { cartTotals, lineAmount, schemeOf } from '../src/pricing.ts'

test('a scheme comes off the line amount', () => {
  assert.equal(lineAmount({ quantity: 3, rate: 11800, scheme: 3 }), 34338)
  assert.equal(lineAmount({ quantity: 2, rate: 5000 }), 10000)
})

test('cart totals report the scheme savings', () => {
  assert.deepEqual(cartTotals([{ quantity: 3, rate: 10000, scheme: 3 }, { quantity: 1, rate: 5000 }]), { gross: 35000, total: 34100, savings: 900 })
})

test('scheme percent from the API is clamped and tolerant', () => {
  assert.equal(schemeOf({ schemePercent: '3.00' }), 3)
  assert.equal(schemeOf({}), 0)
  assert.equal(schemeOf({ schemePercent: '250' }), 100)
})
