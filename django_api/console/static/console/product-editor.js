// Shared by the full product form and Quick add: searchable master pickers
// with "create new", HSN → GST defaulting, and on-device photo shrinking.
(function () {
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
  const lookupUrl = document.currentScript.dataset.lookupUrl;
  const lookupKinds = {id_company_name: ['company', 'company'], id_brand_name: ['brand', 'brand'], id_category_name: ['category', 'category'], id_hsn: ['hsn', 'HSN']};
  function superpowerSelect(select, kind, label) {
    if (!select || select.dataset.superpower) return;
    select.dataset.superpower = 'true';
    const wrap = document.createElement('div'); wrap.className = 'relative';
    select.parentNode.insertBefore(wrap, select); wrap.appendChild(select); select.classList.add('hidden');
    const input = document.createElement('input'); input.type = 'search'; input.placeholder = `Search ${label}…`; input.autocomplete = 'off'; input.className = 'w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100';
    const menu = document.createElement('div'); menu.className = 'absolute left-0 right-0 z-40 mt-1 hidden max-h-60 overflow-y-auto rounded-xl border border-slate-200 bg-white p-1 shadow-xl'; wrap.append(input, menu);
    const selectedText = () => select.options[select.selectedIndex]?.text || '';
    input.value = select.value ? selectedText() : '';
    const close = () => menu.classList.add('hidden');
    const render = () => { const q = input.value.toLowerCase(); menu.innerHTML = '';
      const create = document.createElement('button'); create.type = 'button'; create.textContent = `+ Create new ${label}`; create.className = 'mb-1 block w-full rounded-lg border-b border-slate-100 px-3 py-2 text-left text-sm font-semibold text-brand-600 hover:bg-brand-50';
      create.onclick = () => { close(); window.dispatchEvent(new CustomEvent('open-product-master', {detail: {kind, selectId: select.id, label}})); };
      menu.appendChild(create); Array.from(select.options).filter(o => !q || o.text.toLowerCase().includes(q)).forEach(option => { const button = document.createElement('button'); button.type = 'button'; button.textContent = option.text; button.className = 'block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-brand-50'; button.onclick = () => { select.value = option.value; input.value = option.value ? option.text : ''; select.dispatchEvent(new Event('change', {bubbles: true})); close(); }; menu.appendChild(button); }); menu.classList.remove('hidden'); };
    input.onfocus = () => { input.select(); render(); }; input.oninput = render; select.onchange = () => { input.value = select.value ? selectedText() : ''; }; document.addEventListener('click', event => { if (!wrap.contains(event.target)) close(); });
  }
  Object.entries(lookupKinds).forEach(([id, [kind, label]]) => superpowerSelect(document.getElementById(id), kind, label));
  const hsnSelect = document.getElementById('id_hsn');
  const gstInput = document.getElementById('id_gst_rate');
  if (hsnSelect && gstInput) hsnSelect.addEventListener('change', () => { const match = hsnSelect.options[hsnSelect.selectedIndex]?.text.match(/\(([\d.]+)%\)$/); if (match) gstInput.value = match[1]; });
  function productEditor(initialTab) {
    return {tab: initialTab || 'details', saving: false, preview: '', photoName: '', photoBusy: false, master: null, masterLabel: '', masterValue: '', masterRate: '0', masterSelectId: '', masterSaving: false, masterError: '',
      openMaster(detail) { this.master = detail.kind; this.masterLabel = detail.label.charAt(0).toUpperCase() + detail.label.slice(1); this.masterSelectId = detail.selectId; this.masterValue = ''; this.masterRate = '0'; this.masterError = ''; },
      async createMaster() { this.masterSaving = true; this.masterError = ''; try { const response = await fetch(lookupUrl, {method: 'POST', headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded'}, body: new URLSearchParams({kind: this.master, name: this.masterValue.trim(), default_gst_rate: this.masterRate})}); const data = await response.json(); if (!response.ok) { this.masterError = data.error || 'Could not create master.'; return; } const select = document.getElementById(this.masterSelectId); select.add(new Option(data.label, data.id, true, true)); select.dispatchEvent(new Event('change', {bubbles: true})); if (this.master === 'hsn' && data.gstRate) document.getElementById('id_gst_rate').value = data.gstRate; this.master = null; } catch (error) { this.masterError = 'Network error. Try again.'; } finally { this.masterSaving = false; } },
      pickPhoto(camera) {
        const input = this.$refs.photoInput;
        if (!input) return;
        if (camera) input.setAttribute('capture', 'environment');
        else input.removeAttribute('capture');
        input.value = '';
        input.click();
      },
      async onPhotoPicked(event) {
        const input = event.target;
        const file = input.files && input.files[0];
        if (!file) return;
        this.photoBusy = true;
        if (this.preview) URL.revokeObjectURL(this.preview);
        this.preview = URL.createObjectURL(file);
        try {
          const optimised = await window.shrinkPhoto(file);
          if (optimised !== file) {
            const transfer = new DataTransfer();
            transfer.items.add(optimised);
            input.files = transfer.files;
          }
          this.photoName = optimised.name + ' · ' + Math.round(optimised.size / 1024) + ' KB';
        } catch (error) {
          this.photoName = file.name + ' · ' + Math.round(file.size / 1024) + ' KB';
        } finally {
          this.photoBusy = false;
        }
      }
    };
  }
  window.productEditor = productEditor;
})();
