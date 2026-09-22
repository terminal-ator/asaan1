import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
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

type Product = { id: string; sku: string; name: string; simpleName?: string; company: string; brand: string; category: string; packing: string; unit: string; rate: number; mrp: number; schemePercent?: string; gstRate?: string; hsnCode?: string; imageUrl?: string; updatedAt: string; createdAt: string }
type CartItem = Pick<Product, 'id' | 'sku' | 'name' | 'unit' | 'rate'> & { quantity: number }
type QuantityTarget = Omit<CartItem, 'quantity'> & { simpleName?: string }
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
// A shop profile without a name or mobile is useless for billing, so treat it
// as not set up and ask for the details again.
const hasShopDetails = (shop: Shop | null): shop is Shop => Boolean(shop?.storeName?.trim() && shop?.mobile?.trim())
// Used by the header menu: drop the offline copies and start clean.
async function clearCacheAndReload() {
  try {
    if ('caches' in window) for (const key of await caches.keys()) await caches.delete(key)
    if ('serviceWorker' in navigator) for (const registration of await navigator.serviceWorker.getRegistrations()) await registration.unregister()
  } finally { window.location.reload() }
}

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

  function changeQuantity(target: QuantityTarget, delta: number) {
    const found = cart.find(item => item.id === target.id && item.unit === target.unit)
    setQuantity(target, (found?.quantity ?? 0) + delta)
  }

  function setQuantity(target: QuantityTarget, quantity: number) {
    quantity = Number.isFinite(quantity) ? Math.max(0, Math.floor(quantity)) : 0
    const found = cart.find(item => item.id === target.id && item.unit === target.unit)
    const next = quantity <= 0
      ? cart.filter(item => !(item.id === target.id && item.unit === target.unit))
      : found
        ? cart.map(item => item === found ? { ...item, quantity } : item)
        : [...cart, { id: target.id, sku: target.sku, name: target.simpleName || target.name, unit: target.unit, rate: target.rate, quantity }]
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
    if (!hasShopDetails(shop) || cart.length === 0) return
    const order: LocalOrder = { clientOrderId: crypto.randomUUID(), shop, items: cart, notes: '', total, createdAt: new Date().toISOString(), status: 'pending' }
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
    localStorage.removeItem('ordex-shop')
    await Promise.all([db.products.clear(), db.cart.clear(), db.orders.clear()])
    window.location.reload()
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
  const marginTotal = useMemo(() => {
    const byId = new Map(products.map(product => [product.id, product]))
    return cart.reduce((sum, item) => {
      const product = byId.get(item.id)
      return product && product.mrp > item.rate ? sum + (product.mrp - item.rate) * item.quantity : sum
    }, 0)
  }, [cart, products])
  const newProducts = useMemo(() => [...products].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt)).slice(0, 8), [products])

  if (!hasShopDetails(shop)) return <Registration initial={shop} onSave={saved => { localStorage.setItem('ordex-shop', JSON.stringify(saved)); setShop(saved) }} />
  return <main className={screen === 'catalogue' ? 'catalogue' : undefined}>
    <header><div className="header-brand"><span className="logo" aria-hidden="true">O</span><div><strong>Ordex</strong><span>{shop.storeName}</span></div></div><div className="header-actions"><button className="quiet" onClick={() => setScreen('orders')}>Orders</button><Menu onLogout={() => void logOut()} /></div></header>
    {message && <div className="notice">{message}<button onClick={() => setMessage('')}>×</button></div>}
    {screen === 'catalogue' && <Catalogue products={filtered} newProducts={newProducts} cart={cart} query={query} setQuery={setQuery} company={company} setCompany={setCompany} brand={brand} setBrand={setBrand} companies={companies} brands={brands} changeQuantity={changeQuantity} setQuantity={setQuantity} />}
    {screen === 'cart' && <Cart cart={cart} total={total} margin={marginTotal} onBack={() => setScreen('catalogue')} onSubmit={placeOrder} onClear={() => void saveCart([])} changeQuantity={changeQuantity} setQuantity={setQuantity} />}
    {screen === 'orders' && <Orders onBack={() => setScreen('catalogue')} onRepeat={repeatOrder} />}
    {screen === 'catalogue' && <button className="cart-fab" onClick={() => setScreen('cart')}><span className="cart-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M3 4h2l2.2 10.2a2 2 0 0 0 2 1.6h7.9a2 2 0 0 0 1.9-1.4L20.5 8H6"/><circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/></svg></span><span className="cart-copy"><b>View cart</b><small>{cart.reduce((sum, item) => sum + item.quantity, 0)} {cart.reduce((sum, item) => sum + item.quantity, 0) === 1 ? 'item' : 'items'}</small></span><strong>{money(total)}</strong><span className="cart-arrow" aria-hidden="true">›</span></button>}
  </main>
}

function Registration({ initial, onSave }: { initial?: Shop | null; onSave: (shop: Shop) => void }) {
  const [shop, setShop] = useState<Shop>(initial ?? { storeName: '', customerName: '', mobile: '', address: '' })
  const [locationState, setLocationState] = useState<'idle' | 'loading' | 'saved' | 'error'>('idle')
  const [error, setError] = useState('')
  const shareLocation = () => {
    if (!navigator.geolocation) { setLocationState('error'); return }
    setLocationState('loading')
    navigator.geolocation.getCurrentPosition(position => {
      setShop(current => ({ ...current, latitude: position.coords.latitude, longitude: position.coords.longitude, locationAccuracy: Math.round(position.coords.accuracy) }))
      setLocationState('saved')
    }, () => setLocationState('error'), { enableHighAccuracy: true, timeout: 15_000, maximumAge: 60_000 })
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const storeName = shop.storeName.trim()
    const mobile = shop.mobile.trim()
    if (!storeName || !mobile) {
      setError('Store name and mobile number are required.')
      return
    }
    setError('')
    onSave({ ...shop, storeName, mobile, customerName: shop.customerName?.trim(), address: shop.address?.trim() })
  }
  const update = (changes: Partial<Shop>) => {
    setShop(current => ({ ...current, ...changes }))
    if (error) setError('')
  }
  return <main className="registration"><div className="brand"><span className="logo" aria-hidden="true">O</span>Ordex</div><h1>Set up your shop</h1><p>Save your details on this device to make future orders quick. They are included only when you submit an order.</p><form onSubmit={submit}><Field label="Store name" value={shop.storeName} onChange={value => update({ storeName: value })} required /><Field label="Contact name" value={shop.customerName ?? ''} onChange={value => update({ customerName: value })} /><Field label="Mobile number" type="tel" value={shop.mobile} onChange={value => update({ mobile: value })} required /><Field label="GSTIN (optional)" value={shop.gstin ?? ''} onChange={value => update({ gstin: value.toUpperCase().replace(/[^0-9A-Z]/g, '') })} maxLength={15} /><Field label="Address" value={shop.address ?? ''} onChange={value => update({ address: value })} /><section className="location-card"><div><b>Shop location <small>Optional</small></b><p>{locationState === 'saved' ? `Location saved (accurate to about ${shop.locationAccuracy} m)` : locationState === 'error' ? 'Location could not be shared. You can continue without it.' : 'Share your current location to help with delivery.'}</p></div><button type="button" className="location-button" onClick={shareLocation} disabled={locationState === 'loading'}>{locationState === 'loading' ? 'Finding…' : locationState === 'saved' ? 'Update' : 'Share location'}</button></section>{error && <p className="form-error">{error}</p>}<button className="primary">Open catalogue</button></form></main>
}

function Field({ label, value, onChange, required = false, maxLength, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; maxLength?: number; type?: string }) { return <label>{label}{required && <span className="required-mark"> *</span>}<input type={type} value={value} onChange={event => onChange(event.target.value)} required={required} maxLength={maxLength} /></label> }

function Menu({ onLogout }: { onLogout: () => void }) {
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
      <button role="menuitem" onClick={() => window.location.reload()}>Refresh</button>
      <button role="menuitem" onClick={() => void clearCacheAndReload()}>Clear cache &amp; reload</button>
      <button role="menuitem" className="danger" onClick={onLogout}>Log out</button>
    </div>}
  </div>
}

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
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filterCount = (props.company ? 1 : 0) + (props.brand ? 1 : 0)
  // Open the panel whenever a filter is applied so the choice stays visible.
  useEffect(() => { if (props.company || props.brand) setFiltersOpen(true) }, [props.company, props.brand])
  return <><section className="controls"><div className="search-row"><input className="search" placeholder="Search product, brand, SKU…" value={props.query} onChange={e => props.setQuery(e.target.value)} /><button type="button" className={`filter-toggle ${filterCount ? 'active' : ''} ${filtersOpen ? 'open' : ''}`} onClick={() => setFiltersOpen(open => !open)} aria-expanded={filtersOpen} aria-controls="catalogue-filters"><svg className="filter-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" /></svg><span className="filter-label">Filters</span>{filterCount > 0 && <span className="filter-count">{filterCount}</span>}<svg className="filter-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></button></div>{filtersOpen && <div className="filters-panel" id="catalogue-filters"><div className="filter-group"><span>Company</span><div className="filter-row"><button className={`filter-pill ${!props.company ? 'selected' : ''}`} onClick={() => { props.setCompany(''); props.setBrand('') }}>All companies</button>{props.companies.map(value => <button key={value} className={`filter-pill ${props.company === value ? 'selected' : ''}`} onClick={() => { props.setCompany(value); props.setBrand('') }}>{value}</button>)}</div></div><div className="filter-group brands"><span>{props.company ? `${props.company} brands` : 'Brand'}</span><div className="filter-row"><button className={`filter-pill ${!props.brand ? 'selected' : ''}`} onClick={() => props.setBrand('')}>All brands</button>{props.brands.map(value => <button key={value} className={`filter-pill ${props.brand === value ? 'selected' : ''}`} onClick={() => props.setBrand(value)}>{value}</button>)}</div></div></div>}</section>{showNewProducts && <section className="new-products"><div><b>New products</b><small>Recently added to the catalogue</small></div><div className="new-product-row">{props.newProducts.map(product => <button key={product.id} onClick={() => openKeypad(product)}><span>{product.company}</span><b>{product.simpleName || product.name}</b><small>{product.packing} · {money(product.rate)}</small></button>)}</div></section>}<div className="count">{props.products.length} products · Tap a product to enter quantity</div><div ref={parentRef} className="product-list"><div style={{ height: virtual.getTotalSize(), position: 'relative' }}>{virtual.getVirtualItems().map(item => { const product = props.products[item.index]; const quantity = props.cart.find(line => line.id === product.id)?.quantity ?? 0; return <article className="product" key={product.id} onClick={() => openKeypad(product)} style={{ transform: `translateY(${item.start}px)` }}>{imageSource(product) ? <img className="product-image" src={imageSource(product)} loading="lazy" onError={event => { event.currentTarget.style.display = 'none' }} /> : <span className="product-image placeholder">▦</span>}<div className="product-info"><b>{product.simpleName || product.name}</b><small>{product.packing} · {product.company}</small><strong>{money(product.rate)} <em>/{product.unit}</em>{Number(product.schemePercent) > 0 && <span className="scheme-chip">{Number(product.schemePercent)}% scheme</span>}</strong></div><Quantity value={quantity} decrement={() => props.changeQuantity(product, -1)} increment={() => props.changeQuantity(product, 1)} onInput={value => props.setQuantity(product, value)} onOpenKeypad={() => openKeypad(product)} /></article> })}</div></div>{keypadProduct && <Keypad product={keypadProduct} value={keypadValue} pressKey={pressKey} onClose={() => setKeypadProduct(null)} onSave={() => { props.setQuantity(keypadProduct, Number(keypadValue)); setKeypadProduct(null) }} />}</>
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

function Keypad({ product, value, pressKey, onClose, onSave }: { product: Product; value: string; pressKey: (key: string) => void; onClose: () => void; onSave: () => void }) {
  const scheme = Number(product.schemePercent) || 0
  const gst = Number(product.gstRate) || 0
  const image = imageSource(product)
  const unitMargin = Math.max(0, product.mrp - product.rate)
  const marginPercent = product.mrp > 0 ? (unitMargin / product.mrp) * 100 : 0
  const quantity = Number(value) || 0
  const rows: { label: string; value: string; numeric?: boolean }[] = [
    { label: `Rate / ${product.unit}`, value: money(product.rate), numeric: true },
    { label: 'MRP', value: product.mrp > 0 ? money(product.mrp) : '—', numeric: true },
    ...(unitMargin > 0 ? [{ label: 'Margin / unit', value: `${money(unitMargin)} · ${marginPercent.toFixed(1)}%`, numeric: true }] : []),
    ...(scheme > 0 ? [{ label: 'Scheme', value: `${scheme}%`, numeric: true }] : []),
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
          {image
            ? <img className="keypad-image" src={image} alt="" loading="lazy" onError={event => { event.currentTarget.style.display = 'none' }} />
            : <span className="keypad-image placeholder" aria-hidden="true">▦</span>}
          <div className="keypad-heading">
            <b>{product.simpleName || product.name}</b>
            <small>{product.packing} · {product.company}</small>
          </div>
        </div>
        <button onClick={onClose} aria-label="Close keypad">×</button>
      </div>

      <div className="keypad-price">
        <strong>{money(product.rate)} <em>/{product.unit}</em></strong>
        {product.mrp > product.rate && <s>{money(product.mrp)}</s>}
        {scheme > 0 && <span className="scheme-chip">{scheme}% scheme</span>}
      </div>

      <div className="keypad-display">{value || '0'}</div>

      {unitMargin > 0 && <div className="keypad-margin">
        <span>Retail margin<small>{marginPercent.toFixed(1)}% of MRP</small></span>
        <span className="keypad-margin-value">
          <strong>{money(quantity > 0 ? unitMargin * quantity : unitMargin)}</strong>
          <em>{quantity > 0 ? `on ${quantity} ${product.unit}` : 'per unit'}</em>
        </span>
      </div>}

      <div className="keypad-grid">{['1', '2', '3', '4', '5', '6', '7', '8', '9'].map(key => <button key={key} onClick={() => pressKey(key)}>{key}</button>)}<button className="keypad-clear" onClick={() => pressKey('clear')}>Clear</button><button onClick={() => pressKey('0')}>0</button><button aria-label="Backspace" onClick={() => pressKey('backspace')}>⌫</button></div>
      <button className="keypad-save" onClick={onSave}>{Number(value) > 0 ? `Update quantity · ${money(Number(value) * product.rate)}` : 'Remove from order'}</button>

      <p className="detail-heading">Product details</p>
      <table className="detail-table">
        <tbody>
          {rows.map(row => <tr key={row.label}><th scope="row">{row.label}</th><td className={row.numeric ? 'num' : ''}>{row.value}</td></tr>)}
        </tbody>
      </table>
    </section>
  </div>
}

function Cart({ cart, total, margin, onBack, onSubmit, onClear, changeQuantity, setQuantity }: { cart: CartItem[]; total: number; margin: number; onBack: () => void; onSubmit: () => void; onClear: () => void; changeQuantity: (target: QuantityTarget, d: number) => void; setQuantity: (target: QuantityTarget, q: number) => void }) {
  const clear = () => { if (window.confirm('Clear all items from this cart?')) onClear() }
  return <section className="page"><button className="back" onClick={onBack}>← Catalogue</button><div className="cart-heading"><h1>Your order</h1>{cart.length > 0 && <button onClick={clear}>Clear cart</button>}</div>{cart.length === 0 ? <p className="empty">Your cart is empty.</p> : <><table className="list-table"><thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Amount</th></tr></thead><tbody>{cart.map(item => <tr key={`${item.id}-${item.unit}`}><td className="item"><b>{item.name}</b><small>{money(item.rate)} / {item.unit}</small><button className="remove-line" onClick={() => setQuantity(item, 0)}>Remove</button></td><td className="num"><Quantity value={item.quantity} decrement={() => changeQuantity(item, -1)} increment={() => changeQuantity(item, 1)} onInput={value => setQuantity(item, value)} /></td><td className="num amount">{money(item.quantity * item.rate)}</td></tr>)}</tbody></table><table className="totals-table"><tbody><tr><td>Tentative total</td><td>{money(total)}</td></tr>{margin > 0 && <tr className="margin-row"><td>Your retail margin<small>If sold at MRP</small></td><td>{money(margin)}</td></tr>}</tbody></table><p className="hint">Final rates, schemes, tax and availability are confirmed during billing.</p><button className="primary" onClick={() => void onSubmit()}>Submit order</button></>}</section>
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
  return <section className="page summary"><button className="back" onClick={onBack}>← Previous orders</button><div className="summary-heading"><div><span className={order.status}>{order.status}</span><h1>{order.orderNumber ?? 'Order waiting to submit'}</h1><p>{new Date(order.createdAt).toLocaleString('en-IN')}</p>{order.error && <p className="error">{order.error}</p>}</div><b>{money(order.total)}</b></div><section className="summary-shop"><b>{order.shop.storeName}</b><small>{order.shop.customerName && `${order.shop.customerName} · `}{order.shop.mobile}</small>{order.shop.address && <small>{order.shop.address}</small>}</section><h2>Items</h2><table className="list-table"><thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Amount</th></tr></thead><tbody>{order.items.map(item => <tr key={`${item.id}-${item.unit}`}><td className="item"><b>{item.name}</b><small>{money(item.rate)} / {item.unit}</small></td><td className="num">{item.quantity} ×</td><td className="num amount">{money(item.quantity * item.rate)}</td></tr>)}</tbody></table><table className="totals-table"><tbody><tr><td>Tentative total</td><td>{money(order.total)}</td></tr></tbody></table><button className="primary" onClick={() => void onRepeat(order)}>Repeat this order</button>{order.status === 'pending' && <button className="summary-cancel" onClick={onCancel}>Cancel queued order</button>}</section>
}

createRoot(document.getElementById('root')!).render(<App />)
