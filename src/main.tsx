import { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useVirtualizer } from '@tanstack/react-virtual'
import Dexie, { type EntityTable } from 'dexie'
import MiniSearch from 'minisearch'
import './styles.css'
import './filters.css'
import './location.css'
import './new-products.css'
import './order-summary.css'
import './cart-button.css'
import './cart-actions.css'
import './product-images.css'

// Same-origin by default: Vite proxies /api and /media to Django while
// developing, and in production nginx serves the built PWA next to Django.
const apiURL = import.meta.env.VITE_API_URL ?? ''

type Product = { id: string; sku: string; name: string; simpleName?: string; company: string; brand: string; category: string; packing: string; unit: string; rate: number; mrp: number; imageUrl?: string; updatedAt: string; createdAt: string }
type CartItem = Pick<Product, 'id' | 'sku' | 'name' | 'unit' | 'rate'> & { quantity: number }
type Shop = { storeName: string; customerName: string; mobile: string; gstin?: string; address?: string; latitude?: number; longitude?: number; locationAccuracy?: number }
type LocalOrder = { clientOrderId: string; shop: Shop; items: CartItem[]; notes: string; total: number; createdAt: string; status: 'pending' | 'submitted' | 'failed'; orderNumber?: string; error?: string }

class OrdexDB extends Dexie {
  products!: EntityTable<Product, 'id'>
  cart!: EntityTable<{ id: 'current'; items: CartItem[] }, 'id'>
  orders!: EntityTable<LocalOrder, 'clientOrderId'>
  constructor() {
    super('ordex')
    this.version(1).stores({ products: 'id, sku, name, company, brand, category', cart: 'id', orders: 'clientOrderId, status, createdAt' })
  }
}
const db = new OrdexDB()
const money = (paise: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(paise / 100)
const imageSource = (product: Product) => product.imageUrl?.startsWith('/') ? `${apiURL}${product.imageUrl}` : product.imageUrl

function App() {
  const [shop, setShop] = useState<Shop | null>(() => JSON.parse(localStorage.getItem('ordex-shop') || 'null'))
  const [products, setProducts] = useState<Product[]>([])
  const [cart, setCart] = useState<CartItem[]>([])
  const [query, setQuery] = useState('')
  const [company, setCompany] = useState('')
  const [brand, setBrand] = useState('')
  const [screen, setScreen] = useState<'catalogue' | 'cart' | 'orders'>('catalogue')
  const [message, setMessage] = useState('')

  useEffect(() => {
    void (async () => {
      setProducts(await db.products.toArray())
      setCart((await db.cart.get('current'))?.items ?? [])
      await refreshCatalogue()
      await retryPendingOrders()
    })()
    // A cache-first service worker is useful after deployment, but makes local
    // development appear stale after an edit.
    if (import.meta.env.PROD && 'serviceWorker' in navigator) void navigator.serviceWorker.register('/sw.js')
  }, [])

  async function refreshCatalogue() {
    try {
      const response = await fetch(`${apiURL}/api/catalogue`)
      if (!response.ok) throw new Error()
      const payload = await response.json() as { products: Product[] }
      await db.products.bulkPut(payload.products)
      setProducts(payload.products)
    } catch { setMessage('Showing saved catalogue. Updates will sync when you are online.') }
  }

  async function saveCart(next: CartItem[]) {
    setCart(next)
    await db.cart.put({ id: 'current', items: next })
  }

  function changeQuantity(product: Product, delta: number) {
    const found = cart.find(item => item.id === product.id && item.unit === product.unit)
    setQuantity(product, (found?.quantity ?? 0) + delta)
  }

  function setQuantity(product: Product, quantity: number) {
    quantity = Number.isFinite(quantity) ? Math.max(0, Math.floor(quantity)) : 0
    const found = cart.find(item => item.id === product.id && item.unit === product.unit)
    const next = quantity <= 0
      ? cart.filter(item => !(item.id === product.id && item.unit === product.unit))
      : found
        ? cart.map(item => item === found ? { ...item, quantity } : item)
        : [...cart, { id: product.id, sku: product.sku, name: product.simpleName || product.name, unit: product.unit, rate: product.rate, quantity }]
    void saveCart(next)
  }

  async function retryPendingOrders() {
    const pending = await db.orders.where('status').equals('pending').toArray()
    for (const order of pending) await sendOrder(order, false)
  }

  async function sendOrder(order: LocalOrder, showResult = true) {
    try {
      const payload = { ...order, items: order.items.map(item => ({ productId: item.id, sku: item.sku, name: item.name, unit: item.unit, quantity: item.quantity, rate: item.rate })) }
      const response = await fetch(`${apiURL}/api/orders`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
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
      const saved = { ...order, status: 'submitted' as const, orderNumber: receipt.orderNumber }
      await db.orders.put(saved)
      if (showResult) setMessage(`Order ${receipt.orderNumber} submitted successfully.`)
    } catch {
      await db.orders.put({ ...order, status: 'pending' })
      if (showResult) setMessage('Order saved on this device and will submit automatically when you are online.')
    }
  }

  async function placeOrder() {
    if (!shop || cart.length === 0) return
    const order: LocalOrder = { clientOrderId: crypto.randomUUID(), shop, items: cart, notes: '', total, createdAt: new Date().toISOString(), status: 'pending' }
    await db.orders.put(order)
    await saveCart([])
    setScreen('orders')
    await sendOrder(order)
  }

  async function repeatOrder(order: LocalOrder) {
    const productByID = new Map(products.map(product => [product.id, product]))
    const unavailable: string[] = []
    const next = order.items.flatMap(item => {
      const product = productByID.get(item.id)
      if (!product) { unavailable.push(item.name); return [] }
      return [{ id: product.id, sku: product.sku, name: product.simpleName || product.name, unit: product.unit, rate: product.rate, quantity: item.quantity }]
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
  const filtered = useMemo(() => {
    const productByID = new Map(products.map(product => [product.id, product]))
    const matches = query.trim() ? search.search(query, { prefix: true, fuzzy: 0.2, combineWith: 'AND' }).flatMap(result => {
      const product = productByID.get(String(result.id))
      return product ? [product] : []
    }) : products
    return matches.filter(product => (!company || product.company === company) && (!brand || product.brand === brand))
  }, [products, query, company, brand, search])
  const total = cart.reduce((sum, item) => sum + item.quantity * item.rate, 0)
  const newProducts = useMemo(() => [...products].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt)).slice(0, 8), [products])

  if (!shop) return <Registration onSave={saved => { localStorage.setItem('ordex-shop', JSON.stringify(saved)); setShop(saved) }} />
  return <main>
    <header><div><strong>Ordex</strong><span>{shop.storeName}</span></div><button className="quiet" onClick={() => setScreen('orders')}>Orders</button></header>
    {message && <div className="notice">{message}<button onClick={() => setMessage('')}>×</button></div>}
    {screen === 'catalogue' && <Catalogue products={filtered} newProducts={newProducts} cart={cart} query={query} setQuery={setQuery} company={company} setCompany={setCompany} brand={brand} setBrand={setBrand} companies={companies} brands={brands} changeQuantity={changeQuantity} setQuantity={setQuantity} />}
    {screen === 'cart' && <Cart cart={cart} total={total} onBack={() => setScreen('catalogue')} onSubmit={placeOrder} onClear={() => void saveCart([])} changeQuantity={changeQuantity} setQuantity={setQuantity} products={products} />}
    {screen === 'orders' && <Orders onBack={() => setScreen('catalogue')} onRepeat={repeatOrder} />}
    {screen === 'catalogue' && <button className="cart-fab" onClick={() => setScreen('cart')}><span className="cart-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M3 4h2l2.2 10.2a2 2 0 0 0 2 1.6h7.9a2 2 0 0 0 1.9-1.4L20.5 8H6"/><circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/></svg></span><span className="cart-copy"><b>View cart</b><small>{cart.reduce((sum, item) => sum + item.quantity, 0)} {cart.reduce((sum, item) => sum + item.quantity, 0) === 1 ? 'item' : 'items'}</small></span><strong>{money(total)}</strong><span className="cart-arrow" aria-hidden="true">›</span></button>}
  </main>
}

function Registration({ onSave }: { onSave: (shop: Shop) => void }) {
  const [shop, setShop] = useState<Shop>({ storeName: '', customerName: '', mobile: '', address: '' })
  const [locationState, setLocationState] = useState<'idle' | 'loading' | 'saved' | 'error'>('idle')
  const shareLocation = () => {
    if (!navigator.geolocation) { setLocationState('error'); return }
    setLocationState('loading')
    navigator.geolocation.getCurrentPosition(position => {
      setShop(current => ({ ...current, latitude: position.coords.latitude, longitude: position.coords.longitude, locationAccuracy: Math.round(position.coords.accuracy) }))
      setLocationState('saved')
    }, () => setLocationState('error'), { enableHighAccuracy: true, timeout: 15_000, maximumAge: 60_000 })
  }
  return <main className="registration"><div className="brand">Ordex</div><h1>Set up your shop</h1><p>Save your details on this device to make future orders quick. They are included only when you submit an order.</p><form onSubmit={event => { event.preventDefault(); onSave(shop) }}><Field label="Store name" value={shop.storeName} onChange={value => setShop({ ...shop, storeName: value })} required /><Field label="Contact name" value={shop.customerName} onChange={value => setShop({ ...shop, customerName: value })} /><Field label="Mobile number" value={shop.mobile} onChange={value => setShop({ ...shop, mobile: value })} required /><Field label="GSTIN (optional)" value={shop.gstin ?? ''} onChange={value => setShop({ ...shop, gstin: value.toUpperCase().replace(/[^0-9A-Z]/g, '') })} maxLength={15} /><Field label="Address" value={shop.address ?? ''} onChange={value => setShop({ ...shop, address: value })} /><section className="location-card"><div><b>Shop location <small>Optional</small></b><p>{locationState === 'saved' ? `Location saved (accurate to about ${shop.locationAccuracy} m)` : locationState === 'error' ? 'Location could not be shared. You can continue without it.' : 'Share your current location to help with delivery.'}</p></div><button type="button" className="location-button" onClick={shareLocation} disabled={locationState === 'loading'}>{locationState === 'loading' ? 'Finding…' : locationState === 'saved' ? 'Update' : 'Share location'}</button></section><button className="primary">Open catalogue</button></form></main>
}

function Field({ label, value, onChange, required = false, maxLength }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; maxLength?: number }) { return <label>{label}<input value={value} onChange={event => onChange(event.target.value)} required={required} maxLength={maxLength} /></label> }

function Catalogue(props: { products: Product[]; newProducts: Product[]; cart: CartItem[]; query: string; setQuery: (v: string) => void; company: string; setCompany: (v: string) => void; brand: string; setBrand: (v: string) => void; companies: string[]; brands: string[]; changeQuantity: (p: Product, d: number) => void; setQuantity: (p: Product, q: number) => void }) {
  const parentRef = useRef<HTMLDivElement>(null)
  const [keypadProduct, setKeypadProduct] = useState<Product | null>(null)
  const [keypadValue, setKeypadValue] = useState('')
  const virtual = useVirtualizer({ count: props.products.length, getScrollElement: () => parentRef.current, estimateSize: () => 93, overscan: 8 })
  const openKeypad = (product: Product) => {
    const quantity = props.cart.find(item => item.id === product.id && item.unit === product.unit)?.quantity ?? 0
    setKeypadProduct(product)
    setKeypadValue(quantity ? String(quantity) : '')
  }
  const pressKey = (key: string) => setKeypadValue(value => {
    if (key === 'backspace') return value.slice(0, -1)
    if (key === 'clear') return ''
    return value.length < 5 ? `${value}${key}` : value
  })
  const showNewProducts = !props.query && !props.company && !props.brand
  return <><section className="controls"><input className="search" placeholder="Search product, brand, SKU…" value={props.query} onChange={e => props.setQuery(e.target.value)} /><div className="filter-group"><span>Company</span><div className="filter-row"><button className={`filter-pill ${!props.company ? 'selected' : ''}`} onClick={() => { props.setCompany(''); props.setBrand('') }}>All companies</button>{props.companies.map(value => <button key={value} className={`filter-pill ${props.company === value ? 'selected' : ''}`} onClick={() => { props.setCompany(value); props.setBrand('') }}>{value}</button>)}</div></div><div className="filter-group brands"><span>{props.company ? `${props.company} brands` : 'Brand'}</span><div className="filter-row"><button className={`filter-pill ${!props.brand ? 'selected' : ''}`} onClick={() => props.setBrand('')}>All brands</button>{props.brands.map(value => <button key={value} className={`filter-pill ${props.brand === value ? 'selected' : ''}`} onClick={() => props.setBrand(value)}>{value}</button>)}</div></div></section>{showNewProducts && <section className="new-products"><div><b>New products</b><small>Recently added to the catalogue</small></div><div className="new-product-row">{props.newProducts.map(product => <button key={product.id} onClick={() => openKeypad(product)}><span>{product.company}</span><b>{product.simpleName || product.name}</b><small>{product.packing} · {money(product.rate)}</small></button>)}</div></section>}<div className="count">{props.products.length} products · Tap a product to enter quantity</div><div ref={parentRef} className="product-list"><div style={{ height: virtual.getTotalSize(), position: 'relative' }}>{virtual.getVirtualItems().map(item => { const product = props.products[item.index]; const quantity = props.cart.find(line => line.id === product.id)?.quantity ?? 0; return <article className="product" key={product.id} onClick={() => openKeypad(product)} style={{ transform: `translateY(${item.start}px)` }}>{imageSource(product) ? <img className="product-image" src={imageSource(product)} loading="lazy" onError={event => { event.currentTarget.style.display = 'none' }} /> : <span className="product-image placeholder">▦</span>}<div className="product-info"><b>{product.simpleName || product.name}</b><small>{product.packing} · {product.company}</small><strong>{money(product.rate)} <em>/{product.unit}</em></strong></div><Quantity value={quantity} decrement={() => props.changeQuantity(product, -1)} increment={() => props.changeQuantity(product, 1)} onInput={value => props.setQuantity(product, value)} onOpenKeypad={() => openKeypad(product)} /></article> })}</div></div>{keypadProduct && <Keypad product={keypadProduct} value={keypadValue} pressKey={pressKey} onClose={() => setKeypadProduct(null)} onSave={() => { props.setQuantity(keypadProduct, Number(keypadValue)); setKeypadProduct(null) }} />}</>
}

function Quantity({ value, decrement, increment, onInput, onOpenKeypad }: { value: number; decrement: () => void; increment: () => void; onInput: (value: number) => void; onOpenKeypad?: () => void }) { return <div className="quantity" onClick={event => event.stopPropagation()}><button aria-label="Reduce quantity" onClick={decrement}>−</button><input aria-label="Quantity" type="number" min="0" inputMode="numeric" readOnly={Boolean(onOpenKeypad)} value={value || ''} placeholder="0" onClick={() => onOpenKeypad?.()} onChange={event => onInput(Number(event.target.value))} /><button aria-label="Increase quantity" onClick={increment}>+</button></div> }

function Keypad({ product, value, pressKey, onClose, onSave }: { product: Product; value: string; pressKey: (key: string) => void; onClose: () => void; onSave: () => void }) {
  return <div className="keypad-backdrop" onClick={onClose}><section className="keypad" onClick={event => event.stopPropagation()}><div className="keypad-title"><div><b>{product.simpleName || product.name}</b><small>{product.packing} · {money(product.rate)} / {product.unit}</small></div><button onClick={onClose} aria-label="Close keypad">×</button></div><div className="keypad-display">{value || '0'}</div><div className="keypad-grid">{['1', '2', '3', '4', '5', '6', '7', '8', '9'].map(key => <button key={key} onClick={() => pressKey(key)}>{key}</button>)}<button className="keypad-clear" onClick={() => pressKey('clear')}>Clear</button><button onClick={() => pressKey('0')}>0</button><button aria-label="Backspace" onClick={() => pressKey('backspace')}>⌫</button></div><button className="keypad-save" onClick={onSave}>{Number(value) > 0 ? `Update quantity · ${money(Number(value) * product.rate)}` : 'Remove from order'}</button></section></div>
}

function Cart({ cart, total, onBack, onSubmit, onClear, changeQuantity, setQuantity, products }: { cart: CartItem[]; total: number; onBack: () => void; onSubmit: () => void; onClear: () => void; changeQuantity: (p: Product, d: number) => void; setQuantity: (p: Product, q: number) => void; products: Product[] }) {
  const clear = () => { if (window.confirm('Clear all items from this cart?')) onClear() }
  return <section className="page"><button className="back" onClick={onBack}>← Catalogue</button><div className="cart-heading"><h1>Your order</h1>{cart.length > 0 && <button onClick={clear}>Clear cart</button>}</div>{cart.length === 0 ? <p className="empty">Your cart is empty.</p> : <>{cart.map(item => { const p = products.find(product => product.id === item.id); return <article className="cart-line" key={item.id}><div><b>{item.name}</b><small>{money(item.rate)} / {item.unit}</small><button className="remove-line" onClick={() => { if (p) setQuantity(p, 0) }}>Remove</button></div><Quantity value={item.quantity} decrement={() => { if (p) changeQuantity(p, -1) }} increment={() => { if (p) changeQuantity(p, 1) }} onInput={value => { if (p) setQuantity(p, value) }} /><strong>{money(item.quantity * item.rate)}</strong></article> })}<div className="total"><span>Tentative total</span><b>{money(total)}</b></div><p className="hint">Final rates, schemes, tax and availability are confirmed during billing.</p><button className="primary" onClick={() => void onSubmit()}>Submit order</button></>}</section>
}

function Orders({ onBack, onRepeat }: { onBack: () => void; onRepeat: (order: LocalOrder) => Promise<void> }) {
  const [orders, setOrders] = useState<LocalOrder[]>([])
  const [selected, setSelected] = useState<LocalOrder | null>(null)
  const load = () => void db.orders.orderBy('createdAt').reverse().toArray().then(setOrders)
  useEffect(load, [])
  if (selected) return <OrderSummary order={selected} onBack={() => setSelected(null)} onRepeat={onRepeat} onCancel={() => { void db.orders.delete(selected.clientOrderId).then(() => { load(); setSelected(null) }) }} />
  return <section className="page"><button className="back" onClick={onBack}>← Catalogue</button><h1>Previous orders</h1>{orders.length === 0 ? <p className="empty">No orders yet.</p> : orders.map(order => <article className="history clickable" key={order.clientOrderId} role="button" tabIndex={0} onClick={() => setSelected(order)} onKeyDown={event => { if (event.key === 'Enter') setSelected(order) }}><div><b>{order.orderNumber ?? 'Waiting to submit'}</b><small>{new Date(order.createdAt).toLocaleString('en-IN')} · {order.items.length} items</small></div><span className={order.status}>{order.status}</span><strong>{money(order.total)}</strong><span className="chevron">›</span></article>)}</section>
}

function OrderSummary({ order, onBack, onRepeat, onCancel }: { order: LocalOrder; onBack: () => void; onRepeat: (order: LocalOrder) => Promise<void>; onCancel: () => void }) {
  return <section className="page summary"><button className="back" onClick={onBack}>← Previous orders</button><div className="summary-heading"><div><span className={order.status}>{order.status}</span><h1>{order.orderNumber ?? 'Order waiting to submit'}</h1><p>{new Date(order.createdAt).toLocaleString('en-IN')}</p>{order.error && <p className="error">{order.error}</p>}</div><b>{money(order.total)}</b></div><section className="summary-shop"><b>{order.shop.storeName}</b><small>{order.shop.customerName && `${order.shop.customerName} · `}{order.shop.mobile}</small>{order.shop.address && <small>{order.shop.address}</small>}</section><h2>Items</h2><div className="summary-items">{order.items.map(item => <div key={`${item.id}-${item.unit}`}><div><b>{item.name}</b><small>{money(item.rate)} / {item.unit}</small></div><span>{item.quantity} ×</span><strong>{money(item.quantity * item.rate)}</strong></div>)}</div><div className="summary-total"><span>Tentative total</span><b>{money(order.total)}</b></div><button className="primary" onClick={() => void onRepeat(order)}>Repeat this order</button>{order.status === 'pending' && <button className="summary-cancel" onClick={onCancel}>Cancel queued order</button>}</section>
}

createRoot(document.getElementById('root')!).render(<App />)
