/**
 * VIKMO DealerDesk — Frontend Application Logic
 * Reactive Dashboard, Order Concurrency Lifecycle, GenAI Copilot, and Demand Forecasting
 */

const API_BASE = '/api';

const AppState = {
  activeTab: 'overview',
  dealers: [],
  currentDealerId: 1,
  products: [],
  productsCount: 0,
  productPage: 1,
  productCategory: '',
  productSearch: '',
  orders: [],
  orderFilterStatus: '',
  reorderSuggestions: [],
  chatSessionId: 'session-' + Math.random().toString(36).substring(2, 9),
  chatMessages: [],
  cart: [], // items for new order modal
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', async () => {
  initTabs();
  initModals();
  initChat();
  await loadInitialData();
  startHealthCheck();
});

// --- Tab Switching ---
function initTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.tab;
      switchTab(target);
    });
  });
}

function switchTab(tabId) {
  AppState.activeTab = tabId;
  document.querySelectorAll('.nav-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-view').forEach(view => {
    view.classList.toggle('active', view.id === `view-${tabId}`);
  });

  // Lazy load data based on active tab
  if (tabId === 'products') loadProducts();
  if (tabId === 'orders') loadOrders();
  if (tabId === 'forecast') loadForecast();
  if (tabId === 'overview') loadOverviewStats();
}

// --- Data Loading ---
async function loadInitialData() {
  await Promise.all([
    loadDealers(),
    loadOverviewStats(),
    loadProducts(),
  ]);
}

async function loadDealers() {
  try {
    const res = await fetch(`${API_BASE}/dealers/?page_size=50`);
    const data = await res.json();
    AppState.dealers = data.results || [];
    renderDealerSelector();
  } catch (err) {
    showToast('Failed to load dealers: ' + err.message, 'error');
  }
}

function renderDealerSelector() {
  const select = document.getElementById('global-dealer-select');
  if (!select) return;
  select.innerHTML = AppState.dealers.map(d => 
    `<option value="${d.id}">${d.dealer_code} — ${d.name} (${d.city})</option>`
  ).join('');

  if (AppState.dealers.length > 0) {
    AppState.currentDealerId = AppState.dealers[0].id;
    select.value = AppState.currentDealerId;
  }

  select.addEventListener('change', (e) => {
    AppState.currentDealerId = parseInt(e.target.value, 10);
    showToast(`Switched active dealer to #${AppState.currentDealerId}`, 'info');
    if (AppState.activeTab === 'orders') loadOrders();
  });
}

// --- Overview Dashboard ---
async function loadOverviewStats() {
  try {
    const [prodRes, dealersRes, reorderRes] = await Promise.all([
      fetch(`${API_BASE}/products/?page_size=1`),
      fetch(`${API_BASE}/dealers/?page_size=1`),
      fetch(`${API_BASE}/reorder-suggestions/`),
    ]);

    const prodData = await prodRes.json();
    const dealersData = await dealersRes.json();
    const reorderData = await reorderRes.json();

    document.getElementById('kpi-total-products').textContent = prodData.count || 600;
    document.getElementById('kpi-active-dealers').textContent = dealersData.count || 25;
    
    const reorderList = reorderData.reorder_suggestions || [];
    const urgentCount = reorderList.filter(r => r.suggested_reorder_units > 0).length;
    document.getElementById('kpi-reorder-alerts').textContent = urgentCount;

    // Load recent orders count
    const ordersRes = await fetch(`${API_BASE}/orders/?page_size=10`);
    if (ordersRes.ok) {
      const ordersData = await ordersRes.json();
      document.getElementById('kpi-total-orders').textContent = ordersData.count || ordersData.results?.length || 0;
      renderRecentOrdersOverview(ordersData.results || []);
    }
  } catch (err) {
    console.error('Error loading overview:', err);
  }
}

function renderRecentOrdersOverview(orders) {
  const container = document.getElementById('recent-orders-tbody');
  if (!container) return;
  if (!orders || orders.length === 0) {
    container.innerHTML = '<tr><td colspan="6" style="text-align:center; color: var(--text-muted);">No orders placed yet. Create your first draft order below!</td></tr>';
    return;
  }

  container.innerHTML = orders.slice(0, 5).map(o => `
    <tr>
      <td><span class="sku-tag">${o.order_number}</span></td>
      <td><strong>Dealer #${o.dealer}</strong></td>
      <td>${o.items?.length || 0} line items</td>
      <td><span class="price-display">₹${o.total_amount}</span></td>
      <td>${getStatusBadge(o.status)}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="viewOrderDetail('${o.order_number}')">View</button>
      </td>
    </tr>
  `).join('');
}

// --- Products & Inventory ---
async function loadProducts() {
  const search = AppState.productSearch;
  const category = AppState.productCategory;
  const page = AppState.productPage;

  let url = `${API_BASE}/products/?page=${page}&page_size=16`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (category) url += `&category=${encodeURIComponent(category)}`;

  const grid = document.getElementById('products-grid');
  grid.innerHTML = '<div style="grid-column: 1/-1; text-align:center; padding: 3rem; color: var(--text-muted);">Loading catalogue items...</div>';

  try {
    const res = await fetch(url);
    const data = await res.json();
    AppState.products = data.results || [];
    AppState.productsCount = data.count || 0;
    renderProductsGrid();
    renderProductPagination(data);
  } catch (err) {
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; color: var(--rose);">Failed to load products: ${err.message}</div>`;
  }
}

function renderProductsGrid() {
  const grid = document.getElementById('products-grid');
  if (!AppState.products.length) {
    grid.innerHTML = '<div style="grid-column: 1/-1; text-align:center; padding: 3rem; color: var(--text-muted);">No products match your criteria.</div>';
    return;
  }

  grid.innerHTML = AppState.products.map(p => {
    let stockClass = 'stock-high';
    if (p.stock === 0) stockClass = 'stock-low';
    else if (p.stock < 25) stockClass = 'stock-medium';

    return `
      <div class="product-card" id="card-sku-${p.sku}">
        <div>
          <div class="card-top">
            <span class="sku-tag">${p.sku}</span>
            <span class="stock-pill ${stockClass}">${p.stock} in stock</span>
          </div>
          <div class="product-name">${p.name}</div>
          <div class="fitment-tag">${p.vehicle_fitment || 'Universal'}</div>
          <div style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.5rem;">
            Brand: <strong>${p.brand}</strong> • Category: <strong>${p.category}</strong>
          </div>
        </div>
        <div class="product-meta-row">
          <div>
            <div style="font-size: 0.7rem; color: var(--text-faint); text-transform: uppercase;">Unit Price</div>
            <div class="price-display" style="font-size: 1.15rem; color: #38bdf8;">₹${p.price}</div>
          </div>
          <div style="display:flex; gap: 0.4rem;">
            <button class="btn btn-secondary btn-sm" onclick="openStockModal('${p.sku}', ${p.stock})">Adjust Stock</button>
            <button class="btn btn-primary btn-sm" onclick="quickAddToDraft('${p.sku}')">+ Add</button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function renderProductPagination(data) {
  const container = document.getElementById('product-pagination');
  if (!container) return;
  const totalPages = Math.ceil((data.count || 0) / 16);
  container.innerHTML = `
    <div style="display: flex; align-items: center; justify-content: space-between; width: 100%; margin-top: 1.5rem;">
      <span style="font-size: 0.82rem; color: var(--text-muted);">
        Showing page ${AppState.productPage} of ${totalPages} (${data.count} items)
      </span>
      <div style="display: flex; gap: 0.5rem;">
        <button class="btn btn-secondary btn-sm" ${!data.previous ? 'disabled' : ''} onclick="changeProductPage(-1)">Previous</button>
        <button class="btn btn-secondary btn-sm" ${!data.next ? 'disabled' : ''} onclick="changeProductPage(1)">Next</button>
      </div>
    </div>
  `;
}

function changeProductPage(delta) {
  AppState.productPage += delta;
  loadProducts();
}

// --- Orders Lifecycle ---
async function loadOrders() {
  const dealerId = AppState.currentDealerId;
  let url = `${API_BASE}/orders/?dealer_id=${dealerId}`;
  if (AppState.orderFilterStatus) url += `&status=${AppState.orderFilterStatus}`;

  const tbody = document.getElementById('orders-table-tbody');
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 2rem; color: var(--text-muted);">Fetching orders...</td></tr>';

  try {
    const res = await fetch(url);
    const data = await res.json();
    const orders = data.results || data || [];
    AppState.orders = orders;
    renderOrdersTable(orders);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color: var(--rose);">Failed to load orders: ${err.message}</td></tr>`;
  }
}

function renderOrdersTable(orders) {
  const tbody = document.getElementById('orders-table-tbody');
  if (!orders.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 2rem; color: var(--text-muted);">No orders found for this dealer. Click "+ Create Draft Order" above to start!</td></tr>';
    return;
  }

  tbody.innerHTML = orders.map(o => {
    let actionButtons = '';
    if (o.status === 'DRAFT') {
      actionButtons = `
        <button class="btn btn-success btn-sm" onclick="confirmOrder('${o.order_number}')">Confirm</button>
        <button class="btn btn-danger btn-sm" onclick="cancelOrder('${o.order_number}')">Cancel</button>
      `;
    } else if (o.status === 'CONFIRMED') {
      actionButtons = `
        <button class="btn btn-primary btn-sm" onclick="dispatchOrder('${o.order_number}')">Dispatch</button>
        <button class="btn btn-danger btn-sm" onclick="cancelOrder('${o.order_number}')">Cancel</button>
      `;
    } else if (o.status === 'DISPATCHED') {
      actionButtons = `
        <button class="btn btn-success btn-sm" onclick="deliverOrder('${o.order_number}')">Mark Delivered</button>
      `;
    }

    return `
      <tr>
        <td><span class="sku-tag">${o.order_number}</span></td>
        <td style="font-size: 0.8rem; color: var(--text-muted);">${new Date(o.created_at).toLocaleString()}</td>
        <td>${o.items?.length || 0} SKUs</td>
        <td><span class="price-display">₹${o.subtotal}</span></td>
        <td><span style="font-size: 0.8rem; color: var(--text-muted);">₹${o.tax_amount}</span></td>
        <td><strong class="price-display" style="color: #38bdf8;">₹${o.total_amount}</strong></td>
        <td>${getStatusBadge(o.status)}</td>
        <td style="text-align: right;">
          <div style="display: flex; gap: 0.4rem; justify-content: flex-end;">
            ${actionButtons}
            <button class="btn btn-secondary btn-sm" onclick="viewOrderDetail('${o.order_number}')">Details</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function getStatusBadge(status) {
  const map = {
    'DRAFT': 'badge-draft',
    'CONFIRMED': 'badge-confirmed',
    'DISPATCHED': 'badge-dispatched',
    'DELIVERED': 'badge-delivered',
    'CANCELLED': 'badge-cancelled'
  };
  return `<span class="badge ${map[status] || 'badge-draft'}">${status}</span>`;
}

// Order Transitions
async function confirmOrder(orderNumber) {
  if (!confirm(`Confirm order ${orderNumber}? This atomically reserves stock under database row lock.`)) return;
  try {
    const res = await fetch(`${API_BASE}/orders/${orderNumber}/confirm/`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Failed to confirm');
    showToast(`Order ${orderNumber} CONFIRMED! Stock reserved.`, 'success');
    loadOrders();
    loadOverviewStats();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function dispatchOrder(orderNumber) {
  try {
    const res = await fetch(`${API_BASE}/orders/${orderNumber}/dispatch/`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Failed to dispatch');
    showToast(`Order ${orderNumber} DISPATCHED!`, 'info');
    loadOrders();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function deliverOrder(orderNumber) {
  try {
    const res = await fetch(`${API_BASE}/orders/${orderNumber}/deliver/`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Failed to deliver');
    showToast(`Order ${orderNumber} DELIVERED to dealer!`, 'success');
    loadOrders();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function cancelOrder(orderNumber) {
  if (!confirm(`Cancel order ${orderNumber}? Stock will be restored to inventory.`)) return;
  try {
    const res = await fetch(`${API_BASE}/orders/${orderNumber}/cancel/`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Failed to cancel');
    showToast(`Order ${orderNumber} CANCELLED. Stock returned.`, 'info');
    loadOrders();
    loadOverviewStats();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// --- Modals Setup ---
function initModals() {
  document.querySelectorAll('.modal-close-trigger').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('open'));
    });
  });

  // Stock Adjustment
  document.getElementById('stock-adjust-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const sku = document.getElementById('modal-stock-sku').value;
    const qty = parseInt(document.getElementById('modal-stock-qty').value, 10);
    const reason = document.getElementById('modal-stock-reason').value;

    try {
      const res = await fetch(`${API_BASE}/inventory/${sku}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantity: qty, reason: reason })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error?.message || 'Stock update failed');
      showToast(`Stock for ${sku} updated to ${qty}!`, 'success');
      document.getElementById('stock-modal').classList.remove('open');
      loadProducts();
      loadOverviewStats();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  // New Order Modal Form
  document.getElementById('btn-open-create-order')?.addEventListener('click', () => {
    openCreateOrderModal();
  });

  document.getElementById('add-order-line-btn')?.addEventListener('click', () => {
    addOrderLineItem();
  });

  document.getElementById('create-order-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    submitNewOrder();
  });
}

function openStockModal(sku, currentStock) {
  document.getElementById('modal-stock-sku').value = sku;
  document.getElementById('modal-stock-display-sku').textContent = sku;
  document.getElementById('modal-stock-qty').value = currentStock;
  document.getElementById('stock-modal').classList.add('open');
}

function openCreateOrderModal() {
  const modal = document.getElementById('create-order-modal');
  const linesContainer = document.getElementById('order-lines-container');
  linesContainer.innerHTML = '';
  addOrderLineItem(); // add 1 initial line
  modal.classList.add('open');
}

function addOrderLineItem(defaultSku = '', defaultQty = 1) {
  const container = document.getElementById('order-lines-container');
  const lineIndex = container.children.length;
  const div = document.createElement('div');
  div.className = 'order-line-row';
  div.style = 'display: flex; gap: 0.6rem; align-items: center; margin-bottom: 0.6rem;';
  div.innerHTML = `
    <input type="text" placeholder="SKU (e.g. BRK-1044)" value="${defaultSku}" class="input-field order-sku-input" style="flex: 2; font-family: var(--font-mono); text-transform: uppercase;" required />
    <input type="number" min="1" max="999" value="${defaultQty}" class="input-field order-qty-input" style="width: 90px;" required />
    <button type="button" class="btn btn-danger btn-sm" onclick="this.parentElement.remove()">✕</button>
  `;
  container.appendChild(div);
}

function quickAddToDraft(sku) {
  openCreateOrderModal();
  const container = document.getElementById('order-lines-container');
  container.innerHTML = '';
  addOrderLineItem(sku, 2);
  showToast(`Added ${sku} to draft order builder`, 'info');
}

async function submitNewOrder() {
  const dealerId = AppState.currentDealerId;
  const rows = document.querySelectorAll('.order-line-row');
  const items = [];

  rows.forEach(r => {
    const sku = r.querySelector('.order-sku-input').value.trim().toUpperCase();
    const qty = parseInt(r.querySelector('.order-qty-input').value, 10);
    if (sku && qty > 0) {
      items.push({ sku, quantity: qty });
    }
  });

  if (!items.length) {
    showToast('Add at least one item to order', 'error');
    return;
  }

  const idempotencyKey = 'idem-' + Math.random().toString(36).substring(2, 12);

  try {
    const res = await fetch(`${API_BASE}/orders/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey
      },
      body: JSON.stringify({ dealer_id: dealerId, items: items })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Failed to create order');
    showToast(`Draft Order ${data.order_number} created successfully!`, 'success');
    document.getElementById('create-order-modal').classList.remove('open');
    loadOrders();
    loadOverviewStats();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function viewOrderDetail(orderNumber) {
  try {
    const res = await fetch(`${API_BASE}/orders/${orderNumber}/`);
    const o = await res.json();
    if (!res.ok) throw new Error(o.error?.message || 'Failed to retrieve order');

    const modal = document.getElementById('order-detail-modal');
    document.getElementById('detail-modal-order-no').textContent = o.order_number;
    document.getElementById('detail-modal-body').innerHTML = `
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.25rem;">
        <div>
          <div style="font-size: 0.75rem; color: var(--text-faint);">STATUS</div>
          <div>${getStatusBadge(o.status)}</div>
        </div>
        <div>
          <div style="font-size: 0.75rem; color: var(--text-faint);">DEALER ID</div>
          <div style="font-weight: 700;">#${o.dealer}</div>
        </div>
        <div>
          <div style="font-size: 0.75rem; color: var(--text-faint);">CREATED AT</div>
          <div style="font-size: 0.85rem;">${new Date(o.created_at).toLocaleString()}</div>
        </div>
        <div>
          <div style="font-size: 0.75rem; color: var(--text-faint);">TOTAL AMOUNT (INC 18% GST)</div>
          <div class="price-display" style="font-size: 1.2rem; color: #38bdf8;">₹${o.total_amount}</div>
        </div>
      </div>
      <h4 style="font-size: 0.88rem; font-weight: 700; margin-bottom: 0.6rem; color: var(--text-muted); text-transform: uppercase;">Line Items</h4>
      <div class="table-responsive">
        <table class="data-table">
          <thead>
            <tr>
              <th>SKU</th>
              <th>Product Name</th>
              <th>Unit Price</th>
              <th>Qty</th>
              <th>Line Tax (18%)</th>
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            ${o.items.map(it => `
              <tr>
                <td><span class="sku-tag">${it.sku}</span></td>
                <td>${it.name}</td>
                <td>₹${it.unit_price}</td>
                <td><strong>${it.quantity}</strong></td>
                <td>₹${it.line_tax}</td>
                <td><strong>₹${it.line_total}</strong></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
    modal.classList.add('open');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// --- AI Dealer Assistant (GenAI Tool-Calling Chat) ---
function initChat() {
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-input');
  if (!form || !input) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    await sendChatMessage(msg);
  });

  // Prompt chips
  document.querySelectorAll('.chip-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const text = btn.dataset.prompt;
      if (text) {
        input.value = text;
        sendChatMessage(text);
      }
    });
  });
}

async function sendChatMessage(message) {
  const chatMessages = document.getElementById('chat-messages');
  
  // Render user bubble
  appendChatBubble('user', message);

  // Render typing indicator
  const typingId = 'typing-' + Date.now();
  const typingDiv = document.createElement('div');
  typingDiv.id = typingId;
  typingDiv.className = 'message-bubble message-assistant';
  typingDiv.innerHTML = '<span style="color: var(--text-muted);">Thinking & querying database...</span>';
  chatMessages.appendChild(typingDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  try {
    const res = await fetch(`${API_BASE}/assistant/chat/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: AppState.chatSessionId,
        dealer_id: AppState.currentDealerId,
        message: message
      })
    });

    const data = await res.json();
    document.getElementById(typingId)?.remove();

    if (!res.ok) throw new Error(data.error?.message || 'Chat request failed');

    appendChatBubble('assistant', data.reply, data.tool_calls, data.cited_skus, data.actions);
    if (data.actions && data.actions.length > 0) {
      loadOrders();
      loadOverviewStats();
    }
  } catch (err) {
    document.getElementById(typingId)?.remove();
    appendChatBubble('assistant', `⚠️ Sorry, encountered an error: ${err.message}`);
  }
}

function appendChatBubble(role, text, toolCalls = [], citedSkus = [], actions = []) {
  const chatMessages = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = `message-bubble message-${role}`;

  let toolsHtml = '';
  if (toolCalls && toolCalls.length > 0) {
    toolsHtml = toolCalls.map(tc => `
      <div class="tool-call-box">
        <span style="color: #38bdf8; font-weight: bold;">⚡ Tool: ${tc.name}</span>
        <pre style="margin-top: 0.25rem; font-size: 0.72rem; overflow-x: auto;">${JSON.stringify(tc.arguments, null, 2)}</pre>
      </div>
    `).join('');
  }

  let citedHtml = '';
  if (citedSkus && citedSkus.length > 0) {
    citedHtml = `
      <div style="font-size: 0.72rem; color: var(--text-faint); margin-top: 0.5rem; font-weight: 700;">VERIFIED CITED SKUs:</div>
      <div class="cited-skus-container">
        ${citedSkus.map(s => `<button class="sku-tag" style="cursor: pointer;" onclick="quickAddToDraft('${s}')">+ Draft ${s}</button>`).join('')}
      </div>
    `;
  }

  let actionsHtml = '';
  if (actions && actions.length > 0) {
    actionsHtml = actions.map(act => `
      <div style="margin-top: 0.6rem; padding: 0.5rem 0.75rem; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: var(--radius-sm); font-size: 0.8rem; color: #34d399;">
        ✓ Action Executed: <strong>${act.type}</strong> (${act.order_number || ''})
      </div>
    `).join('');
  }

  div.innerHTML = `
    <div>${escapeHtml(text)}</div>
    ${toolsHtml}
    ${citedHtml}
    ${actionsHtml}
  `;

  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// --- Demand Forecasting & Reorder Engine ---
async function loadForecast() {
  const tbody = document.getElementById('forecast-table-tbody');
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 2rem; color: var(--text-muted);">Calculating rolling demand forecasts & safety stock...</td></tr>';

  try {
    const res = await fetch(`${API_BASE}/reorder-suggestions/`);
    const data = await res.json();
    const suggestions = data.reorder_suggestions || [];
    AppState.reorderSuggestions = suggestions;
    renderForecastTable(suggestions);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color: var(--rose);">Failed to load forecast: ${err.message}</td></tr>`;
  }
}

function renderForecastTable(suggestions) {
  const tbody = document.getElementById('forecast-table-tbody');
  if (!suggestions.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 2rem; color: var(--text-muted);">No forecast data available.</td></tr>';
    return;
  }

  tbody.innerHTML = suggestions.map(s => {
    let urgencyBadge = '<span class="badge badge-delivered">Sufficient</span>';
    if (s.suggested_reorder_units > 50) {
      urgencyBadge = '<span class="badge badge-cancelled">Critical Urgency</span>';
    } else if (s.suggested_reorder_units > 0) {
      urgencyBadge = '<span class="badge badge-dispatched">Reorder Needed</span>';
    }

    return `
      <tr>
        <td><span class="sku-tag">${s.sku}</span></td>
        <td><strong>${s.current_stock}</strong> units</td>
        <td>${s.projected_4week_demand} units</td>
        <td>${s.safety_stock} units</td>
        <td>
          <strong style="color: ${s.suggested_reorder_units > 0 ? '#f43f5e' : '#10b981'}; font-size: 1rem;">
            ${s.suggested_reorder_units}
          </strong>
        </td>
        <td>${urgencyBadge}</td>
        <td style="text-align: right;">
          <button class="btn btn-secondary btn-sm" onclick="showSkuForecastChart('${s.sku}')">Forecast Breakdown</button>
        </td>
      </tr>
    `;
  }).join('');
}

async function showSkuForecastChart(sku) {
  try {
    const res = await fetch(`${API_BASE}/forecast/${sku}/`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Forecast not found');

    const modal = document.getElementById('order-detail-modal');
    document.getElementById('detail-modal-order-no').textContent = `Demand Forecast: ${sku}`;
    
    const weeks = data.forecast || [];
    const maxVal = Math.max(...weeks.map(w => w.forecast_units || 0), 10);

    const barsHtml = weeks.map(w => {
      const pct = Math.round(((w.forecast_units || 0) / maxVal) * 100);
      return `
        <div class="forecast-bar-row">
          <div class="forecast-week-label">Week of ${w.week_start}</div>
          <div class="forecast-bar-track">
            <div class="forecast-bar-fill" style="width: ${pct}%;"></div>
          </div>
          <div class="forecast-val">${w.forecast_units}</div>
        </div>
      `;
    }).join('');

    document.getElementById('detail-modal-body').innerHTML = `
      <div style="margin-bottom: 1.5rem;">
        <h4 style="font-size: 0.95rem; font-weight: 700; margin-bottom: 0.4rem;">4-Week Rolling Demand Prediction</h4>
        <p style="font-size: 0.8rem; color: var(--text-muted);">
          Trained on historical dealer ordering trends without future leakage, capturing Diwali surge and regional lift.
        </p>
      </div>
      <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 1.25rem;">
        ${barsHtml}
      </div>
    `;
    modal.classList.add('open');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// --- Supplier Synchronization Station ---
async function triggerSupplierSync() {
  const btn = document.getElementById('trigger-sync-btn');
  const logDiv = document.getElementById('sync-terminal-log');
  btn.disabled = true;
  btn.textContent = 'Synchronizing...';

  logDiv.innerHTML += `\n[${new Date().toLocaleTimeString()}] Initiating Supplier Sync request against external catalogue...\n`;
  logDiv.scrollTop = logDiv.scrollHeight;

  try {
    const res = await fetch(`${API_BASE}/sync/supplier/`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Sync failed');

    logDiv.innerHTML += `[${new Date().toLocaleTimeString()}] Sync Completed:\n`;
    logDiv.innerHTML += `  - Items Created: ${data.created}\n`;
    logDiv.innerHTML += `  - Items Updated: ${data.updated}\n`;
    logDiv.innerHTML += `  - Items Unchanged: ${data.unchanged}\n`;
    logDiv.innerHTML += `  - Items Rejected: ${data.rejected}\n`;
    logDiv.innerHTML += `  - Supplier Pages Consumed: ${data.pages}\n`;
    logDiv.innerHTML += `  - Total HTTP Requests: ${data.requests}\n`;
    logDiv.scrollTop = logDiv.scrollHeight;

    showToast(`Supplier catalogue sync complete! Created: ${data.created}, Updated: ${data.updated}`, 'success');
    loadProducts();
    loadOverviewStats();
  } catch (err) {
    logDiv.innerHTML += `[${new Date().toLocaleTimeString()}] ERROR: ${err.message}\n`;
    logDiv.scrollTop = logDiv.scrollHeight;
    showToast('Sync error: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Trigger Live Sync';
  }
}

// --- Toast Feedback System ---
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <div style="font-size: 0.88rem; flex: 1;">${escapeHtml(message)}</div>
    <button style="background:none; border:none; color:var(--text-faint); cursor:pointer;" onclick="this.parentElement.remove()">✕</button>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(40px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4500);
}

// --- System Health Check ---
function startHealthCheck() {
  setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/health/`);
      const badge = document.getElementById('system-health-badge');
      if (res.ok) {
        badge.innerHTML = '<span class="status-dot"></span> PostgreSQL & APIs Online';
      } else {
        badge.innerHTML = '<span class="status-dot" style="background:#f43f5e; box-shadow:0 0 10px #f43f5e;"></span> System Degraded';
      }
    } catch {
      const badge = document.getElementById('system-health-badge');
      if (badge) badge.innerHTML = '<span class="status-dot" style="background:#f43f5e;"></span> Offline';
    }
  }, 30000);
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
