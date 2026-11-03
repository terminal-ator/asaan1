import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { useVirtualizer } from '@tanstack/react-virtual'
import Dexie, { type EntityTable } from 'dexie'
import MiniSearch from 'minisearch'
import { cartTotals, lineAmount, schemeOf } from './pricing'
import { inclusiveRate, recommendedProducts, resolveBundles, type ProductBundle, type ShopType } from './bundles'
import './registration.css'
import './styles.css'
import './filters.css'
import './location.css'
import './order-summary.css'
import './cart-button.css'
import './cart-actions.css'
import './product-images.css'
import './categories.css'
import './sales.css'

// Same-origin by default: Vite proxies /api and /media to Django while
// developing, and in production the reverse proxy serves the built PWA next to Django.
const apiURL = import.meta.env.VITE_API_URL ?? ''
// /sales/ is the salesman app: the same ordering screens, installed separately,
// with its own storage and a staff sign-in. Shops never see any of it.
const SALES_APP = /^\/sales(\/|$)/.test(window.location.pathname)
if (window.location.pathname === '/sales') window.location.replace(`/sales/${window.location.search}`)

type CatalogueView = 'all' | 'in-cart' | 'liked' | 'new' | 'regular' | 'usual' | 'deals' | 'discover' | 'recommended'
const PRODUCT_ROW_HEIGHT = 92

type Product = { id: string; sku: string; name: string; simpleName?: string; company: string; brand: string; category: string; packing: string; unit: string; rate: number; rateInclusive?: number; mrp: number; schemePercent?: string; schemeName?: string; gstRate?: string; hsnCode?: string; imageUrl?: string; regular?: boolean; updatedAt: string; createdAt: string }
// `scheme` is the scheme % when the line was priced; refreshed with the catalogue.
type CartItem = Pick<Product, 'id' | 'sku' | 'name' | 'unit' | 'rate'> & { quantity: number; packing?: string; scheme?: number }
type QuantityTarget = Omit<CartItem, 'quantity'> & { simpleName?: string; schemePercent?: string }
type Shop = { id?: number; storeName: string; customerName: string; mobile: string; shopType?: string; bundleIds?: string[]; gstin?: string; address?: string; latitude?: number; longitude?: number; locationAccuracy?: number }
type CatalogueMetadata = { id: 'current'; bundles: ProductBundle[]; shopTypes: ShopType[] }
type Deal = { weekday: number; productId: string; percent: string; note: string }
type LocalOrder = { clientOrderId: string; shop: Shop; items: CartItem[]; notes: string; total: number; createdAt: string; status: 'pending' | 'submitted' | 'failed'; orderNumber?: string; error?: string; serverStatus?: string; takenBy?: string }
// Salesman mode: a signed-in staff member takes orders on a shop's behalf.
type Salesman = { username: string; name: string }
type SalesShop = Shop & { id?: number; orderCount?: number; lastOrderAt?: string | null }
type ShopHistory = { lastOrder: { orderNumber: string; createdAt: string; items: { productId: string; unit: string; quantity: number }[] } | null; usual: string[] }

class AsaanDB extends Dexie {
  products!: EntityTable<Product, 'id'>
  cart!: EntityTable<{ id: 'current'; items: CartItem[] }, 'id'>
  orders!: EntityTable<LocalOrder, 'clientOrderId'>
  likes!: EntityTable<{ id: string }, 'id'>
  metadata!: EntityTable<CatalogueMetadata, 'id'>
  constructor(name: string) {
    super(name)
    this.version(1).stores({ products: 'id, sku, name, company, brand, category', cart: 'id', orders: 'clientOrderId, status, createdAt' })
    // Liked products live on the device: every shop keeps its own shortlist.
    this.version(2).stores({ products: 'id, sku, name, company, brand, category', cart: 'id', orders: 'clientOrderId, status, createdAt', likes: 'id' })
    this.version(3).stores({ metadata: 'id' })
  }
}
// Separate databases so a phone used as both apps keeps two carts and order lists.
const db = new AsaanDB(SALES_APP ? 'asaan-sales' : 'asaan')
const money = (paise: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(paise / 100)
const imageSource = (product: Product) => product.imageUrl?.startsWith('/') ? `${apiURL}${product.imageUrl}` : product.imageUrl
const displayName = (product: Product) => product.simpleName || product.name
// "Pack 2" before "Pack 10", ignoring case.
const naturalOrder = new Intl.Collator('en-IN', { numeric: true, sensitivity: 'base' })
const brandInitials = (brand: string) => {
  const words = brand.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  return (words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)).toUpperCase()
}
// A stable hue per brand so the same brand always gets the same tile colour.
const brandHue = (brand: string) => [...brand].reduce((hue, char) => (hue * 31 + char.charCodeAt(0)) % 360, 7)
// Console statuses, in the words a shop understands.
const STATUS_LABELS: Record<string, string> = { received: 'Received', processing: 'Being packed', completed: 'Completed', cancelled: 'Cancelled' }
const WEEKDAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const statusLabel = (status?: string) => STATUS_LABELS[status ?? ''] ?? (status || '')
// "1 × 12" on a piece-counted product means a case holds 12 pieces, so the
// stepper moves in cases. A product already counted in cases keeps step 1.
const caseSize = (packing?: string, unit?: string) => {
  const match = packing?.match(/[×x]\s*(\d{1,4})/)
  if (!match) return 1
  const pieceUnit = unit ? /pcs|piece|nos|unit|packet|sachet|bottle|tube|bar/i.test(unit) : false
  return pieceUnit ? Math.max(1, Number(match[1])) : 1
}
// Push subscriptions want the VAPID key as bytes, not base64url.
const urlBase64ToUint8Array = (base64: string) => {
  const padding = '='.repeat((4 - base64.length % 4) % 4)
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, character => character.charCodeAt(0))
}
// A shop profile without a name or mobile is useless for billing, so treat it
// as not set up and ask for the details again.
const hasShopDetails = (shop: Shop | null): shop is Shop => Boolean(shop?.storeName?.trim() && shop?.mobile?.trim())
const sameShop = (a: Shop, b: Shop) => a.mobile === b.mobile && a.storeName === b.storeName
const readJSON = <T,>(key: string): T | null => { try { return JSON.parse(localStorage.getItem(key) || 'null') as T | null } catch { return null } }
// Django wants the CSRF cookie echoed back on signed-in requests.
const csrfToken = () => document.cookie.split('; ').find(part => part.startsWith('csrftoken='))?.slice('csrftoken='.length) ?? ''
const salesLoginURL = () => `${apiURL}/admin/login/?next=${encodeURIComponent('/sales/')}`
// Used by the header menu: drop the offline copies and start clean.
async function clearCacheAndReload() {
  try {
    if ('caches' in window) for (const key of await caches.keys()) await caches.delete(key)
    if ('serviceWorker' in navigator) for (const registration of await navigator.serviceWorker.getRegistrations()) await registration.unregister()
  } finally { window.location.reload() }
}

function App() {
  const [ownShop, setOwnShop] = useState<Shop | null>(() => SALES_APP ? null : readJSON<Shop>('asaan-shop'))
  const [salesman, setSalesman] = useState<Salesman | null>(() => SALES_APP ? readJSON<Salesman>('asaan-salesman') : null)
  const [salesShop, setSalesShop] = useState<SalesShop | null>(() => SALES_APP ? readJSON<SalesShop>('asaan-sales-shop') : null)
  const [salesGate, setSalesGate] = useState<'checking' | 'signed-out' | 'offline'>('checking')
  const [shopHistory, setShopHistory] = useState<ShopHistory | null>(null)
  // Everything below orders for this shop: the device's own, or the one the salesman is visiting.
  const shop = salesman ? salesShop : ownShop
  const [products, setProducts] = useState<Product[]>([])
  const [cart, setCart] = useState<CartItem[]>([])
  const [query, setQuery] = useState('')
  const [company, setCompany] = useState('')
  const [brand, setBrand] = useState('')
  const [screen, setScreen] = useState<'catalogue' | 'cart' | 'orders' | 'setup' | 'shops'>('catalogue')
  const [message, setMessage] = useState('')
  const [likes, setLikes] = useState<string[]>([])
  const [catalogueView, setCatalogueView] = useState<CatalogueView>('all')
  const [discoverSeed, setDiscoverSeed] = useState(0)
  const cartRef = useRef<CartItem[]>([])
  const [history, setHistory] = useState<LocalOrder[]>([])
  const [supportPhone, setSupportPhone] = useState('')
  const [pushAvailable, setPushAvailable] = useState(false)
  const [pushEnabled, setPushEnabled] = useState(false)
  const [deals, setDeals] = useState<Deal[]>([])
  const [bundles, setBundles] = useState<ProductBundle[]>([])
  const [shopTypes, setShopTypes] = useState<ShopType[]>([])
  const [catalogueLoading, setCatalogueLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      setProducts(await db.products.toArray())
      const metadata = await db.metadata.get('current')
      setBundles(metadata?.bundles ?? [])
      setShopTypes(metadata?.shopTypes ?? [])
      setLikes((await db.likes.toArray()).map(like => like.id))
      const savedCart = (await db.cart.get('current'))?.items ?? []
      cartRef.current = savedCart
      setCart(savedCart)
      await loadHistory()
      await refreshCatalogue()
      await retryPendingOrders()
      await refreshStatuses()
      await checkPush()
    })()
    // First open of the salesman app, or back from the staff sign-in page.
    if (SALES_APP && !readJSON<Salesman>('asaan-salesman')) void signIn()
    // A cache-first service worker is useful after deployment, but makes local
    // development appear stale after an edit.
    if (import.meta.env.PROD && 'serviceWorker' in navigator) void navigator.serviceWorker.register('/sw.js')
  }, [])

  // The catalogue changes during the day. Refresh when the app returns to the
  // foreground or the connection comes back, not only on a cold start.
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible') { void refreshCatalogue(); void refreshStatuses() } }
    document.addEventListener('visibilitychange', refresh)
    window.addEventListener('online', refresh)
    return () => {
      document.removeEventListener('visibilitychange', refresh)
      window.removeEventListener('online', refresh)
    }
  }, [])

  async function loadHistory() {
    setHistory(await db.orders.orderBy('createdAt').reverse().toArray())
  }

  async function refreshStatuses() {
    const orders = await db.orders.toArray()
    if (!orders.length) return
    try {
      const response = await fetch(`${apiURL}/api/orders/status?ids=${orders.map(order => order.clientOrderId).join(',')}`)
      if (!response.ok) return
      const payload = await response.json() as { orders: { clientOrderId: string; orderNumber: string; status: string }[] }
      for (const entry of payload.orders) {
        const order = orders.find(candidate => candidate.clientOrderId === entry.clientOrderId)
        if (!order || order.serverStatus === entry.status) continue
        await db.orders.put({ ...order, orderNumber: entry.orderNumber, serverStatus: entry.status })
        // Only announce a change once we already knew the previous status.
        if (order.serverStatus) notifyStatus(order, entry.status)
      }
      await loadHistory()
    } catch { /* offline; the next open checks again */ }
  }

  function notifyStatus(order: LocalOrder, status: string) {
    const text = `Order ${order.orderNumber ?? ''} · ${statusLabel(status)}`
    setMessage(text)
    if ('Notification' in window && Notification.permission === 'granted' && 'serviceWorker' in navigator) {
      void navigator.serviceWorker.ready
        .then(registration => registration.showNotification('Asaan order update', { body: text, icon: '/icon.svg', badge: '/icon.svg', data: { url: '/' } }))
        .catch(() => { /* the in-app notice is enough */ })
    }
  }

  async function checkPush() {
    try {
      const response = await fetch(`${apiURL}/api/push/key`)
      if (!response.ok) return
      const payload = await response.json() as { key: string }
      setPushAvailable(Boolean(payload.key))
      if ('serviceWorker' in navigator) {
        const registration = await navigator.serviceWorker.ready
        setPushEnabled(Boolean(await registration.pushManager.getSubscription()))
      }
    } catch { /* offline */ }
  }

  async function enableNotifications() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) { setMessage('This browser cannot show order updates.'); return }
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') { setMessage('Notifications were not allowed.'); return }
      const response = await fetch(`${apiURL}/api/push/key`)
      const { key } = await response.json() as { key: string }
      if (!key) { setMessage('Order updates are not set up yet.'); return }
      const registration = await navigator.serviceWorker.ready
      const subscription = (await registration.pushManager.getSubscription()) ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) })
      await fetch(`${apiURL}/api/push/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mobile: shop?.mobile ?? '', subscription: subscription.toJSON() }),
      })
      setPushEnabled(true)
      setMessage('Order updates are on for this device.')
    } catch { setMessage('Could not turn on order updates. Try again later.') }
  }

  function shareOrder(order: LocalOrder) {
    const lines = order.items.slice(0, 40).map(item => `• ${item.name} — ${item.quantity} ${item.unit}`)
    const text = `Order ${order.orderNumber ?? order.clientOrderId.slice(0, 8)}\n${lines.join('\n')}\nTentative total: ${money(order.total)}\n${order.shop.storeName} · ${order.shop.mobile}`
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, '_blank', 'noopener')
  }

  async function refreshCatalogue() {
    try {
      const response = await fetch(`${apiURL}/api/catalogue`)
      if (!response.ok) throw new Error()
      const payload = await response.json() as { products: Product[]; deals?: Deal[]; bundles?: ProductBundle[]; shopTypes?: ShopType[] }
      // Replace the offline copy in full: a product removed or deactivated in
      // the console must not reappear the next time the app starts offline.
      const current = new Set(payload.products.map(product => product.id))
      await db.transaction('rw', db.products, db.likes, db.metadata, async () => {
        await db.products.bulkPut(payload.products)
        await db.metadata.put({ id: 'current', bundles: payload.bundles ?? [], shopTypes: payload.shopTypes ?? [] })
        const stale = await db.products.filter(product => !current.has(product.id)).primaryKeys()
        await db.products.bulkDelete(stale)
        // A liked product that left the catalogue should not linger in the shortlist.
        const staleLikes = await db.likes.filter(like => !current.has(like.id)).primaryKeys()
        await db.likes.bulkDelete(staleLikes)
      })
      setProducts(payload.products)
      setBundles(payload.bundles ?? [])
      setShopTypes(payload.shopTypes ?? [])
      setDeals(payload.deals ?? [])
      setLikes(likes => likes.filter(id => current.has(id)))
      // The server rejects a whole order if one line is no longer sold, so
      // drop those lines now rather than at checkout, and reprice the rest so
      // the tentative total follows today's rates and schemes.
      const latest = new Map(payload.products.map(product => [product.id, product]))
      const kept = cartRef.current.flatMap(item => {
        const product = latest.get(item.id)
        return product ? [{ ...item, rate: inclusiveRate(product), scheme: schemeOf(product) }] : []
      })
      const dropped = cartRef.current.length - kept.length
      if (kept.some((item, index) => item.rate !== cartRef.current[index]?.rate || item.scheme !== cartRef.current[index]?.scheme) || dropped) await saveCart(kept)
      setMessage(message => dropped
        ? `${dropped} item${dropped === 1 ? ' is' : 's are'} no longer available and ${dropped === 1 ? 'was' : 'were'} removed from your cart.`
        : message.startsWith('Showing saved catalogue') ? '' : message)
    } catch { setMessage('Showing saved catalogue. Updates will sync when you are online.') }
    finally { setCatalogueLoading(false) }
  }

  async function completeSetup(saved: Shop, selectedIds: string[]) {
    const availableIds = resolveBundles(bundles, products, saved.shopType ?? '')
      .filter(bundle => selectedIds.includes(bundle.id)).map(bundle => bundle.id)
    if (availableIds.length) {
      setCatalogueView('recommended')
      setMessage('Your selected bundles are saved. Find their products in Recommended.')
    } else {
      setCatalogueView('all')
    }
    const profile = { ...saved, bundleIds: availableIds }
    if (salesman) { await chooseShop(profile); return }
    localStorage.setItem('asaan-shop', JSON.stringify(profile))
    setOwnShop(profile)
    setScreen('catalogue')
  }

  async function signIn() {
    setSalesGate('checking')
    try {
      const response = await fetch(`${apiURL}/api/sales/me`, { credentials: 'same-origin' })
      if (response.status === 403 || response.status === 401) { setSalesGate('signed-out'); return }
      if (!response.ok) throw new Error()
      const me = await response.json() as Salesman
      localStorage.setItem('asaan-salesman', JSON.stringify(me))
      setSalesman(me)
      setScreen('shops')
    } catch { setSalesGate('offline') }
  }

  async function signOut() {
    const pending = history.filter(order => order.status === 'pending').length
    const warning = pending
      ? `${pending} order${pending === 1 ? ' has' : 's have'} not been sent yet and will stay on this phone until someone signs in again. Sign out anyway?`
      : cartRef.current.length ? `Sign out? The cart for ${salesShop?.storeName ?? 'this shop'} will be cleared.` : 'Sign out of the salesman app on this phone?'
    if (!window.confirm(warning)) return
    await saveCart([])
    localStorage.removeItem('asaan-salesman')
    localStorage.removeItem('asaan-sales-shop')
    // End the staff session too, so the next person on this phone signs in as themselves.
    try { await fetch(`${apiURL}/admin/logout/`, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': csrfToken() } }) } catch { /* offline: the session ends on its own */ }
    setSalesman(null)
    setSalesShop(null)
    setShopHistory(null)
    setCatalogueView('all')
    setScreen('catalogue')
    setSalesGate('signed-out')
  }

  async function chooseShop(next: SalesShop) {
    if (salesShop && !sameShop(salesShop, next) && cartRef.current.length && !window.confirm(`Clear the cart for ${salesShop.storeName} and start an order for ${next.storeName}?`)) return
    if (!salesShop || !sameShop(salesShop, next)) await saveCart([])
    localStorage.setItem('asaan-sales-shop', JSON.stringify(next))
    setSalesShop(next)
    setCatalogueView('all')
    setScreen('catalogue')
  }

  // What the visited shop bought before, from any device it ordered on.
  useEffect(() => {
    setShopHistory(null)
    if (!salesman || !salesShop?.id) return
    let cancelled = false
    void fetch(`${apiURL}/api/sales/shops/${salesShop.id}/history`, { credentials: 'same-origin' })
      .then(response => response.ok ? response.json() as Promise<ShopHistory> : null)
      .then(payload => { if (!cancelled && payload) setShopHistory(payload) })
      .catch(() => { /* offline: the device's own orders still show */ })
    return () => { cancelled = true }
  }, [salesman, salesShop?.id, history.length])

  async function toggleLike(productId: string) {
    // The database is the source of truth so two quick taps cannot race.
    if (await db.likes.get(productId)) {
      await db.likes.delete(productId)
      setLikes(list => list.filter(id => id !== productId))
    } else {
      await db.likes.put({ id: productId })
      setLikes(list => list.includes(productId) ? list : [...list, productId])
    }
  }

  async function saveCart(next: CartItem[]) {
    cartRef.current = next
    setCart(next)
    await db.cart.put({ id: 'current', items: next })
  }

  function changeQuantity(target: QuantityTarget, delta: number) {
    const found = cart.find(item => item.id === target.id && item.unit === target.unit)
    setQuantity(target, (found?.quantity ?? 0) + delta)
  }

  // Two taps in the same tick would both read the same stale cart, so keep the
  // latest lines in a ref and write through it.
  function setQuantity(target: QuantityTarget, quantity: number) {
    quantity = Number.isFinite(quantity) ? Math.max(0, Math.floor(quantity)) : 0
    const current = cartRef.current
    const found = current.find(item => item.id === target.id && item.unit === target.unit)
    const next = quantity <= 0
      ? current.filter(item => !(item.id === target.id && item.unit === target.unit))
      : found
        ? current.map(item => item === found ? { ...item, quantity } : item)
        : [...current, { id: target.id, sku: target.sku, name: target.simpleName || target.name, unit: target.unit, rate: inclusiveRate(target), quantity, packing: target.packing, scheme: target.scheme ?? schemeOf(target) }]
    void saveCart(next)
  }

  async function retryPendingOrders() {
    const pending = await db.orders.where('status').equals('pending').toArray()
    for (const order of pending) await sendOrder(order, false)
  }

  async function sendOrder(order: LocalOrder, showResult = true) {
    try {
      const payload = { ...order, items: order.items.map(item => ({ productId: item.id, sku: item.sku, name: item.name, unit: item.unit, quantity: item.quantity, rate: item.rate })) }
      const response = order.takenBy
        ? await fetch(`${apiURL}/api/sales/orders`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() }, body: JSON.stringify(payload) })
        : await fetch(`${apiURL}/api/orders`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      // A salesman whose sign-in lapsed keeps the order and signs in again.
      if (order.takenBy && response.status === 403) {
        await db.orders.put({ ...order, status: 'pending', error: 'Sign in again to send this order.' })
        if (showResult) setMessage('Your staff sign-in has ended. The order is saved; sign in again from the menu to send it.')
        await refreshStatuses()
        return
      }
      if (!response.ok) {
        let detail = `Server rejected the order (${response.status}).`
        try {
          const body = await response.json() as { error?: string }
          if (body.error) detail = body.error
        } catch { /* keep the status-based message */ }
        if (response.status >= 400 && response.status < 500) {
          await db.orders.put({ ...order, status: 'failed', error: detail })
          if (showResult) setMessage(detail)
          return
        }
        throw new Error(detail)
      }
      const receipt = await response.json() as { orderNumber: string }
      const saved = { ...order, status: 'submitted' as const, orderNumber: receipt.orderNumber, error: undefined }
      await db.orders.put(saved)
      if (showResult) setMessage(`Order ${receipt.orderNumber} submitted successfully.`)
    } catch {
      await db.orders.put({ ...order, status: 'pending' })
      if (showResult) setMessage('Order saved on this device and will submit automatically when you are online.')
    }
    // The home shelves and the Orders screen read this list.
    await refreshStatuses()
  }

  async function placeOrder() {
    if (!hasShopDetails(shop) || cart.length === 0) return
    const order: LocalOrder = { clientOrderId: crypto.randomUUID(), shop, items: cart, notes: '', total, createdAt: new Date().toISOString(), status: 'pending', ...(salesman ? { takenBy: salesman.username } : {}) }
    await db.orders.put(order)
    await saveCart([])
    setScreen('orders')
    await sendOrder(order)
  }

  async function logOut() {
    const pending = await db.orders.where('status').equals('pending').count()
    const warning = pending
      ? `${pending} order${pending === 1 ? '' : 's'} on this device have not been submitted yet and will be deleted. Log out anyway?`
      : 'Log out and remove this shop and its saved data from this device?'
    if (!window.confirm(warning)) return
    localStorage.removeItem('asaan-shop')
    await Promise.all([db.products.clear(), db.cart.clear(), db.orders.clear(), db.metadata.clear()])
    window.location.reload()
  }

  async function repeatOrder(order: LocalOrder) {
    const productByID = new Map(products.map(product => [product.id, product]))
    const unavailable: string[] = []
    const next = order.items.flatMap(item => {
      const product = productByID.get(item.id)
      if (!product) { unavailable.push(item.name); return [] }
      return [{ id: product.id, sku: product.sku, name: product.simpleName || product.name, unit: product.unit, rate: inclusiveRate(product), quantity: item.quantity, packing: product.packing, scheme: schemeOf(product) }]
    })
    await saveCart(next)
    setScreen('catalogue')
    setMessage(unavailable.length ? `${unavailable.length} unavailable item${unavailable.length === 1 ? '' : 's'} was not added. Current prices have been applied.` : 'Previous items added with current prices.')
  }

  const companies = useMemo(() => [...new Set(products.map(p => p.company))].sort(), [products])
  const brands = useMemo(() => [...new Set(products.filter(p => !company || p.company === company).map(p => p.brand))].sort(), [products, company])
  const search = useMemo(() => {
    const index = new MiniSearch<Product>({ fields: ['name', 'simpleName', 'sku', 'company', 'brand', 'category', 'packing'], storeFields: ['id'] })
    index.addAll(products)
    return index
  }, [products])
  const browse = useMemo(() => {
    const productByID = new Map(products.map(product => [product.id, product]))
    const matches = query.trim() ? search.search(query, { prefix: true, fuzzy: 0.2, combineWith: 'AND' }).flatMap(result => {
      const product = productByID.get(String(result.id))
      return product ? [product] : []
    }) : products
    return matches.filter(product => (!company || product.company === company) && (!brand || product.brand === brand))
  }, [products, query, company, brand, search])
  // A random list for discovery. The seed only exists to re-run this memo.
  const discover = useMemo(() => {
    if (catalogueView !== 'discover' || browse.length === 0) return []
    const pool = [...browse]
    for (let i = pool.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1))
      const swap = pool[i]
      pool[i] = pool[j]
      pool[j] = swap
    }
    return pool.slice(0, 10)
  }, [browse, catalogueView, discoverSeed])
  const { total, savings } = cartTotals(cart)
  const marginTotal = useMemo(() => {
    const byId = new Map(products.map(product => [product.id, product]))
    return cart.reduce((sum, item) => {
      const product = byId.get(item.id)
      return product ? sum + Math.max(0, product.mrp * item.quantity - lineAmount(item)) : sum
    }, 0)
  }, [cart, products])
  const newProducts = useMemo(() => [...products].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt)).slice(0, 8), [products])
  const regularProducts = useMemo(() => products.filter(product => product.regular), [products])
  const recommended = useMemo(() => recommendedProducts(bundles, products, shop?.shopType ?? '', shop?.bundleIds ?? []), [bundles, products, shop?.shopType, shop?.bundleIds])
  const dealEntries = useMemo(() => {
    const byId = new Map(products.map(product => [product.id, product]))
    return deals
      .map(deal => ({ deal, product: byId.get(deal.productId) }))
      .filter((entry): entry is { deal: Deal; product: Product } => Boolean(entry.product))
      .sort((a, b) => a.deal.weekday - b.deal.weekday)
  }, [deals, products])
  const todayDeal = useMemo(() => {
    const weekday = (new Date().getDay() + 6) % 7
    return dealEntries.find(entry => entry.deal.weekday === weekday) ?? null
  }, [dealEntries])
  // A salesman's device holds orders for many shops; only this shop's count.
  const shopOrders = useMemo(() => shop ? history.filter(order => !salesman || sameShop(order.shop, shop)) : history, [history, shop, salesman])
  // The server knows orders the shop placed itself, so prefer its last order when it is newer.
  const lastOrder = useMemo<LocalOrder | null>(() => {
    const local = shopOrders[0] ?? null
    const remote = shopHistory?.lastOrder
    if (!salesman || !shop || !remote || (local && Date.parse(local.createdAt) >= Date.parse(remote.createdAt))) return local
    const byId = new Map(products.map(product => [product.id, product]))
    const items = remote.items.flatMap(item => {
      const product = byId.get(item.productId)
      return product && product.unit === item.unit ? [{ id: product.id, sku: product.sku, name: displayName(product), unit: product.unit, rate: inclusiveRate(product), quantity: item.quantity, packing: product.packing, scheme: schemeOf(product) }] : []
    })
    return items.length ? { clientOrderId: remote.orderNumber, orderNumber: remote.orderNumber, shop, items, notes: '', total: cartTotals(items).total, createdAt: remote.createdAt, status: 'submitted' } : local
  }, [shopOrders, shopHistory, salesman, shop, products])
  // What this shop actually buys, ranked from its own order history.
  const usual = useMemo(() => {
    const byId = new Map(products.map(product => [product.id, product]))
    if (salesman && shopHistory?.usual.length) return shopHistory.usual.flatMap(id => byId.get(id) ?? [])
    const bought = new Map<string, number>()
    for (const order of shopOrders) {
      for (const item of order.items) bought.set(item.id, (bought.get(item.id) ?? 0) + item.quantity)
    }
    return [...bought.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([id]) => byId.get(id))
      .filter((product): product is Product => Boolean(product))
      .slice(0, 8)
  }, [shopOrders, shopHistory, salesman, products])

  if (SALES_APP && !salesman) return <SalesSignIn gate={salesGate} onRetry={() => void signIn()} />
  if (salesman && screen !== 'setup' && (screen === 'shops' || !hasShopDetails(shop))) return <ShopPicker salesman={salesman} current={salesShop} message={message} onDismiss={() => setMessage('')} onPick={next => void chooseShop(next)} onNew={() => { setSalesShop(null); setScreen('setup') }} onBack={hasShopDetails(salesShop) ? () => setScreen('catalogue') : undefined} onSignOut={() => void signOut()} />
  if (!hasShopDetails(shop) || screen === 'setup') return <Registration initial={shop} salesman={Boolean(salesman)} products={products} bundles={bundles} shopTypes={shopTypes} loading={catalogueLoading} onSave={completeSetup} onCancel={salesman ? () => setScreen('shops') : hasShopDetails(shop) ? () => setScreen('catalogue') : undefined} />
  return <main className={screen === 'catalogue' ? 'catalogue' : undefined}>
    <header><div className="header-brand"><span className="logo" aria-hidden="true">A</span><div><strong>Asaan</strong><span>{salesman ? `Salesman · ${salesman.name}` : shop.storeName}</span></div></div><div className="header-actions">{supportPhone && <a className="quiet" href={`https://wa.me/${supportPhone.replace(/\D/g, '')}`} target="_blank" rel="noreferrer">Help</a>}<button className="quiet" onClick={() => setScreen('orders')}>Orders</button><Menu salesman={Boolean(salesman)} onLogout={() => void (salesman ? signOut() : logOut())} onSetup={() => setScreen('setup')} onSignIn={salesman ? () => { window.location.href = salesLoginURL() } : undefined} callHref={supportPhone ? `tel:${supportPhone}` : undefined} /></div></header>
    {salesman && <div className="sales-bar"><span>Order for <b>{shop.storeName}</b><small>{[shop.customerName, shop.mobile].filter(Boolean).join(' · ')}</small></span><button onClick={() => setScreen('shops')}>Change shop</button></div>}
    {message && <div className="notice">{message}<button onClick={() => setMessage('')}>×</button></div>}
    {screen === 'catalogue' && <Catalogue recommended={recommended} onSetup={() => setScreen('setup')} products={browse} newProducts={newProducts} regular={regularProducts} usual={usual} deals={dealEntries} todayDeal={todayDeal} lastOrder={lastOrder} onRepeat={order => void repeatOrder(order)} discover={discover} view={catalogueView} setView={setCatalogueView} cart={cart} likes={likes} shuffleDiscover={() => setDiscoverSeed(seed => seed + 1)} toggleLike={id => void toggleLike(id)} query={query} setQuery={setQuery} company={company} setCompany={setCompany} brand={brand} setBrand={setBrand} companies={companies} brands={brands} changeQuantity={changeQuantity} setQuantity={setQuantity} />}
    {screen === 'cart' && <Cart cart={cart} total={total} savings={savings} margin={marginTotal} onBack={() => setScreen('catalogue')} onSubmit={placeOrder} onClear={() => void saveCart([])} changeQuantity={changeQuantity} setQuantity={setQuantity} />}
    {screen === 'orders' && <Orders orders={shopOrders} supportPhone={supportPhone} pushAvailable={pushAvailable && !salesman} pushEnabled={pushEnabled} onEnablePush={() => void enableNotifications()} onShare={shareOrder} onBack={() => setScreen('catalogue')} onRepeat={repeatOrder} onChanged={loadHistory} />}
    {screen === 'catalogue' && <button className="cart-fab" onClick={() => setScreen('cart')}><span className="cart-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M3 4h2l2.2 10.2a2 2 0 0 0 2 1.6h7.9a2 2 0 0 0 1.9-1.4L20.5 8H6"/><circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/></svg></span><span className="cart-copy"><b>View cart</b><small>{cart.reduce((sum, item) => sum + item.quantity, 0)} {cart.reduce((sum, item) => sum + item.quantity, 0) === 1 ? 'item' : 'items'}</small></span><strong>{money(total)}</strong><span className="cart-arrow" aria-hidden="true">›</span></button>}
  </main>
}

function Registration({ initial, salesman = false, products, bundles, shopTypes, loading, onSave, onCancel }: {
  initial?: Shop | null; salesman?: boolean; products: Product[]; bundles: ProductBundle[]; shopTypes: ShopType[]; loading: boolean
  onSave: (shop: Shop, selectedIds: string[]) => Promise<void>
  onCancel?: () => void
}) {
  const [shop, setShop] = useState<Shop>(initial ?? { storeName: '', customerName: '', mobile: '', address: '' })
  const [tab, setTab] = useState<'details' | 'bundles'>('details')
  const [selectedIds, setSelectedIds] = useState<string[]>(initial?.bundleIds ?? [])
  const [saving, setSaving] = useState(false)
  const [locationState, setLocationState] = useState<'idle' | 'loading' | 'saved' | 'error'>('idle')
  const [error, setError] = useState('')
  const recommendations = useMemo(() => resolveBundles(bundles, products, shop.shopType ?? ''), [bundles, products, shop.shopType])
  const selected = recommendations.filter(bundle => selectedIds.includes(bundle.id))
  const shareLocation = () => {
    if (!navigator.geolocation) { setLocationState('error'); return }
    setLocationState('loading')
    navigator.geolocation.getCurrentPosition(position => {
      setShop(current => ({ ...current, latitude: position.coords.latitude, longitude: position.coords.longitude, locationAccuracy: Math.round(position.coords.accuracy) }))
      setLocationState('saved')
    }, () => setLocationState('error'), { enableHighAccuracy: true, timeout: 15_000, maximumAge: 60_000 })
  }
  const save = async (ids: string[]) => {
    if (saving) return
    const storeName = shop.storeName.trim()
    const mobile = shop.mobile.trim()
    if (!storeName || !mobile) {
      setTab('details')
      setError('Store name and mobile number are required.')
      return
    }
    setError('')
    setSaving(true)
    try {
      await onSave({ ...shop, storeName, mobile, customerName: shop.customerName?.trim(), address: shop.address?.trim() }, ids)
    } catch { setError('Could not save setup on this device. Please try again.') }
    finally { setSaving(false) }
  }
  const submit = (event: FormEvent) => { event.preventDefault(); void save(selected.map(bundle => bundle.id)) }
  const update = (changes: Partial<Shop>) => {
    setShop(current => ({ ...current, ...changes }))
    if ('shopType' in changes) setSelectedIds([])
    if (error) setError('')
  }
  return <main className="registration">
    <div className="brand"><span className="logo" aria-hidden="true">A</span>Asaan</div>
    <h1>{salesman ? (initial ? 'Shop details' : 'Add a shop') : 'Set up your shop'}</h1>
    <p>{salesman ? 'Enter the shop you are visiting. Its orders are recorded as taken by you.' : 'Save your details on this device to make future orders quick. They are included only when you submit an order.'}</p>
    <form onSubmit={submit} noValidate>
      <div className="setup-tabs" role="tablist" aria-label="Shop setup" onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        const next = event.key === 'Home' ? 'details' : event.key === 'End' ? 'bundles' : tab === 'details' ? 'bundles' : 'details'
        setTab(next)
        document.getElementById(`setup-${next}-tab`)?.focus()
      }}>
        <button type="button" id="setup-details-tab" role="tab" aria-selected={tab === 'details'} aria-controls="setup-details" tabIndex={tab === 'details' ? 0 : -1} onClick={() => setTab('details')}>Shop details</button>
        <button type="button" id="setup-bundles-tab" role="tab" aria-selected={tab === 'bundles'} aria-controls="setup-bundles" tabIndex={tab === 'bundles' ? 0 : -1} onClick={() => setTab('bundles')}>Recommended bundles</button>
      </div>
      <section id="setup-details" role="tabpanel" aria-labelledby="setup-details-tab" hidden={tab !== 'details'}>
        <div className="setup-grid">
          <Field label="Store name" value={shop.storeName} onChange={value => update({ storeName: value })} required />
          <label>Shop type <span className="setup-optional">Optional</span><select value={shop.shopType ?? ''} onChange={event => update({ shopType: event.target.value })}>
            <option value="">Choose your shop type</option>
            {shopTypes.map(type => <option key={type.id} value={type.id}>{type.name}</option>)}
          </select></label>
          <Field label="Contact name" value={shop.customerName ?? ''} onChange={value => update({ customerName: value })} />
          <Field label="Mobile number" type="tel" value={shop.mobile} onChange={value => update({ mobile: value })} required />
          <Field label="GSTIN (optional)" value={shop.gstin ?? ''} onChange={value => update({ gstin: value.toUpperCase().replace(/[^0-9A-Z]/g, '') })} maxLength={15} />
          <Field label="Address" value={shop.address ?? ''} onChange={value => update({ address: value })} />
        </div>
        <section className="location-card"><div><b>Shop location <small>Optional</small></b><p>{locationState === 'saved' ? `Location saved (accurate to about ${shop.locationAccuracy} m)` : locationState === 'error' ? 'Location could not be shared. You can continue without it.' : 'Share your current location to help with delivery.'}</p></div><button type="button" className="location-button" onClick={shareLocation} disabled={locationState === 'loading'}>{locationState === 'loading' ? 'Finding…' : locationState === 'saved' ? 'Update' : 'Share location'}</button></section>
        <button type="button" className="setup-next" onClick={() => setTab('bundles')}>Browse recommended bundles →</button>
      </section>
      <section id="setup-bundles" role="tabpanel" aria-labelledby="setup-bundles-tab" hidden={tab !== 'bundles'}>
        <h2>A starting point for your shop</h2>
        <p>Select any bundles you like. Their products appear under the Recommended pill in your catalogue. Add what you need as you browse.</p>
        <label>Shop type<select value={shop.shopType ?? ''} onChange={event => update({ shopType: event.target.value })}>
          <option value="">Choose your shop type</option>
          {shopTypes.map(type => <option key={type.id} value={type.id}>{type.name}</option>)}
        </select></label>
        {loading && <p className="setup-empty" role="status">Loading recommendations…</p>}
        {!loading && !shop.shopType && <p className="setup-empty">Choose a shop type to see its recommended bundles. You can also continue without a bundle.</p>}
        {!loading && shop.shopType && !recommendations.length && <p className="setup-empty">No recommended bundles for this shop type yet. Continue to browse the full catalogue.</p>}
        <div className="setup-grid bundle-grid">
          {recommendations.map(bundle => <article key={bundle.id} className={`bundle-card${selectedIds.includes(bundle.id) ? ' selected' : ''}`}>
            <label className="bundle-choice"><input type="checkbox" checked={selectedIds.includes(bundle.id)} onChange={event => setSelectedIds(ids => event.target.checked ? [...ids, bundle.id] : ids.filter(id => id !== bundle.id))} /><span><b>{bundle.name}</b><small>{bundle.items.length} {bundle.items.length === 1 ? 'product' : 'products'} · suggested total {money(bundle.total)} incl. GST</small></span></label>
            {bundle.description && <p>{bundle.description}</p>}
            <details><summary>View products & quantities</summary><ul>{bundle.items.map(({ product, quantity }) => <li key={product.id}><span>{product.simpleName || product.name}<small>{quantity} {product.unit}{product.packing ? ` · ${product.packing}` : ''}</small></span><b>{money(inclusiveRate(product) * quantity)}</b></li>)}</ul></details>
          </article>)}
        </div>
        {selected.length > 0 && <p className="bundle-selection" role="status">{selected.length} {selected.length === 1 ? 'bundle' : 'bundles'} selected. Their products will appear in Recommended.</p>}
      </section>
      <div className="setup-actions">
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary" disabled={saving || (loading && selectedIds.length > 0)}>{saving ? 'Saving…' : selected.length > 0 ? 'Save & view recommendations' : 'Open catalogue'}</button>
        {selected.length > 0 && <button type="button" className="setup-skip" disabled={saving} onClick={() => void save([])}>Continue without a bundle</button>}
        {onCancel && <button type="button" className="setup-skip" disabled={saving} onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  </main>
}

// The salesman app's front door: staff sign in with their console account.
function SalesSignIn({ gate, onRetry }: { gate: 'checking' | 'signed-out' | 'offline'; onRetry: () => void }) {
  return <main className="registration sales-sign-in">
    <div className="brand"><span className="logo" aria-hidden="true">A</span>Asaan Sales</div>
    <h1>Take orders for shops</h1>
    {gate === 'checking' && <p role="status">Checking your sign-in…</p>}
    {gate === 'signed-out' && <><p>Sign in with your staff account. Orders you take are recorded in your name.</p><a className="primary" href={salesLoginURL()}>Sign in</a></>}
    {gate === 'offline' && <><p>Could not reach Asaan. Check the connection and try again.</p><button className="primary" onClick={onRetry}>Try again</button></>}
  </main>
}

// Salesman mode: choose the shop being visited. Shops that ordered recently come first.
function ShopPicker({ salesman, current, message, onDismiss, onPick, onNew, onBack, onSignOut }: { salesman: Salesman; current: SalesShop | null; message: string; onDismiss: () => void; onPick: (shop: SalesShop) => void; onNew: () => void; onBack?: () => void; onSignOut: () => void }) {
  const [query, setQuery] = useState('')
  const [shops, setShops] = useState<SalesShop[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'offline' | 'signed-out'>('loading')
  useEffect(() => {
    let cancelled = false
    const timer = window.setTimeout(() => {
      setState(value => value === 'ready' ? value : 'loading')
      fetch(`${apiURL}/api/sales/shops?q=${encodeURIComponent(query.trim())}`, { credentials: 'same-origin' })
        .then(async response => {
          if (cancelled) return
          if (response.status === 403) { setState('signed-out'); return }
          if (!response.ok) throw new Error()
          setShops((await response.json() as { shops: SalesShop[] }).shops)
          setState('ready')
        })
        .catch(() => { if (!cancelled) setState('offline') })
    }, query ? 250 : 0)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [query])
  const visited = (shop: SalesShop) => shop.lastOrderAt ? `Last order ${new Date(shop.lastOrderAt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}` : 'No orders yet'
  return <main className="shop-picker">
    <header><div className="header-brand"><span className="logo" aria-hidden="true">A</span><div><strong>Choose a shop</strong><span>Salesman · {salesman.name}</span></div></div><div className="header-actions">{onBack && <button className="quiet" onClick={onBack}>Back</button>}<button className="quiet" onClick={onSignOut}>Sign out</button></div></header>
    {message && <div className="notice">{message}<button onClick={onDismiss}>×</button></div>}
    <div className="shop-picker-search">
      <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search shop, owner, mobile or area" enterKeyHint="search" aria-label="Search shops" />
      <button className="primary" onClick={onNew}>+ New shop</button>
    </div>
    {state === 'signed-out' && <p className="shop-picker-note">Your staff sign-in has ended. <a href={salesLoginURL()}>Sign in again</a>.</p>}
    {state === 'offline' && <p className="shop-picker-note">Could not load shops. Check the connection{current ? ', or carry on with ' + current.storeName : ''}.</p>}
    {state === 'loading' && !shops.length && <p className="shop-picker-note">Loading shops…</p>}
    {state === 'ready' && !shops.length && <p className="shop-picker-note">{query ? 'No shop matches. Add it as a new shop.' : 'No shops yet. Add the first one.'}</p>}
    <ul className="shop-list">
      {shops.map(shop => <li key={shop.id}><button className={current?.id === shop.id ? 'current' : undefined} onClick={() => onPick(shop)}>
        <span className="shop-avatar" aria-hidden="true">{brandInitials(shop.storeName)}</span>
        <span className="shop-copy"><b>{shop.storeName}</b><small>{[shop.customerName, shop.mobile].filter(Boolean).join(' · ')}</small>{shop.address && <small>{shop.address}</small>}</span>
        <span className="shop-meta">{visited(shop)}{current?.id === shop.id && <em>Current</em>}</span>
      </button></li>)}
    </ul>
  </main>
}

function Field({ label, value, onChange, required = false, maxLength, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; maxLength?: number; type?: string }) { return <label>{label}{required && <span className="required-mark"> *</span>}<input type={type} value={value} onChange={event => onChange(event.target.value)} required={required} maxLength={maxLength} /></label> }

function Menu({ salesman = false, onLogout, onSetup, onSignIn, callHref }: { salesman?: boolean; onLogout: () => void; onSetup: () => void; onSignIn?: () => void; callHref?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => { if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', escape) }
  }, [open])
  return <div className="menu" ref={ref}>
    <button className="quiet menu-button" aria-label="More options" aria-expanded={open} onClick={() => setOpen(value => !value)}>⋮</button>
    {open && <div className="menu-list" role="menu">
      <button role="menuitem" onClick={() => { setOpen(false); onSetup() }}>{salesman ? 'Edit this shop' : <>Shop details &amp; bundles</>}</button>
      {onSignIn && <button role="menuitem" onClick={() => { setOpen(false); onSignIn() }}>Staff sign in again</button>}
      <button role="menuitem" onClick={() => window.location.reload()}>Refresh</button>
      <button role="menuitem" onClick={() => void clearCacheAndReload()}>Clear cache &amp; reload</button>
      {callHref && <a role="menuitem" href={callHref}>Call support</a>}
      <button role="menuitem" className="danger" onClick={onLogout}>{salesman ? 'Sign out' : 'Log out'}</button>
    </div>}
  </div>
}

function Catalogue(props: {
  products: Product[]
  newProducts: Product[]
  regular: Product[]
  recommended: Product[]
  onSetup: () => void
  usual: Product[]
  deals: { deal: Deal; product: Product }[]
  todayDeal: { deal: Deal; product: Product } | null
  lastOrder: LocalOrder | null
  onRepeat: (order: LocalOrder) => void
  discover: Product[]
  view: CatalogueView
  setView: (v: CatalogueView) => void
  cart: CartItem[]
  likes: string[]
  shuffleDiscover: () => void
  toggleLike: (id: string) => void
  query: string
  setQuery: (v: string) => void
  company: string
  setCompany: (v: string) => void
  brand: string
  setBrand: (v: string) => void
  companies: string[]
  brands: string[]
  changeQuantity: (p: Product, d: number) => void
  setQuantity: (p: Product, q: number) => void
}) {
  const [keypadProduct, setKeypadProduct] = useState<Product | null>(null)
  const [keypadValue, setKeypadValue] = useState('')
  const cartQuantities = useMemo(
    () => new Map(props.cart.filter((item) => item.quantity > 0).map((item) => [`${item.id}:${item.unit}`, item.quantity])),
    [props.cart]
  )
  const visibleProducts = useMemo(() => {
    if (props.view === 'all') return props.products
    if (props.view === 'in-cart') return props.products.filter((product) => cartQuantities.has(`${product.id}:${product.unit}`))
    if (props.view === 'liked') {
      const liked = new Set(props.likes)
      return props.products.filter((product) => liked.has(product.id))
    }
    if (props.view === 'recommended') {
      const ids = new Set(props.recommended.map(product => product.id))
      return props.products.filter(product => ids.has(product.id))
    }
    const picks =
      props.view === 'new'
        ? props.newProducts
        : props.view === 'regular'
          ? props.regular
          : props.view === 'usual'
            ? props.usual
            : props.view === 'discover'
              ? props.discover
              : props.deals.map((entry) => entry.product)
    const matching = new Set(props.products.map((product) => product.id))
    // Preserve each view's ranking and apply search/company/brand filters.
    return [...new Map(picks.filter((product) => matching.has(product.id)).map((product) => [product.id, product])).values()]
  }, [props.view, props.products, props.likes, props.newProducts, props.regular, props.recommended, props.usual, props.discover, props.deals, cartQuantities])
  const selectView = (view: CatalogueView) => props.setView(props.view === view ? 'all' : view)
  const viewLabels: Record<CatalogueView, string> = {
    all: 'All products',
    'in-cart': 'In cart',
    liked: 'Liked',
    new: 'New products',
    regular: 'Regular',
    usual: 'Your usual',
    deals: 'Deals this week',
    discover: 'Discover',
    recommended: 'Recommended'
  }
  const emptyMessage =
    props.view === 'in-cart' && cartQuantities.size === 0
      ? 'Your cart is empty. Tap + on a product or enter a quantity to add it.'
      : props.query.trim() || props.company || props.brand
        ? 'No products match these filters.'
        : props.view === 'recommended'
          ? 'No recommended products yet. Choose bundles in Shop details & bundles from the menu.'
        : props.view === 'liked'
          ? 'No liked items yet. Tap the heart on a product to save it here.'
          : `No ${viewLabels[props.view].toLowerCase()} available yet.`
  const openKeypad = (product: Product) => {
    const quantity = cartQuantities.get(`${product.id}:${product.unit}`) ?? 0
    setKeypadProduct(product)
    setKeypadValue(quantity ? String(quantity) : '')
  }
  const pressKey = (key: string) =>
    setKeypadValue((value) => {
      if (key === 'backspace') return value.slice(0, -1)
      if (key === 'clear') return ''
      return value.length < 5 ? `${value}${key}` : value
    })
  const [filtersOpen, setFiltersOpen] = useState(false)
  const likedSet = useMemo(() => new Set(props.likes), [props.likes])
  // Browsing everything starts from categories; searching, filtering or any
  // other view goes straight to a product list.
  const showCategories = props.view === 'all' && !props.query.trim() && !props.company && !props.brand
  const categories = useMemo(() => {
    const groups = new Map<string, Product[]>()
    for (const product of props.products) {
      const name = product.category || 'Other'
      const group = groups.get(name)
      if (group) group.push(product)
      else groups.set(name, [product])
    }
    return [...groups].map(([name, products]): CategoryGroup => {
      products.sort((a, b) => naturalOrder.compare(displayName(a), displayName(b)))
      // Photos first, then one brand tile per brand, so the row hints at what is inside.
      const brands = new Set<string>()
      const tiles = products.filter((product) => !imageSource(product) && !brands.has(product.brand) && Boolean(brands.add(product.brand)))
      let inCart = 0
      let cartAmount = 0
      for (const product of products) {
        const quantity = cartQuantities.get(`${product.id}:${product.unit}`)
        if (!quantity) continue
        inCart += 1
        cartAmount += lineAmount({ quantity, rate: inclusiveRate(product), scheme: schemeOf(product) })
      }
      return { name, products, thumbs: [...products.filter((product) => imageSource(product)), ...tiles].slice(0, 3), inCart, cartAmount }
    }).sort((a, b) => naturalOrder.compare(a.name, b.name))
  }, [props.products, cartQuantities])
  const [openCategory, setOpenCategory] = useState<string | null>(null)
  const sheetCategory = openCategory ? categories.find((category) => category.name === openCategory) : undefined
  // The sheet takes a history entry so the phone's Back button closes it
  // instead of leaving the app.
  const openSheet = (name: string) => {
    window.history.pushState({ asaanSheet: true }, '')
    setOpenCategory(name)
  }
  const closeSheet = () => {
    if (window.history.state?.asaanSheet) window.history.back()
    else setOpenCategory(null)
  }
  useEffect(() => {
    const onBack = () => {
      setOpenCategory(null)
      setKeypadProduct(null)
    }
    window.addEventListener('popstate', onBack)
    return () => {
      window.removeEventListener('popstate', onBack)
      // Leaving the catalogue (e.g. for the cart) with the sheet open.
      if (window.history.state?.asaanSheet) window.history.back()
    }
  }, [])
  useEffect(() => {
    if (!openCategory) return
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !keypadProduct) closeSheet() }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [openCategory, keypadProduct])
  const row: RowContext = {
    view: props.view, cartQuantities, likedSet, deals: props.deals, todayDeal: props.todayDeal,
    toggleLike: props.toggleLike, changeQuantity: props.changeQuantity, setQuantity: props.setQuantity, openKeypad
  }
  const filterCount = (props.company ? 1 : 0) + (props.brand ? 1 : 0)
  return (
    <>
      <section className="controls">
        <div className="search-row">
          <input
            className="search"
            aria-label="Search products"
            placeholder="Search product, brand, SKU…"
            value={props.query}
            onChange={(e) => props.setQuery(e.target.value)}
          />
          <button
            type="button"
            className={`filter-toggle ${filterCount ? 'active' : ''} ${filtersOpen ? 'open' : ''}`}
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            aria-controls="catalogue-filters">
            <svg
              className="filter-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true">
              <path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" />
            </svg>
            <span className="filter-label">Filters</span>
            {filterCount > 0 && <span className="filter-count">{filterCount}</span>}
            <svg
              className="filter-chevron"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true">
              <path d="m6 9 6 6 6-6" />
            </svg>
          </button>
        </div>
        <div className="quick-row" role="group" aria-label="Product views">
          <button
            type="button"
            className={`quick-toggle ${props.view === 'all' ? 'active' : ''}`}
            aria-pressed={props.view === 'all'}
            onClick={() => props.setView('all')}>
            All
          </button>
          <button type="button" className={`quick-toggle ${props.view === 'recommended' ? 'active' : ''}`} aria-pressed={props.view === 'recommended'} onClick={() => selectView('recommended')}>
            Recommended
          </button>
          <button
            type="button"
            className={`quick-toggle ${props.view === 'in-cart' ? 'active' : ''}`}
            aria-pressed={props.view === 'in-cart'}
            onClick={() => selectView('in-cart')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 3h2l2.2 11a2 2 0 0 0 2 1.6h7.9a2 2 0 0 0 1.9-1.4L21 7H6" />
              <circle cx="9" cy="20" r="1" />
              <circle cx="18" cy="20" r="1" />
            </svg>
            <span>In cart</span>
            <span className="quick-count">{cartQuantities.size}</span>
          </button>
          <button
            type="button"
            className={`quick-toggle ${props.view === 'liked' ? 'active' : ''}`}
            aria-pressed={props.view === 'liked'}
            onClick={() => selectView('liked')}>
            <svg
              viewBox="0 0 24 24"
              fill={props.view === 'liked' ? 'currentColor' : 'none'}
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true">
              <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21.2l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z" />
            </svg>
            <span>Liked</span>
            {props.likes.length > 0 && <span className="quick-count">{props.likes.length}</span>}
          </button>
          <button
            type="button"
            className={`quick-toggle ${props.view === 'new' ? 'active' : ''}`}
            aria-pressed={props.view === 'new'}
            onClick={() => selectView('new')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
              <path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z" />
            </svg>
            <span>New</span>
          </button>
          {props.regular.length > 0 && (
            <button
              type="button"
              className={`quick-toggle ${props.view === 'regular' ? 'active' : ''}`}
              aria-pressed={props.view === 'regular'}
              onClick={() => selectView('regular')}>
              <svg
                viewBox="0 0 24 24"
                fill={props.view === 'regular' ? 'currentColor' : 'none'}
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true">
                <path d="M12 3l2.7 5.6 6.1.8-4.5 4.2 1.1 6-5.4-3-5.4 3 1.1-6L3.2 9.4l6.1-.8z" />
              </svg>
              <span>Regular</span>
            </button>
          )}
          {props.usual.length > 0 && (
            <button
              type="button"
              className={`quick-toggle ${props.view === 'usual' ? 'active' : ''}`}
              aria-pressed={props.view === 'usual'}
              onClick={() => selectView('usual')}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M3 12a9 9 0 1 0 2.9-6.6" />
                <path d="M3 4v5h5" />
              </svg>
              <span>Usual</span>
            </button>
          )}
          {props.deals.length > 0 && (
            <button
              type="button"
              className={`quick-toggle ${props.view === 'deals' ? 'active' : ''}`}
              aria-pressed={props.view === 'deals'}
              onClick={() => selectView('deals')}>
              Deals
            </button>
          )}
          <button
            type="button"
            className={`quick-toggle ${props.view === 'discover' ? 'active' : ''}`}
            aria-pressed={props.view === 'discover'}
            onClick={() => selectView('discover')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M16 3h5v5" />
              <path d="M4 20 21 3" />
              <path d="M21 16v5h-5" />
              <path d="m15 15 6 6" />
              <path d="m4 4 5 5" />
            </svg>
            <span>Discover</span>
          </button>
        </div>
        {filtersOpen && (
          <div className="filters-panel" id="catalogue-filters">
            <div className="filter-group">
              <span>Company</span>
              <div className="filter-row">
                <button
                  className={`filter-pill ${!props.company ? 'selected' : ''}`}
                  onClick={() => {
                    props.setCompany('')
                    props.setBrand('')
                  }}>
                  All companies
                </button>
                {props.companies.map((value) => (
                  <button
                    key={value}
                    className={`filter-pill ${props.company === value ? 'selected' : ''}`}
                    onClick={() => {
                      props.setCompany(value)
                      props.setBrand('')
                    }}>
                    {value}
                  </button>
                ))}
              </div>
            </div>
            <div className="filter-group brands">
              <span>{props.company ? `${props.company} brands` : 'Brand'}</span>
              <div className="filter-row">
                <button className={`filter-pill ${!props.brand ? 'selected' : ''}`} onClick={() => props.setBrand('')}>
                  All brands
                </button>
                {props.brands.map((value) => (
                  <button key={value} className={`filter-pill ${props.brand === value ? 'selected' : ''}`} onClick={() => props.setBrand(value)}>
                    {value}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>
      <div className="catalogue-meta">
        <div className="count" aria-live="polite">
          {showCategories
            ? `${categories.length} ${categories.length === 1 ? 'category' : 'categories'} · ${props.products.length} products · GST included`
            : `${viewLabels[props.view]} · ${visibleProducts.length} · GST included`}
        </div>
        {props.view === 'discover' && (
          <button type="button" className="catalogue-action" onClick={props.shuffleDiscover}>
            Shuffle
          </button>
        )}
        {props.view === 'recommended' && <button type="button" className="catalogue-action" onClick={props.onSetup}>Choose bundles</button>}
        {props.lastOrder && props.view !== 'discover' && props.view !== 'recommended' && (
          <button
            type="button"
            className="catalogue-action"
            title={`${props.lastOrder.items.length} items · ${money(props.lastOrder.total)} · ${new Date(props.lastOrder.createdAt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`}
            onClick={() => props.lastOrder && props.onRepeat(props.lastOrder)}>
            Order again ›
          </button>
        )}
      </div>
      {showCategories ? (
        <CategoryList categories={categories} onOpen={openSheet} />
      ) : (
        <ProductList products={visibleProducts} row={row} empty={emptyMessage} resetKey={`${props.view}|${props.query}|${props.company}|${props.brand}`} />
      )}
      {showCategories && sheetCategory && <CategorySheet key={sheetCategory.name} category={sheetCategory} row={row} onClose={closeSheet} />}
      {keypadProduct && (
        <Keypad
          product={keypadProduct}
          value={keypadValue}
          liked={likedSet.has(keypadProduct.id)}
          onToggleLike={() => props.toggleLike(keypadProduct.id)}
          pressKey={pressKey}
          onAddCase={() => setKeypadValue((value) => String(Math.min(99999, (Number(value) || 0) + caseSize(keypadProduct.packing, keypadProduct.unit))))}
          onClose={() => setKeypadProduct(null)}
          onSave={() => {
            props.setQuantity(keypadProduct, Number(keypadValue))
            setKeypadProduct(null)
          }}
        />
      )}
    </>
  )
}

// Everything a product row needs from the catalogue, shared by the main list
// and the category sheet.
type RowContext = {
  view: CatalogueView
  cartQuantities: Map<string, number>
  likedSet: Set<string>
  deals: { deal: Deal; product: Product }[]
  todayDeal: { deal: Deal; product: Product } | null
  toggleLike: (id: string) => void
  changeQuantity: (p: Product, d: number) => void
  setQuantity: (p: Product, q: number) => void
  openKeypad: (product: Product) => void
}

function ProductRow({ product, index, start, rowRef, view, cartQuantities, likedSet, deals, todayDeal, toggleLike, changeQuantity, setQuantity, openKeypad }: RowContext & { product: Product; index: number; start: number; rowRef: (element: HTMLElement | null) => void }) {
  const quantity = cartQuantities.get(`${product.id}:${product.unit}`) ?? 0
  return (
    <article
      ref={rowRef}
      data-index={index}
      className={`product ${quantity > 0 ? 'in-cart' : ''}`}
      onClick={() => openKeypad(product)}
      style={{ transform: `translateY(${start}px)` }}>
      <div className="product-main">
        <span className="product-photo">
          <ProductThumb product={product} className="product-image" />
          <button
            type="button"
            className={`like-button ${likedSet.has(product.id) ? 'on' : ''}`}
            aria-label={likedSet.has(product.id) ? 'Remove from liked' : 'Add to liked'}
            aria-pressed={likedSet.has(product.id)}
            onClick={(event) => {
              event.stopPropagation()
              toggleLike(product.id)
            }}>
            <svg
              viewBox="0 0 24 24"
              fill={likedSet.has(product.id) ? 'currentColor' : 'none'}
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true">
              <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21.2l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z" />
            </svg>
          </button>
        </span>
        <div className="product-info">
          <b>{product.simpleName || product.name}</b>
          <small>
            {view === 'deals'
              ? deals
                  .filter((entry) => entry.product.id === product.id)
                  .map((entry) => (
                    <span key={entry.deal.weekday} className="deal-chip">
                      {WEEKDAY_NAMES[entry.deal.weekday]} · {Number(entry.deal.percent)}%
                    </span>
                  ))
              : todayDeal?.product.id === product.id && <span className="deal-chip">Today · {Number(todayDeal.deal.percent)}%</span>}
            {schemeOf(product) > 0 && <span className="scheme-chip">{schemeOf(product)}% {product.schemeName || 'scheme'}</span>}
            {product.packing} · {product.company}
          </small>
          <strong>
            <span className="rate">
              <span className="amount">{money(inclusiveRate(product))}</span> <em className="unit">/{product.unit}</em>
            </span>
            <span className="mrp">MRP {money(product.mrp)}</span>
          </strong>
        </div>
      </div>
      <Quantity
        value={quantity}
        decrement={() => changeQuantity(product, -caseSize(product.packing, product.unit))}
        increment={() => changeQuantity(product, caseSize(product.packing, product.unit))}
        onInput={(value) => setQuantity(product, value)}
        onOpenKeypad={() => openKeypad(product)}
      />
    </article>
  )
}

function ProductList({ products, row, empty, resetKey, className = '' }: { products: Product[]; row: RowContext; empty: string; resetKey: string; className?: string }) {
  const parentRef = useRef<HTMLDivElement>(null)
  const virtual = useVirtualizer({
    count: products.length,
    getScrollElement: () => parentRef.current,
    // Rows grow to fit long names, so each one is measured once rendered.
    estimateSize: () => PRODUCT_ROW_HEIGHT,
    getItemKey: (index) => products[index].id,
    overscan: 8
  })
  useEffect(() => {
    parentRef.current?.scrollTo({ top: 0 })
  }, [resetKey])
  return (
    <div ref={parentRef} className={`product-list ${className}`}>
      {products.length === 0 && <p className="empty">{empty}</p>}
      <div style={{ height: virtual.getTotalSize(), position: 'relative' }}>
        {virtual.getVirtualItems().map((item) => (
          <ProductRow key={item.key} product={products[item.index]} index={item.index} start={item.start} rowRef={virtual.measureElement} {...row} />
        ))}
      </div>
    </div>
  )
}

type CategoryGroup = { name: string; products: Product[]; thumbs: Product[]; inCart: number; cartAmount: number }

// The product photo, or a brand-coloured tile with the brand's initials.
function ProductThumb({ product, className }: { product: Product; className: string }) {
  const [failed, setFailed] = useState(false)
  const source = imageSource(product)
  if (source && !failed) return <img className={className} src={source} alt="" loading="lazy" onError={() => setFailed(true)} />
  const brand = product.brand || product.company || displayName(product)
  return (
    <span className={`${className} brand-tile`} style={{ '--tile-hue': brandHue(brand) } as CSSProperties} aria-hidden="true">
      {brandInitials(brand)}
    </span>
  )
}

function CategoryList({ categories, onOpen }: { categories: CategoryGroup[]; onOpen: (name: string) => void }) {
  return (
    <div className="product-list category-scroll">
      {categories.length === 0 && <p className="empty">No products available yet.</p>}
      <ul className="category-list">
        {categories.map((category) => (
          <li key={category.name}>
            <button type="button" className={`category-row ${category.inCart ? 'has-cart' : ''}`} onClick={() => onOpen(category.name)}>
              <span className="category-copy">
                <b>{category.name}</b>
                <small>{category.products.length} {category.products.length === 1 ? 'product' : 'products'}</small>
                {category.inCart > 0 && <small className="category-cart">{category.inCart} in cart · {money(category.cartAmount)}</small>}
              </span>
              <span className="category-thumbs" aria-hidden="true">
                {category.thumbs.map((product) => <ProductThumb key={product.id} product={product} className="category-thumb" />)}
              </span>
              <span className="category-arrow" aria-hidden="true">›</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

const SHEET_CLOSE_DRAG = 110

function CategorySheet({ category, row, onClose }: { category: CategoryGroup; row: RowContext; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [brand, setBrand] = useState('')
  const [drag, setDrag] = useState(0)
  const dragStart = useRef<number | null>(null)
  const brands = useMemo(() => [...new Set(category.products.map((product) => product.brand).filter(Boolean))].sort(naturalOrder.compare), [category.products])
  const products = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean)
    return category.products.filter((product) => {
      if (brand && product.brand !== brand) return false
      const text = `${displayName(product)} ${product.name} ${product.brand} ${product.packing} ${product.sku}`.toLowerCase()
      return words.every((word) => text.includes(word))
    })
  }, [category.products, brand, query])
  const filtered = products.length !== category.products.length
  // Drag the handle or title down to close; the product list keeps its own scrolling.
  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('button, input')) return
    dragStart.current = event.clientY
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragStart.current !== null) setDrag(Math.max(0, event.clientY - dragStart.current))
  }
  const endDrag = () => {
    if (dragStart.current === null) return
    dragStart.current = null
    if (drag > SHEET_CLOSE_DRAG) onClose()
    else setDrag(0)
  }
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <section
        className={`category-sheet ${drag ? 'dragging' : ''}`}
        style={drag ? { transform: `translateY(${drag}px)` } : undefined}
        role="dialog"
        aria-modal="true"
        aria-labelledby="category-sheet-title"
        onClick={(event) => event.stopPropagation()}>
        <div className="sheet-grab" onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}>
          <span className="sheet-handle" aria-hidden="true" />
          <div className="sheet-head">
            <div>
              <b id="category-sheet-title">{category.name}</b>
              <small>
                {filtered ? `${products.length} of ${category.products.length}` : category.products.length} {category.products.length === 1 ? 'product' : 'products'} · GST included
                {category.inCart > 0 && <span className="category-cart"> · {category.inCart} in cart · {money(category.cartAmount)}</span>}
              </small>
            </div>
            <button type="button" className="keypad-close" aria-label="Close" onClick={onClose}>×</button>
          </div>
        </div>
        {(category.products.length > 6 || brands.length > 1) && (
          <div className="sheet-tools">
            {category.products.length > 6 && (
              <input
                className="search sheet-search"
                type="search"
                aria-label={`Search ${category.name}`}
                placeholder={`Search in ${category.name}…`}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            )}
            {brands.length > 1 && (
              <div className="sheet-brands" role="group" aria-label="Brands">
                <button type="button" className={`filter-pill ${!brand ? 'selected' : ''}`} aria-pressed={!brand} onClick={() => setBrand('')}>All brands</button>
                {brands.map((value) => (
                  <button key={value} type="button" className={`filter-pill ${brand === value ? 'selected' : ''}`} aria-pressed={brand === value} onClick={() => setBrand(brand === value ? '' : value)}>
                    {value}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <ProductList products={products} row={row} empty="No products match. Try another brand or word." resetKey={`${category.name}|${brand}|${query}`} className="sheet-list" />
      </section>
    </div>
  )
}

function Quantity({ value, decrement, increment, onInput, onOpenKeypad }: { value: number; decrement: () => void; increment: () => void; onInput: (value: number) => void; onOpenKeypad?: () => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const bump = (action: () => void) => { setDraft(null); action() }
  const commit = (raw: string) => {
    const parsed = Math.floor(Number(raw))
    if (Number.isFinite(parsed)) onInput(Math.max(0, parsed))
  }
  return <div className="quantity" onClick={event => event.stopPropagation()}>
    <button aria-label="Reduce quantity" onClick={() => bump(decrement)}>−</button>
    <input
      aria-label="Quantity"
      type="number"
      min="0"
      step="1"
      inputMode="numeric"
      readOnly={Boolean(onOpenKeypad)}
      value={onOpenKeypad ? (value || '') : (draft ?? (value || ''))}
      placeholder="0"
      onClick={() => onOpenKeypad?.()}
      onWheel={event => event.currentTarget.blur()}
      onChange={event => {
        if (onOpenKeypad) return
        const raw = event.target.value
        setDraft(raw)
        // Committing an empty or zero draft would delete the line while the
        // customer is still typing; those wait for blur below.
        if (raw === '' || Number(raw) === 0) return
        commit(raw)
      }}
      onBlur={() => {
        if (draft === null) return
        const raw = draft
        setDraft(null)
        // Clearing the field keeps the previous quantity; an explicit 0 removes.
        if (raw.trim() !== '') commit(raw)
      }}
    />
    <button aria-label="Increase quantity" onClick={() => bump(increment)}>+</button>
  </div>
}

function Keypad({ product, value, liked, onToggleLike, pressKey, onAddCase, onClose, onSave }: { product: Product; value: string; liked: boolean; onToggleLike: () => void; pressKey: (key: string) => void; onAddCase: () => void; onClose: () => void; onSave: () => void }) {
  const scheme = Number(product.schemePercent) || 0
  const gst = Number(product.gstRate) || 0
  const image = imageSource(product)
  const rate = inclusiveRate(product)
  const unitMargin = Math.max(0, product.mrp - rate)
  const marginPercent = product.mrp > 0 ? (unitMargin / product.mrp) * 100 : 0
  const quantity = Number(value) || 0
  const rows: { label: string; value: string; numeric?: boolean }[] = [
    { label: `Rate / ${product.unit} (incl. GST)`, value: money(rate), numeric: true },
    { label: 'MRP', value: product.mrp > 0 ? money(product.mrp) : '—', numeric: true },
    ...(unitMargin > 0 ? [{ label: 'Margin / unit', value: `${money(unitMargin)} · ${marginPercent.toFixed(1)}%`, numeric: true }] : []),
    ...(scheme > 0 ? [{ label: product.schemeName ? `Scheme · ${product.schemeName}` : 'Scheme', value: `${scheme}% off`, numeric: true }] : []),
    ...(gst > 0 ? [{ label: 'GST', value: `${gst}%`, numeric: true }] : []),
    { label: 'Brand', value: product.brand },
    { label: 'Category', value: product.category },
    { label: 'SKU', value: product.sku },
    { label: 'Unit', value: product.unit },
  ]
  return <div className="keypad-backdrop" onClick={onClose}>
    <section className="keypad" onClick={event => event.stopPropagation()}>
      <div className="keypad-title">
        <div className="keypad-product">
          <ProductThumb product={product} className="keypad-image" />
          <div className="keypad-heading">
            <b>{product.simpleName || product.name}</b>
            <small>{product.packing} · {product.company}</small>
          </div>
        </div>
        <div className="keypad-title-actions"><button type="button" className={`like-button ${liked ? 'on' : ''}`} aria-label={liked ? 'Remove from liked' : 'Add to liked'} aria-pressed={liked} onClick={onToggleLike}><svg viewBox="0 0 24 24" fill={liked ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21.2l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z" /></svg></button><button className="keypad-close" onClick={onClose} aria-label="Close keypad">×</button></div>
      </div>

      <div className="keypad-price">
        <strong>{money(rate)} <em>/{product.unit} incl. GST</em></strong>
        {product.mrp > rate && <s>{money(product.mrp)}</s>}
        {scheme > 0 && <span className="scheme-chip">{scheme}% scheme</span>}
      </div>

      <div className="keypad-display">{value || '0'}</div>

      {caseSize(product.packing, product.unit) > 1 && <div className="keypad-case"><span>1 case = {caseSize(product.packing, product.unit)} {product.unit}</span><button type="button" onClick={onAddCase}>+1 case</button></div>}

      {unitMargin > 0 && <div className="keypad-margin">
        <span>Retail margin<small>{marginPercent.toFixed(1)}% of MRP</small></span>
        <span className="keypad-margin-value">
          <strong>{money(quantity > 0 ? unitMargin * quantity : unitMargin)}</strong>
          <em>{quantity > 0 ? `on ${quantity} ${product.unit}` : 'per unit'}</em>
        </span>
      </div>}

      <div className="keypad-grid">{['1', '2', '3', '4', '5', '6', '7', '8', '9'].map(key => <button key={key} onClick={() => pressKey(key)}>{key}</button>)}<button className="keypad-clear" onClick={() => pressKey('clear')}>Clear</button><button onClick={() => pressKey('0')}>0</button><button aria-label="Backspace" onClick={() => pressKey('backspace')}>⌫</button></div>
      <button className="keypad-save" onClick={onSave}>{Number(value) > 0 ? `Update quantity · ${money(Number(value) * rate)}` : 'Remove from order'}</button>

      <p className="detail-heading">Product details</p>
      <table className="detail-table">
        <tbody>
          {rows.map(row => <tr key={row.label}><th scope="row">{row.label}</th><td className={row.numeric ? 'num' : ''}>{row.value}</td></tr>)}
        </tbody>
      </table>
    </section>
  </div>
}

function Cart({ cart, total, savings, margin, onBack, onSubmit, onClear, changeQuantity, setQuantity }: { cart: CartItem[]; total: number; savings: number; margin: number; onBack: () => void; onSubmit: () => void; onClear: () => void; changeQuantity: (target: QuantityTarget, d: number) => void; setQuantity: (target: QuantityTarget, q: number) => void }) {
  const clear = () => { if (window.confirm('Clear all items from this cart?')) onClear() }
  return <section className="page"><button className="back" onClick={onBack}>← Catalogue</button><div className="cart-heading"><h1>Your order</h1>{cart.length > 0 && <button onClick={clear}>Clear cart</button>}</div>{cart.length === 0 ? <p className="empty">Your cart is empty.</p> : <><table className="list-table"><thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Amount</th></tr></thead><tbody>{cart.map(item => <tr key={`${item.id}-${item.unit}`}><td className="item"><b>{item.name}</b><small>{money(item.rate)} / {item.unit} incl. GST{item.scheme ? <span className="scheme-chip">{item.scheme}% scheme</span> : null}</small><button className="remove-line" onClick={() => setQuantity(item, 0)}>Remove</button></td><td className="num"><Quantity value={item.quantity} decrement={() => changeQuantity(item, -caseSize(item.packing, item.unit))} increment={() => changeQuantity(item, caseSize(item.packing, item.unit))} onInput={value => setQuantity(item, value)} /></td><td className="num amount">{money(lineAmount(item))}</td></tr>)}</tbody></table><table className="totals-table"><tbody>{savings > 0 && <tr className="margin-row"><td>Scheme savings<small>Already taken off below</small></td><td>−{money(savings)}</td></tr>}<tr><td>Tentative total<small>Inclusive of GST</small></td><td>{money(total)}</td></tr>{margin > 0 && <tr className="margin-row"><td>Your retail margin<small>If sold at MRP</small></td><td>{money(margin)}</td></tr>}</tbody></table><p className="hint">Final rates, schemes, tax and availability are confirmed during billing.</p><button className="primary" onClick={() => void onSubmit()}>Submit order</button></>}</section>
}

function Orders({ orders, supportPhone, pushAvailable, pushEnabled, onEnablePush, onShare, onBack, onRepeat, onChanged }: { orders: LocalOrder[]; supportPhone: string; pushAvailable: boolean; pushEnabled: boolean; onEnablePush: () => void; onShare: (order: LocalOrder) => void; onBack: () => void; onRepeat: (order: LocalOrder) => Promise<void>; onChanged: () => Promise<void> }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = selectedId ? orders.find(order => order.clientOrderId === selectedId) ?? null : null
  if (selected) return <OrderSummary order={selected} supportPhone={supportPhone} onShare={onShare} onBack={() => setSelectedId(null)} onRepeat={onRepeat} onCancel={async () => { await db.orders.delete(selected.clientOrderId); await onChanged(); setSelectedId(null) }} />
  return <section className="page"><button className="back" onClick={onBack}>← Catalogue</button><div className="orders-heading"><h1>Previous orders</h1>{pushAvailable && !pushEnabled && <button type="button" className="enable-push" onClick={onEnablePush}>Get order updates</button>}</div>{pushAvailable && pushEnabled && <p className="orders-note">Order updates are on for this device. We will tell you when the status changes.</p>}{orders.length === 0 ? <p className="empty">No orders yet.</p> : orders.map(order => <article className="history clickable" key={order.clientOrderId} role="button" tabIndex={0} onClick={() => setSelectedId(order.clientOrderId)} onKeyDown={event => { if (event.key === 'Enter') setSelectedId(order.clientOrderId) }}><div><b>{order.orderNumber ?? 'Waiting to submit'}</b><small>{new Date(order.createdAt).toLocaleString('en-IN')} · {order.items.length} items</small></div>{order.serverStatus ? <span className={`server-status ${order.serverStatus}`}>{statusLabel(order.serverStatus)}</span> : <span className={order.status}>{order.status}</span>}<strong>{money(order.total)}</strong><span className="chevron">›</span></article>)}</section>
}

function OrderSummary({ order, supportPhone, onShare, onBack, onRepeat, onCancel }: { order: LocalOrder; supportPhone: string; onShare: (order: LocalOrder) => void; onBack: () => void; onRepeat: (order: LocalOrder) => Promise<void>; onCancel: () => void }) {
  return <section className="page summary"><button className="back" onClick={onBack}>← Previous orders</button><div className="summary-heading"><div>{order.serverStatus ? <span className={`server-status ${order.serverStatus}`}>{statusLabel(order.serverStatus)}</span> : <span className={order.status}>{order.status}</span>}<h1>{order.orderNumber ?? 'Order waiting to submit'}</h1><p>{new Date(order.createdAt).toLocaleString('en-IN')}</p>{order.error && <p className="error">{order.error}</p>}</div><b>{money(order.total)}</b></div><section className="summary-shop"><b>{order.shop.storeName}</b><small>{order.shop.customerName && `${order.shop.customerName} · `}{order.shop.mobile}</small>{order.shop.address && <small>{order.shop.address}</small>}</section><h2>Items</h2><table className="list-table"><thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Amount</th></tr></thead><tbody>{order.items.map(item => <tr key={`${item.id}-${item.unit}`}><td className="item"><b>{item.name}</b><small>{money(item.rate)} / {item.unit} incl. GST</small></td><td className="num">{item.quantity} ×</td><td className="num amount">{money(lineAmount(item))}</td></tr>)}</tbody></table><table className="totals-table"><tbody><tr><td>Tentative total<small>Inclusive of GST</small></td><td>{money(order.total)}</td></tr></tbody></table>{order.orderNumber && <button className="share-button" onClick={() => onShare(order)}>Share on WhatsApp</button>}<button className="primary" onClick={() => void onRepeat(order)}>Repeat this order</button>{supportPhone && <a className="summary-help" href={`https://wa.me/${supportPhone.replace(/\D/g, '')}`} target="_blank" rel="noreferrer">Need help? WhatsApp us</a>}{order.status === 'pending' && <button className="summary-cancel" onClick={onCancel}>Cancel queued order</button>}</section>
}

createRoot(document.getElementById('root')!).render(<App />)
