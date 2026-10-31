(() => {
  'use strict';
  const root = document.getElementById('image-workspace');
  if (!root) return;
  const $ = id => document.getElementById(`iw-${id}`);
  const filters = [...root.querySelectorAll('[data-filter]')];
  const tabs = [...root.querySelectorAll('[data-tab]')];
  const dialog = $('dialog');
  const canvas = $('canvas');
  const attributeInputs = [...root.querySelectorAll('[data-attribute]')];
  const attributeInput = name => attributeInputs.find(input => input.dataset.attribute === name);
  const csrf = root.querySelector('[name=csrfmiddlewaretoken]').value;
  let lookups = {}, originalAttributes = '', attributesDirty = false;
  let products = [], page = 1, pages = 1, controller, searchTimer, loading = false;
  let selected = null, draftFile = null, localUrl = '', bitmap = null;
  let busy = false, imageBusy = false, editChanged = false, urlChanged = false, activeTab = 'upload', imageTicket = 0;
  let transform = { rotation: 0, flip: false, zoom: 1, brightness: 100, crop: 'original', x: 0, y: 0 };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function icon(kind) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.6');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', kind === 'camera'
      ? 'M3 7h4l2-3h6l2 3h4v13H3z M16 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0'
      : 'M4 4h16v16H4z M4 17l5-5 4 4 3-3 4 4 M9 8h.01');
    svg.append(path);
    return svg;
  }
  function notice(message, error = false) {
    $('notice').textContent = message;
    $('notice').classList.toggle('error', error);
    $('notice').hidden = !message;
  }
  function editorStatus(message, error = true) {
    $('editor-status').textContent = message;
    $('editor-status').hidden = !message;
    $('editor-status').classList.toggle('info', !error);
  }
  function dirty() { return Boolean(draftFile || editChanged || urlChanged || attributesDirty); }
  function attributes() {
    return Object.fromEntries(attributeInputs.map(input => [input.dataset.attribute, input.type === 'checkbox' ? input.checked : input.value]));
  }
  function clearFieldErrors() {
    for (const input of attributeInputs) {
      input.removeAttribute('aria-invalid');
      document.getElementById(`${input.id}-error`).textContent = '';
    }
  }
  function showFieldErrors(errors) {
    clearFieldErrors();
    let first;
    for (const [name, messages] of Object.entries(errors || {})) {
      const input = attributeInput(name);
      if (!input) continue;
      input.setAttribute('aria-invalid', 'true');
      document.getElementById(`${input.id}-error`).textContent = messages.map(error => error.message).join(' ');
      first ||= input;
    }
    if (first) {
      setTab(first.closest('[role=tabpanel]').id.replace('iw-panel-', ''));
      first.focus();
    }
  }
  function updatePricePreview() {
    const rate = Number(attributeInput('rate').value), gst = Number(attributeInput('gst_rate').value);
    const formatter = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' });
    const paise = Math.round(rate * 100);
    const rawTax = paise * Math.round(gst * 100) / 10000;
    const wholeTax = Math.floor(rawTax);
    // Match Product.gst_amount: Python rounds a half-paise to the nearest even paise.
    const tax = rawTax - wholeTax === 0.5 ? wholeTax + wholeTax % 2 : Math.round(rawTax);
    $('price-preview').textContent = Number.isFinite(rate) && Number.isFinite(gst)
      ? `Shop rate incl. GST: ${formatter.format((paise + tax) / 100)}` : 'Enter a valid sale rate and GST percentage.';
  }
  function fillAttributes(product) {
    for (const input of attributeInputs) {
      const name = input.dataset.attribute;
      if (input.tagName === 'SELECT') {
        input.replaceChildren(new Option(name === 'hsn' ? 'No HSN master' : 'Select…', ''));
        for (const choice of lookups[name] || []) {
          const label = name === 'hsn' ? `${choice.code} · ${choice.default_gst_rate}%${choice.description ? ' · ' + choice.description : ''}` : choice.name;
          input.add(new Option(label, String(choice.id)));
        }
      }
      if (input.type === 'checkbox') input.checked = product.attributes[name];
      else input.value = product.attributes[name] ?? '';
    }
    attributeInput('hsn_code').readOnly = Boolean(attributeInput('hsn').value);
    originalAttributes = JSON.stringify(attributes());
    attributesDirty = false;
    clearFieldErrors();
    updatePricePreview();
  }
  function updateButtons() {
    const blocked = busy || imageBusy;
    $('save').disabled = blocked || !dirty();
    $('save-next').disabled = blocked || !dirty();
    $('save-next').textContent = busy ? 'Saving…' : 'Save & next →';
    $('remove').disabled = blocked || !selected?.imageUrl;
    for (const id of ['camera', 'choose', 'dropzone', 'url', 'url-preview']) $(id).disabled = blocked;
    for (const id of ['cancel', 'close']) $(id).disabled = busy;
    tabs.forEach(tab => { tab.disabled = blocked; });
    attributeInputs.forEach(input => { input.disabled = busy; });
    for (const id of ['crop', 'zoom', 'brightness', 'rotate-left', 'rotate-right', 'flip', 'edit-reset']) {
      $(id).disabled = blocked || !bitmap;
    }
  }
  function readLocation() {
    const params = new URLSearchParams(location.search);
    $('search').value = params.get('q') || '';
    $('sort').value = params.get('sort') || 'company';
    if (!$('sort').value) $('sort').value = 'company';
    for (const select of filters) {
      const value = params.get(select.dataset.filter) || '';
      if (value && ![...select.options].some(option => option.value === value)) select.add(new Option(value, value));
      select.value = value;
    }
    page = Math.max(1, parseInt(params.get('page'), 10) || 1);
  }
  function params() {
    const values = new URLSearchParams();
    if ($('search').value.trim()) values.set('q', $('search').value.trim());
    for (const select of filters) if (select.value) values.set(select.dataset.filter, select.value);
    if ($('sort').value !== 'company') values.set('sort', $('sort').value);
    if (page > 1) values.set('page', String(page));
    return values;
  }
  function updateLocation() {
    const query = params().toString();
    history.replaceState(null, '', location.pathname + (query ? `?${query}` : ''));
    const count = filters.filter(select => select.value).length;
    $('filter-count').textContent = count ? `(${count})` : '';
  }
  async function responseData(response) {
    if (response.status === 401) throw new Error('Your session expired. Sign in again, then refresh this page.');
    let data;
    try { data = await response.json(); }
    catch { throw new Error('The server could not complete this request. Please try again.'); }
    if (!response.ok) {
      const errors = Object.values(data.errors || {}).flat().map(error => error.message);
      const error = new Error(errors.length ? [...new Set(errors)].join(' ') : data.error || 'Could not complete this request.');
      error.fields = data.errors;
      throw error;
    }
    return data;
  }
  function renderCards() {
    $('grid').replaceChildren();
    for (const product of products) {
      const card = element('article', 'iw-card');
      const imageButton = element('button', 'iw-card-image');
      imageButton.type = 'button';
      imageButton.setAttribute('aria-label', `Edit image for ${product.simpleName || product.name}`);
      imageButton.addEventListener('click', () => openEditor(product));
      const placeholder = element('span', 'iw-placeholder');
      placeholder.append(icon('image'), element('span', '', 'Add a product photo'));
      imageButton.append(placeholder);
      if (product.imageUrl) {
        const image = element('img');
        image.src = product.imageUrl;
        image.alt = product.simpleName || product.name;
        image.loading = 'lazy';
        placeholder.hidden = true;
        image.addEventListener('error', () => {
          image.hidden = true;
          placeholder.hidden = false;
          placeholder.lastChild.textContent = 'Image unavailable';
        });
        imageButton.append(image);
      }
      imageButton.append(element('span', `iw-badge ${product.source}`, { missing: 'Missing image', uploaded: 'Uploaded', linked: 'Image URL' }[product.source]));
      const body = element('div', 'iw-card-body');
      const name = element('h3', '', product.simpleName || product.name);
      const nameButton = element('button', 'iw-name-button', product.simpleName || product.name);
      nameButton.type = 'button';
      nameButton.setAttribute('aria-label', `Edit details for ${product.simpleName || product.name}`);
      nameButton.addEventListener('click', () => openEditor(product, 'details'));
      name.replaceChildren(nameButton);
      name.title = product.name;
      const meta = element('p', 'iw-card-meta', `${product.company} · ${product.brand}`);
      meta.title = `${product.company} · ${product.brand} · ${product.category}`;
      body.append(name, meta, element('p', 'iw-card-sku', `${product.sku} · ${product.packing}`));
      const tags = element('p', 'iw-card-tags');
      if (!product.active) tags.append(element('span', '', 'Inactive'));
      if (product.regular) tags.append(element('span', '', 'Regular'));
      if (tags.childNodes.length) body.append(tags);
      const actions = element('div', 'iw-card-actions');
      const edit = element('button', 'iw-button', 'Edit product');
      edit.type = 'button';
      edit.addEventListener('click', () => openEditor(product, 'details'));
      const camera = element('button', 'iw-button iw-camera-button');
      camera.type = 'button';
      camera.title = 'Take photo';
      camera.setAttribute('aria-label', `Take photo of ${product.simpleName || product.name}`);
      camera.append(icon('camera'));
      camera.addEventListener('click', () => { openEditor(product); pickFile(true); });
      actions.append(edit, camera);
      body.append(actions);
      card.append(imageButton, body);
      $('grid').append(card);
    }
  }
  async function loadProducts() {
    controller?.abort();
    const current = new AbortController();
    controller = current;
    loading = true;
    $('grid').setAttribute('aria-busy', 'true');
    $('prev').disabled = $('next').disabled = true;
    $('count').textContent = 'Loading products…';
    updateLocation();
    try {
      const response = await fetch(`${root.dataset.listUrl}?${params()}`, { signal: current.signal, cache: 'no-store' });
      const data = await responseData(response);
      if (controller !== current || current.signal.aborted) return false;
      products = data.products;
      lookups = data.lookups;
      $('unit-options').replaceChildren(...data.facets.unit.map(unit => new Option(unit, unit)));
      page = data.page;
      pages = data.pages;
      for (const key of ['company', 'brand', 'category', 'unit']) {
        const select = filters.find(filter => filter.dataset.filter === key);
        const value = select.value, label = select.options[0].textContent;
        select.replaceChildren(new Option(label, ''));
        data.facets[key].forEach(choice => select.add(new Option(choice, choice)));
        if (value && !data.facets[key].includes(value)) select.add(new Option(value, value));
        select.value = value;
      }
      renderCards();
      $('empty').hidden = data.total !== 0;
      $('count').textContent = `${data.total.toLocaleString()} product${data.total === 1 ? '' : 's'}${params().size ? ' matching your view' : ''}`;
      $('page').textContent = `Page ${page} of ${pages}`;
      updateLocation();
      return true;
    } catch (error) {
      if (error.name !== 'AbortError' && controller === current) {
        notice(`${error.message} Use Refresh to try again.`, true);
        $('count').textContent = 'Unable to load products';
      }
      return false;
    } finally {
      if (controller === current) {
        loading = false;
        $('grid').setAttribute('aria-busy', 'false');
        $('prev').disabled = page <= 1;
        $('next').disabled = page >= pages;
      }
    }
  }
  function resetFilters() {
    clearTimeout(searchTimer);
    $('search').value = '';
    filters.forEach(select => { select.value = ''; });
    $('sort').value = 'company';
    page = 1;
    notice('');
    void loadProducts();
  }
  function clearDraft() {
    imageTicket++;
    if (localUrl) URL.revokeObjectURL(localUrl);
    localUrl = '';
    bitmap = null;
    draftFile = null;
    editChanged = false;
    urlChanged = false;
    imageBusy = false;
    attributesDirty = false;
    $('file').value = '';
    $('file-info').textContent = '';
    resetTransform();
  }
  function resetTransform() {
    transform = { rotation: 0, flip: false, zoom: 1, brightness: 100, crop: 'original', x: 0, y: 0 };
    $('crop').value = 'original';
    $('zoom').value = '1';
    $('brightness').value = '100';
    $('zoom-value').textContent = '1×';
    $('brightness-value').textContent = '100%';
    $('flip').setAttribute('aria-pressed', 'false');
  }
  function previewImage(source, label) {
    canvas.hidden = true;
    const image = $('preview-image');
    image.hidden = !source;
    $('preview-empty').hidden = Boolean(source);
    $('preview-empty').textContent = 'No image yet';
    if (source) image.src = source;
    else image.removeAttribute('src');
    $('preview-tag').textContent = label;
  }
  function openEditor(product, initialTab = 'upload') {
    clearDraft();
    selected = product;
    fillAttributes(product);
    $('editor-title').textContent = product.simpleName || product.name;
    $('editor-sku').textContent = product.sku;
    $('editor-meta').textContent = `${product.company} · ${product.brand} · ${product.packing}`;
    $('url').value = product.source === 'linked' ? product.imageUrl : '';
    $('edit-hint').textContent = 'Choose an image or edit the current photo. Drag the preview to position your crop.';
    editorStatus('');
    previewImage(product.imageUrl, 'Current image');
    setTab(initialTab);
    updateButtons();
    if (!dialog.open) dialog.showModal();
    if (['details', 'pricing'].includes(initialTab)) {
      const input = attributeInput(initialTab === 'pricing' ? 'rate' : product.simpleName ? 'simple_name' : 'name');
      input.focus();
      input.select();
    }
  }
  function closeEditor() {
    if (busy) return;
    if (dirty() && !window.confirm('Discard your unsaved product changes?')) return;
    dialog.close();
    clearDraft();
    selected = null;
  }
  function setTab(name) {
    activeTab = name;
    const detailsTab = ['details', 'pricing'].includes(name);
    $('preview').hidden = detailsTab;
    $('media-controls').hidden = detailsTab;
    tabs.forEach(tab => {
      const chosen = tab.dataset.tab === name;
      tab.setAttribute('aria-selected', String(chosen));
      tab.tabIndex = chosen ? 0 : -1;
      $(`panel-${tab.dataset.tab}`).hidden = !chosen;
    });
    if (detailsTab) return;
    if (name === 'edit') {
      if (bitmap) drawPreview();
      else if (selected?.imageUrl) void loadExistingImage();
      else editorStatus('Choose a photo first to use the editing tools.', false);
    } else if (name === 'url') {
      previewImage($('url').value.trim(), urlChanged ? 'URL preview' : 'Current image URL');
    } else if (bitmap && (editChanged || draftFile)) {
      drawPreview();
    } else {
      previewImage(selected?.imageUrl, 'Current image');
    }
  }
  function pickFile(camera = false) {
    if (busy || imageBusy) return;
    $('file').value = '';
    if (camera) $('file').setAttribute('capture', 'environment');
    else $('file').removeAttribute('capture');
    $('file').click();
  }
  function loadImage(source, crossOrigin = false) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      const timer = setTimeout(() => { image.src = ''; reject(new Error('Image loading timed out.')); }, 20000);
      if (crossOrigin) image.crossOrigin = 'anonymous';
      image.onload = () => { clearTimeout(timer); resolve(image); };
      image.onerror = () => { clearTimeout(timer); reject(new Error('The image could not be loaded.')); };
      image.src = source;
    });
  }
  async function loadExistingImage() {
    if (imageBusy || busy) return;
    const ticket = ++imageTicket;
    imageBusy = true;
    editorStatus('Loading image for editing…', false);
    updateButtons();
    try {
      const image = await loadImage(selected.imageUrl, true);
      if (ticket !== imageTicket) return;
      bitmap = image;
      // Test canvas access before offering save; external hosts may deny it.
      const probe = document.createElement('canvas');
      probe.width = probe.height = 1;
      probe.getContext('2d').drawImage(image, 0, 0, 1, 1);
      probe.getContext('2d').getImageData(0, 0, 1, 1);
      editorStatus('');
      drawPreview();
    } catch {
      if (ticket !== imageTicket) return;
      bitmap = null;
      editorStatus('This photo cannot be edited here. Its host may restrict access. Download it and choose the file, or upload a replacement.');
    } finally {
      if (ticket === imageTicket) { imageBusy = false; updateButtons(); }
    }
  }
  async function acceptFile(file) {
    if (!file || busy || imageBusy) return;
    if (file.size > 10 * 1024 * 1024) { editorStatus('Choose an image smaller than 10 MB.'); return; }
    if (file.type && !file.type.startsWith('image/')) { editorStatus('Choose an image file.'); return; }
    imageBusy = true;
    updateButtons();
    const ticket = ++imageTicket;
    const source = URL.createObjectURL(file);
    editorStatus('Preparing your photo…', false);
    try {
      const image = await loadImage(source);
      if (ticket !== imageTicket) { URL.revokeObjectURL(source); return; }
      if (image.naturalWidth * image.naturalHeight > 40000000) throw new Error('too many pixels');
      if (localUrl) URL.revokeObjectURL(localUrl);
      localUrl = source;
      draftFile = file;
      bitmap = image;
      urlChanged = false;
      $('url').value = '';
      resetTransform();
      editChanged = false;
      $('file-info').textContent = `${file.name || 'Pasted photo'} · ${Math.round(file.size / 1024)} KB · ${image.naturalWidth} × ${image.naturalHeight}`;
      editorStatus('');
      setTab('edit');
    } catch {
      URL.revokeObjectURL(source);
      if (ticket === imageTicket) editorStatus('This image could not be opened. Choose a JPEG, PNG or WebP photo with fewer than 40 million pixels.');
    } finally {
      if (ticket === imageTicket) { imageBusy = false; updateButtons(); }
    }
  }
  function geometry() {
    const quarterTurn = transform.rotation % 180 !== 0;
    const width = quarterTurn ? bitmap.naturalHeight : bitmap.naturalWidth;
    const height = quarterTurn ? bitmap.naturalWidth : bitmap.naturalHeight;
    const ratio = transform.crop === 'original' ? width / height : Number(transform.crop);
    const cropWidth = Math.min(width, height * ratio) / transform.zoom;
    const cropHeight = cropWidth / ratio;
    const maxX = (width - cropWidth) / 2, maxY = (height - cropHeight) / 2;
    transform.x = Math.max(-maxX, Math.min(maxX, transform.x));
    transform.y = Math.max(-maxY, Math.min(maxY, transform.y));
    return { width, height, cropWidth, cropHeight };
  }
  function draw(target, maxSide) {
    const shape = geometry();
    const scale = Math.min(1, maxSide / Math.max(shape.cropWidth, shape.cropHeight));
    target.width = Math.max(1, Math.round(shape.cropWidth * scale));
    target.height = Math.max(1, Math.round(shape.cropHeight * scale));
    const context = target.getContext('2d');
    // Keep white backgrounds consistent for transparent pack photos and JPEG output.
    context.fillStyle = '#fff';
    context.fillRect(0, 0, target.width, target.height);
    context.save();
    const nativeFilters = 'filter' in context;
    if (nativeFilters) context.filter = `brightness(${transform.brightness}%)`;
    context.translate(target.width / 2, target.height / 2);
    context.scale(target.width / shape.cropWidth, target.height / shape.cropHeight);
    context.translate(-transform.x, -transform.y);
    if (transform.flip) context.scale(-1, 1);
    context.rotate(transform.rotation * Math.PI / 180);
    context.drawImage(bitmap, -bitmap.naturalWidth / 2, -bitmap.naturalHeight / 2);
    context.restore();
    // Some mobile browsers lack canvas filters; keep preview and saved pixels consistent.
    if (!nativeFilters && transform.brightness !== 100) {
      const pixels = context.getImageData(0, 0, target.width, target.height);
      const factor = transform.brightness / 100;
      for (let index = 0; index < pixels.data.length; index += 4) {
        pixels.data[index] *= factor;
        pixels.data[index + 1] *= factor;
        pixels.data[index + 2] *= factor;
      }
      context.putImageData(pixels, 0, 0);
    }
  }
  function drawPreview() {
    if (!bitmap) return;
    $('preview-image').hidden = true;
    $('preview-empty').hidden = true;
    canvas.hidden = false;
    draw(canvas, 600);
    $('preview-tag').textContent = draftFile || editChanged ? 'Unsaved preview' : 'Current image';
  }
  function changed() {
    editChanged = true;
    urlChanged = false;
    $('url').value = selected?.source === 'linked' ? selected.imageUrl : '';
    editorStatus('');
    drawPreview();
    updateButtons();
  }
  async function saveImage(next = false, remove = false) {
    if (busy || imageBusy || !selected) return;
    const product = selected;
    const nextTab = ['details', 'pricing'].includes(activeTab) ? activeTab : 'upload';
    if (attributesDirty) {
      clearFieldErrors();
      const invalid = attributeInputs.find(input => !input.checkValidity());
      if (invalid) {
        setTab(invalid.closest('[role=tabpanel]').id.replace('iw-panel-', ''));
        invalid.reportValidity();
        return;
      }
    }
    if (remove && !window.confirm(`Remove the image for ${product.simpleName || product.name}?`)) return;
    const body = new FormData();
    body.set('version', product.updatedAt);
    if (attributesDirty) body.set('attributes', JSON.stringify(attributes()));
    let action = remove ? 'remove' : urlChanged ? 'url' : (draftFile || editChanged) ? 'upload' : 'keep';
    body.set('action', action);
    if (action === 'url') {
      const value = $('url').value.trim();
      let valid = false;
      try { valid = ['http:', 'https:'].includes(new URL(value).protocol); } catch { /* validate below */ }
      if (!valid || value.length > 200) { editorStatus('Enter a valid HTTP or HTTPS image URL (up to 200 characters).'); $('url').focus(); return; }
      body.set('image_url', value);
    }
    busy = true;
    editorStatus('Saving changes…', false);
    updateButtons();
    // Prefer the next visible product; a missing-image filter may remove this one after saving.
    const index = products.findIndex(item => item.id === product.id);
    const nextIds = products.slice(index + 1).map(item => item.id);
    const previousIds = new Set(products.map(item => item.id));
    const previousPage = page;
    try {
      if (action === 'upload') {
        if (!bitmap) throw new Error('Choose an image first.');
        const output = document.createElement('canvas');
        draw(output, 1600);
        const blob = await new Promise(resolve => output.toBlob(resolve, 'image/jpeg', 0.85));
        if (!blob) throw new Error('Could not prepare the image. Try choosing the photo again.');
        body.set('image', blob, `${product.sku.replace(/[^a-z0-9_-]/gi, '_')}.jpg`);
      }
      const url = root.dataset.updateUrl.replace('00000000-0000-0000-0000-000000000000', product.id);
      const response = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf }, body });
      const data = await responseData(response);
      selected = data.product;
      const excluded = !matchesView(data.product);
      // Once saved, a catalogue refresh failure must not leave an unsaved editor.
      editChanged = urlChanged = false;
      attributesDirty = false;
      draftFile = null;
      const loaded = await loadProducts();
      busy = false;
      dialog.close();
      clearDraft();
      selected = null;
      const message = `${data.product.simpleName || data.product.name}: ${remove ? 'image removed; changes saved' : 'changes saved'}.`;
      if (loaded) notice(message);
      else notice(`${message} Refresh to reload the catalogue.`, true);
      if (next && loaded) {
        const candidate = nextIds.map(id => products.find(item => item.id === id)).find(Boolean)
          || (excluded && page === previousPage ? products.find(item => !previousIds.has(item.id)) : null);
        if (candidate) openEditor(candidate, nextTab);
        else if (page < pages) {
          page++;
          if (await loadProducts() && products[0]) openEditor(products[0], nextTab);
        } else notice('Changes saved. You have reached the end of this view.');
      }
    } catch (error) {
      busy = false;
      updateButtons();
      showFieldErrors(error.fields);
      editorStatus(error.message);
    } finally {
      busy = false;
      updateButtons();
    }
  }

  function matchesView(product) {
    for (const select of filters) {
      const key = select.dataset.filter, value = select.value;
      if (!value) continue;
      if (['company', 'brand', 'category', 'unit'].includes(key) && product[key] !== value) return false;
      if (['active', 'regular'].includes(key) && product[key] !== (value === 'yes')) return false;
      if (key === 'image' && ((value === 'present' && product.source === 'missing')
        || (value !== 'present' && value !== product.source))) return false;
    }
    const haystack = [product.name, product.simpleName, product.sku, product.company, product.brand, product.category, product.packing].join(' ').toLowerCase();
    return $('search').value.trim().toLowerCase().split(/\s+/).every(word => haystack.includes(word));
  }

  attributeInputs.forEach(input => {
    input.id = `iw-attribute-${input.dataset.attribute}`;
    const error = element('span', 'iw-field-error');
    error.id = `${input.id}-error`;
    input.setAttribute('aria-describedby', error.id);
    input.parentElement.append(error);
    const update = () => {
      if (input.dataset.attribute === 'hsn') {
        const master = (lookups.hsn || []).find(hsn => String(hsn.id) === input.value);
        attributeInput('hsn_code').readOnly = Boolean(master);
        if (master) {
          attributeInput('hsn_code').value = master.code;
          attributeInput('gst_rate').value = master.default_gst_rate;
        }
      }
      attributesDirty = JSON.stringify(attributes()) !== originalAttributes;
      input.removeAttribute('aria-invalid');
      error.textContent = '';
      updatePricePreview();
      updateButtons();
    };
    input.addEventListener('input', update);
    input.addEventListener('change', update);
  });

  $('search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    // Cancel a previous query immediately, before the debounce starts another.
    controller?.abort();
    searchTimer = setTimeout(() => { page = 1; notice(''); void loadProducts(); }, 220);
  });
  filters.forEach(select => select.addEventListener('change', () => {
    clearTimeout(searchTimer);
    if (select.dataset.filter === 'company') filters.find(filter => filter.dataset.filter === 'brand').value = '';
    page = 1;
    notice('');
    void loadProducts();
  }));
  $('sort').addEventListener('change', () => { page = 1; void loadProducts(); });
  $('refresh').addEventListener('click', () => { notice(''); void loadProducts(); });
  $('prev').addEventListener('click', () => { if (!loading && page > 1) { page--; void loadProducts(); } });
  $('next').addEventListener('click', () => { if (!loading && page < pages) { page++; void loadProducts(); } });
  $('reset').addEventListener('click', resetFilters);
  $('empty-reset').addEventListener('click', resetFilters);
  $('filter-toggle').addEventListener('click', () => {
    const expanded = $('filters').classList.toggle('open');
    $('filter-toggle').setAttribute('aria-expanded', String(expanded));
  });
  window.addEventListener('popstate', () => { readLocation(); void loadProducts(); });
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => setTab(tab.dataset.tab));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const target = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[target].focus();
      setTab(tabs[target].dataset.tab);
    });
  });
  $('close').addEventListener('click', closeEditor);
  $('cancel').addEventListener('click', closeEditor);
  dialog.addEventListener('cancel', event => { event.preventDefault(); closeEditor(); });
  $('camera').addEventListener('click', () => pickFile(true));
  $('choose').addEventListener('click', () => pickFile());
  $('dropzone').addEventListener('click', () => pickFile());
  $('file').addEventListener('change', event => { void acceptFile(event.target.files[0]); });
  $('dropzone').addEventListener('dragover', event => { event.preventDefault(); $('dropzone').classList.add('dragging'); });
  $('dropzone').addEventListener('dragleave', () => $('dropzone').classList.remove('dragging'));
  $('dropzone').addEventListener('drop', event => {
    event.preventDefault();
    $('dropzone').classList.remove('dragging');
    void acceptFile(event.dataTransfer.files[0]);
  });
  document.addEventListener('paste', event => {
    if (!dialog.open || busy || imageBusy || !['upload', 'edit'].includes(activeTab)) return;
    const file = [...(event.clipboardData?.items || [])].find(item => item.type.startsWith('image/'))?.getAsFile();
    if (file) { event.preventDefault(); void acceptFile(file); }
  });
  $('preview-image').addEventListener('error', () => {
    if (!dialog.open) return;
    $('preview-image').hidden = true;
    $('preview-empty').hidden = false;
    $('preview-empty').textContent = 'Image unavailable';
    if (activeTab === 'url') editorStatus('The preview could not load. Check that this is a direct image URL.');
  });
  $('preview-image').addEventListener('load', () => {
    if (activeTab === 'url' || (!bitmap && activeTab === 'upload')) {
      $('preview-image').hidden = false;
      $('preview-empty').hidden = true;
    }
  });
  $('url').addEventListener('input', () => { urlChanged = true; editorStatus(''); updateButtons(); });
  $('url-preview').addEventListener('click', () => {
    const source = $('url').value.trim();
    try {
      if (!['http:', 'https:'].includes(new URL(source).protocol)) throw new Error();
      previewImage(source, 'URL preview');
    } catch { editorStatus('Enter a valid HTTP or HTTPS image URL.'); }
  });
  $('crop').addEventListener('change', () => { transform.crop = $('crop').value; transform.x = transform.y = 0; changed(); });
  $('zoom').addEventListener('input', () => { transform.zoom = Number($('zoom').value); $('zoom-value').textContent = `${transform.zoom}×`; changed(); });
  $('brightness').addEventListener('input', () => { transform.brightness = Number($('brightness').value); $('brightness-value').textContent = `${transform.brightness}%`; changed(); });
  function rotate(degrees) {
    transform.rotation = (transform.rotation + degrees + 360) % 360;
    transform.x = transform.y = 0;
    changed();
  }
  $('rotate-left').addEventListener('click', () => rotate(-90));
  $('rotate-right').addEventListener('click', () => rotate(90));
  $('flip').addEventListener('click', () => { transform.flip = !transform.flip; $('flip').setAttribute('aria-pressed', String(transform.flip)); changed(); });
  $('edit-reset').addEventListener('click', () => { resetTransform(); editChanged = false; drawPreview(); updateButtons(); });
  let drag = null;
  canvas.addEventListener('pointerdown', event => {
    if (!bitmap || busy || imageBusy) return;
    drag = { x: event.clientX, y: event.clientY, offsetX: transform.x, offsetY: transform.y };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if (!drag || !bitmap || busy) return;
    const shape = geometry(), bounds = canvas.getBoundingClientRect();
    transform.x = drag.offsetX - (event.clientX - drag.x) * shape.cropWidth / bounds.width;
    transform.y = drag.offsetY - (event.clientY - drag.y) * shape.cropHeight / bounds.height;
    changed();
  });
  canvas.addEventListener('pointerup', () => { drag = null; });
  canvas.addEventListener('pointercancel', () => { drag = null; });
  $('save').addEventListener('click', () => { void saveImage(); });
  $('save-next').addEventListener('click', () => { void saveImage(true); });
  $('remove').addEventListener('click', () => { void saveImage(false, true); });
  document.addEventListener('keydown', event => {
    const input = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '');
    if (event.key === '/' && !input && !dialog.open) { event.preventDefault(); $('search').focus(); }
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && dialog.open && !busy && !imageBusy && dirty()) {
      event.preventDefault();
      void saveImage(true);
    }
  });
  window.addEventListener('beforeunload', event => { if (dialog.open && dirty()) { event.preventDefault(); event.returnValue = ''; } });
  readLocation();
  void loadProducts();
})();
