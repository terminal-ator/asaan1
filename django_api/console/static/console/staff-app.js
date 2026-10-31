// Asaan Products: the staff phone app for adding and editing products.
// Built for one thumb: pick masters from recent chips instead of typing,
// photos straight from the camera, and "add similar" for pack-size variants.
(function () {
  const RECENTS_KEY = 'asaan-staff-recents';
  const GST_ENTRY_KEY = 'asaan-staff-rate-includes-gst';
  const DETAIL_FIELDS = ['name', 'simple_name', 'company_name', 'brand_name', 'category_name', 'packing', 'unit'];
  const PRICE_FIELDS = ['rate', 'mrp', 'hsn', 'gst_rate', 'scheme_percent', 'sku'];
  const MASTER_KINDS = { company_name: 'company', brand_name: 'brand', category_name: 'category', hsn: 'hsn' };
  const DEFAULT_UNITS = ['case', 'box', 'pcs', 'pack', 'kg'];
  const GST_RATES = ['0', '5', '12', '18', '28'];

  const money = value => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(Number(value) || 0);
  const round2 = value => Math.round((Number(value) || 0) * 100) / 100;
  const brandInitials = brand => {
    const words = String(brand || '').trim().split(/\s+/).filter(Boolean);
    if (!words.length) return '?';
    return (words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)).toUpperCase();
  };
  const brandHue = brand => [...String(brand || '')].reduce((hue, char) => (hue * 31 + char.charCodeAt(0)) % 360, 7);

  // "18" and "18.00" are the same rate; anything else compares as text.
  const same = (a, b) => {
    const left = String(a ?? ''), right = String(b ?? '');
    if (left === right) return true;
    return left.trim() !== '' && right.trim() !== '' && Number.isFinite(Number(left)) && Number(left) === Number(right);
  };

  function loadRecents() {
    try { return JSON.parse(localStorage.getItem(RECENTS_KEY)) || {}; } catch (error) { return {}; }
  }

  function emptyForm() {
    return {
      sku: '', name: '', simple_name: '', company_name: '', brand_name: '', category_name: '',
      hsn: '', hsn_code: '', packing: '', unit: 'case', rate: '', mrp: '', gst_rate: '',
      scheme_percent: '0', active: true, regular: false,
    };
  }

  window.staffApp = function (config) {
    return {
      tab: 'active',
      query: '',
      products: [],
      page: 0,
      pages: 1,
      total: 0,
      loading: false,
      listError: '',
      signedOut: false,
      lookups: { company_name: [], brand_name: [], category_name: [], hsn: [] },
      units: [...DEFAULT_UNITS],
      recents: loadRecents(),
      toast: null,
      editor: null,
      picker: null,
      archiveMatches: [],
      quickTarget: null,
      gstRates: GST_RATES,
      money,

      init() {
        this.load(true);
        let timer;
        this.$watch('query', () => { clearTimeout(timer); timer = setTimeout(() => this.load(true), 300); });
        this.$watch('tab', () => this.load(true));
        window.addEventListener('popstate', () => { this.picker = null; this.editor = null; });
        if ('serviceWorker' in navigator) navigator.serviceWorker.register(config.swUrl, { scope: config.scope }).catch(() => {});
        const sentinel = this.$refs.more;
        if (sentinel && 'IntersectionObserver' in window) {
          new IntersectionObserver(entries => {
            if (entries.some(entry => entry.isIntersecting) && !this.loading && this.page < this.pages) this.load(false);
          }, { rootMargin: '400px' }).observe(sentinel);
        }
      },

      // ---- Server calls -------------------------------------------------
      async request(url, options = {}) {
        const response = await fetch(url, { credentials: 'same-origin', ...options, headers: { 'X-CSRFToken': config.csrf, ...(options.headers || {}) } });
        if (response.status === 401 || response.status === 403) { this.signedOut = true; throw new Error('signed-out'); }
        let data = {};
        try { data = await response.json(); } catch (error) { /* empty or HTML body */ }
        if (!response.ok) {
          const failure = new Error(data.error || 'Something went wrong. Try again.');
          failure.data = data;
          failure.status = response.status;
          throw failure;
        }
        return data;
      },

      async load(reset) {
        if (this.loading && !reset) return;
        const page = reset ? 1 : this.page + 1;
        const params = new URLSearchParams({ q: this.query.trim(), page: String(page) });
        if (this.tab === 'archived') { params.set('active', 'no'); params.set('sort', 'name'); }
        else { params.set('active', 'yes'); params.set('sort', 'updated'); }
        if (this.tab === 'photos') params.set('image', 'missing');
        this.loading = true;
        this.listError = '';
        const ticket = (this.ticket = (this.ticket || 0) + 1);
        try {
          const data = await this.request(`${config.listUrl}?${params}`);
          if (ticket !== this.ticket) return;
          this.products = reset ? data.products : [...this.products, ...data.products];
          this.page = data.page;
          this.pages = data.pages;
          this.total = data.total;
          this.lookups = data.lookups;
          this.units = [...new Set([...DEFAULT_UNITS, ...data.facets.unit])];
        } catch (error) {
          if (ticket === this.ticket && error.message !== 'signed-out') this.listError = error.message;
        } finally {
          if (ticket === this.ticket) this.loading = false;
        }
      },

      // ---- List helpers -------------------------------------------------
      tileStyle(brand) { return `--tile-hue:${brandHue(brand)}`; },
      initials: brandInitials,
      inclusive(attributes) { return round2((Number(attributes.rate) || 0) * (1 + (Number(attributes.gst_rate) || 0) / 100)); },
      showToast(message, action = null) {
        clearTimeout(this.toastTimer);
        this.toast = { message, action };
        this.toastTimer = setTimeout(() => { this.toast = null; }, action ? 8000 : 3500);
      },
      runToastAction() {
        const action = this.toast && this.toast.action;
        this.toast = null;
        if (action) action.run();
      },
      replaceProduct(product) {
        const belongs = this.tab === 'archived' ? !product.active : product.active && (this.tab !== 'photos' || product.source === 'missing');
        const index = this.products.findIndex(item => item.id === product.id);
        if (index === -1) {
          if (belongs) { this.products.unshift(product); this.total += 1; }
        } else if (belongs) {
          this.products.splice(index, 1, product);
        } else {
          this.products.splice(index, 1);
          this.total -= 1;
        }
      },

      // ---- Quick photo straight from the list ---------------------------
      quickPhoto(product) {
        this.quickTarget = product;
        const input = this.$refs.quickPhoto;
        input.value = '';
        input.click();
      },
      async onQuickPhoto(event) {
        const file = event.target.files && event.target.files[0];
        const product = this.quickTarget;
        if (!file || !product) return;
        this.showToast(`Saving photo for ${product.simpleName || product.name}…`);
        const body = new FormData();
        body.append('action', 'upload');
        body.append('version', product.updatedAt);
        body.append('image', await window.shrinkPhoto(file));
        try {
          const data = await this.request(config.imageUrl.replace('__id__', product.id), { method: 'POST', body });
          this.replaceProduct(data.product);
          const next = this.tab === 'photos' ? this.products.find(item => item.source === 'missing') : null;
          this.showToast('Photo saved.', next ? { label: `Next: ${next.simpleName || next.name}`, run: () => this.quickPhoto(next) } : null);
        } catch (error) {
          if (error.message !== 'signed-out') this.showToast(error.message);
        }
      },

      // ---- Editor -------------------------------------------------------
      openEditor(mode, product = null, copyFrom = null) {
        const source = product ? product.attributes : copyFrom;
        const form = { ...emptyForm(), ...(source || {}) };
        if (mode === 'new') { form.sku = ''; form.active = true; }
        if (!form.unit) form.unit = 'case';
        this.editor = {
          mode, product, form, original: { ...form },
          copiedFrom: copyFrom ? (copyFrom.simple_name || copyFrom.name) : '',
          tab: 'details', errors: {}, error: '', saving: false,
          photo: { file: null, preview: '', remove: false, busy: false },
          includesGst: false, rateText: form.rate,
        };
        // Staff who type the rate shops pay keep doing so on the next product.
        let includesGst = false;
        try { includesGst = localStorage.getItem(GST_ENTRY_KEY) === '1'; } catch (error) { /* private mode */ }
        if (includesGst) { this.editor.includesGst = true; if (form.rate !== '') this.editor.rateText = String(this.inclusive(form)); }
        this.archiveMatches = [];
        if (!window.history.state || !window.history.state.asaanEditor) window.history.pushState({ asaanEditor: true }, '');
        this.$nextTick(() => { const name = document.getElementById('editor-name'); if (name && mode === 'new') name.focus(); });
      },
      dirty() {
        const editor = this.editor;
        if (!editor) return false;
        return editor.photo.file || editor.photo.remove || Object.keys(editor.form).some(key => !same(editor.form[key], editor.original[key]));
      },
      closeEditor(force = false) {
        if (!force && this.dirty() && !window.confirm('Discard your changes to this product?')) return;
        if (window.history.state && window.history.state.asaanEditor) window.history.back();
        else this.editor = null;
      },
      fieldError(field) {
        const list = this.editor && this.editor.errors[field];
        return list && list.length ? list[0].message : '';
      },
      lookupLabel(field, id) {
        const item = (this.lookups[field] || []).find(entry => String(entry.id) === String(id));
        if (!item) return '';
        return field === 'hsn' ? `${item.code} · ${Number(item.default_gst_rate)}% GST` : item.name;
      },
      recentChips(field) {
        const ids = (this.recents[field] || []).filter(id => this.lookupLabel(field, id));
        return ids.slice(0, 5).map(id => ({ id, label: this.lookupLabel(field, id) }));
      },
      remember(field, value) {
        if (!value) return;
        const list = (this.recents[field] || []).filter(item => String(item) !== String(value));
        this.recents[field] = [String(value), ...list].slice(0, 8);
        try { localStorage.setItem(RECENTS_KEY, JSON.stringify(this.recents)); } catch (error) { /* private mode */ }
      },
      choose(field, value) {
        this.editor.form[field] = String(value);
        delete this.editor.errors[field];
        if (field === 'hsn') {
          const hsn = this.lookups.hsn.find(entry => String(entry.id) === String(value));
          if (hsn) { this.editor.form.gst_rate = String(Number(hsn.default_gst_rate)); this.editor.form.hsn_code = hsn.code; this.syncRate(); }
        }
      },

      // Rates can be typed before or including GST; the form always stores before.
      syncRate() {
        const editor = this.editor;
        const gst = Number(editor.form.gst_rate) || 0;
        // An untouched rate keeps its stored value; only the display follows GST.
        if (!editor.rateTouched) {
          if (editor.includesGst && editor.form.rate !== '') editor.rateText = String(this.inclusive(editor.form));
          return;
        }
        if (editor.rateText === '') { editor.form.rate = ''; return; }
        const typed = Number(editor.rateText);
        if (!Number.isFinite(typed)) { editor.form.rate = editor.rateText; return; }
        editor.form.rate = editor.includesGst ? String(round2(typed / (1 + gst / 100))) : editor.rateText;
      },
      toggleIncludesGst() {
        const editor = this.editor;
        editor.includesGst = !editor.includesGst;
        try { localStorage.setItem(GST_ENTRY_KEY, editor.includesGst ? '1' : '0'); } catch (error) { /* private mode */ }
        if (editor.form.rate !== '') editor.rateText = editor.includesGst ? String(this.inclusive(editor.form)) : editor.form.rate;
      },
      priceSummary() {
        const form = this.editor.form;
        if (form.rate === '' || !Number.isFinite(Number(form.rate))) return '';
        const shopsPay = this.inclusive(form);
        const mrp = Number(form.mrp) || 0;
        let text = `Shops pay ${money(shopsPay)} per ${form.unit || 'unit'} incl. GST`;
        if (mrp > shopsPay) text += ` · margin ${money(mrp - shopsPay)} (${((mrp - shopsPay) / mrp * 100).toFixed(1)}%)`;
        return text;
      },

      // Names as you type a new product: offer archived matches to restore.
      async findArchived() {
        const editor = this.editor;
        if (!editor || editor.mode !== 'new') return;
        const words = editor.form.name.trim().split(/\s+/).filter(word => word.length > 1).slice(0, 2);
        clearTimeout(this.archiveTimer);
        if (!words.length || words.join('').length < 3) { this.archiveMatches = []; return; }
        this.archiveTimer = setTimeout(async () => {
          try {
            const data = await this.request(`${config.listUrl}?${new URLSearchParams({ q: words.join(' '), active: 'no', sort: 'name' })}`);
            if (this.editor && this.editor.mode === 'new') this.archiveMatches = data.products.slice(0, 3);
          } catch (error) { this.archiveMatches = []; }
        }, 350);
      },
      async restore(product, openAfter = false) {
        const body = new FormData();
        body.append('version', product.updatedAt);
        body.append('attributes', JSON.stringify({ active: true }));
        try {
          const data = await this.request(config.updateUrl.replace('__id__', product.id), { method: 'POST', body });
          this.replaceProduct(data.product);
          this.showToast(`Restored ${data.product.simpleName || data.product.name}. Check its rate.`);
          if (openAfter) { this.editor = null; this.openEditor('edit', data.product); }
        } catch (error) {
          if (error.message !== 'signed-out') this.showToast(error.message);
        }
      },

      pickPhoto(camera) {
        const input = this.$refs.editorPhoto;
        if (camera) input.setAttribute('capture', 'environment'); else input.removeAttribute('capture');
        input.value = '';
        input.click();
      },
      async onEditorPhoto(event) {
        const file = event.target.files && event.target.files[0];
        if (!file || !this.editor) return;
        const photo = this.editor.photo;
        photo.busy = true;
        if (photo.preview) URL.revokeObjectURL(photo.preview);
        photo.preview = URL.createObjectURL(file);
        photo.file = await window.shrinkPhoto(file);
        photo.remove = false;
        photo.busy = false;
      },
      currentPhoto() {
        const editor = this.editor;
        if (editor.photo.preview) return editor.photo.preview;
        if (editor.photo.remove || !editor.product) return '';
        return editor.product.imageUrl || '';
      },

      // ---- Pickers for company, brand, category and HSN -----------------
      openPicker(field, label) {
        this.picker = { field, label, query: '', creating: false, gst: '18', error: '' };
        this.$nextTick(() => { const input = document.getElementById('picker-search'); if (input) input.focus(); });
      },
      pickerItems() {
        const picker = this.picker;
        const words = picker.query.toLowerCase().split(/\s+/).filter(Boolean);
        const recent = this.recents[picker.field] || [];
        return (this.lookups[picker.field] || [])
          .map(item => ({ id: String(item.id), label: picker.field === 'hsn' ? `${item.code} · ${Number(item.default_gst_rate)}% GST${item.description ? ' · ' + item.description : ''}` : item.name }))
          .filter(item => words.every(word => item.label.toLowerCase().includes(word)))
          .sort((a, b) => {
            const ra = recent.indexOf(a.id), rb = recent.indexOf(b.id);
            if (ra !== rb) return (ra === -1 ? 99 : ra) - (rb === -1 ? 99 : rb);
            return a.label.localeCompare(b.label, 'en-IN', { numeric: true });
          })
          .slice(0, 60);
      },
      pick(id) {
        this.choose(this.picker.field, id);
        this.picker = null;
      },
      async createMaster() {
        const picker = this.picker;
        const name = picker.query.trim();
        if (!name) return;
        picker.creating = true;
        picker.error = '';
        const body = new URLSearchParams({ kind: MASTER_KINDS[picker.field], name, default_gst_rate: picker.gst });
        try {
          const data = await this.request(config.lookupUrl, { method: 'POST', body });
          const list = this.lookups[picker.field];
          if (!list.some(item => String(item.id) === String(data.id))) {
            list.push(picker.field === 'hsn' ? { id: data.id, code: name, description: '', default_gst_rate: data.gstRate || picker.gst } : { id: data.id, name: data.label });
          }
          this.pick(data.id);
        } catch (error) {
          if (error.message !== 'signed-out') picker.error = error.message;
        } finally {
          if (this.picker) this.picker.creating = false;
        }
      },

      // A new product with this one's details; SKU and photo are left for the copy.
      duplicate() {
        const editor = this.editor;
        if (!editor || editor.mode !== 'edit') return;
        const label = editor.product.simpleName || editor.product.name;
        if (this.dirty() && !window.confirm(`Your changes to ${label} have not been saved. Duplicate it anyway?`)) return;
        const copy = { ...editor.form };
        this.editor = null;
        this.openEditor('new', null, copy);
      },

      // ---- Save ---------------------------------------------------------
      async save(andSimilar = false) {
        const editor = this.editor;
        if (!editor || editor.saving) return;
        this.syncRate();
        editor.saving = true;
        editor.error = '';
        editor.errors = {};
        try {
          let product;
          if (editor.mode === 'new') {
            const body = new FormData();
            for (const key of ['name', 'simple_name', 'company_name', 'brand_name', 'category_name', 'packing', 'unit', 'rate', 'mrp', 'hsn', 'gst_rate', 'scheme_percent', 'sku']) body.append(key, editor.form[key] ?? '');
            if (editor.form.regular) body.append('regular', 'on');
            if (editor.photo.file) body.append('image', editor.photo.file);
            product = (await this.request(config.createUrl, { method: 'POST', body })).product;
          } else {
            const changes = {};
            for (const key of Object.keys(editor.form)) if (!same(editor.form[key], editor.original[key])) changes[key] = editor.form[key];
            const body = new FormData();
            body.append('version', editor.product.updatedAt);
            if (Object.keys(changes).length) body.append('attributes', JSON.stringify(changes));
            if (editor.photo.file) { body.append('action', 'upload'); body.append('image', editor.photo.file); }
            else if (editor.photo.remove) body.append('action', 'remove');
            else body.append('action', 'keep');
            if (!Object.keys(changes).length && !editor.photo.file && !editor.photo.remove) { this.closeEditor(true); return; }
            product = (await this.request(config.updateUrl.replace('__id__', editor.product.id), { method: 'POST', body })).product;
          }
          ['company_name', 'brand_name', 'category_name', 'hsn'].forEach(field => this.remember(field, editor.form[field]));
          this.replaceProduct(product);
          const label = product.simpleName || product.name;
          if (andSimilar) {
            // Keep everything but the SKU and photo: pack sizes usually differ by name, packing and price only.
            const copy = { ...product.attributes };
            this.editor = null;
            this.openEditor('new', null, copy);
            this.showToast(`Saved ${label}. Now change what differs.`);
          } else {
            this.closeEditor(true);
            this.showToast(editor.mode === 'new' ? `Added ${label}.` : `Saved ${label}.`);
          }
        } catch (error) {
          if (error.message === 'signed-out') return;
          editor.error = error.message;
          if (error.data && error.data.archived) {
            editor.archived = error.data.archived;
          }
          if (error.data && error.data.errors) {
            editor.errors = error.data.errors;
            const fields = Object.keys(error.data.errors);
            if (fields.some(field => DETAIL_FIELDS.includes(field))) editor.tab = 'details';
            else if (fields.some(field => PRICE_FIELDS.includes(field))) editor.tab = 'price';
            else if (fields.includes('image')) editor.tab = 'photo';
          }
        } finally {
          if (this.editor) this.editor.saving = false;
        }
      },
    };
  };
})();
