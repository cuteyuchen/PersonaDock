(() => {
  'use strict';

  const dialogRoot = document.getElementById('dialog-root');
  const toastRegion = document.getElementById('toast-region');
  let pendingAdoption = null;
  let busy = false;

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function token() {
    return sessionStorage.getItem('personadock.web.token') || '';
  }

  function headers(extra = {}) {
    const value = token();
    return value ? { ...extra, Authorization: `Bearer ${value}` } : extra;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: headers(options.headers || {}) });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const value = await response.json();
        detail = typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail || value);
      } catch (_) {
        // Keep HTTP status.
      }
      throw new Error(detail);
    }
    return response.json();
  }

  function toast(message, type = 'info') {
    const item = document.createElement('div');
    item.className = `toast ${type === 'error' ? 'error' : ''}`;
    item.textContent = message;
    toastRegion.appendChild(item);
    window.setTimeout(() => item.remove(), 4200);
  }

  function showDialog(title, body, footer) {
    dialogRoot.innerHTML = `
      <div class="dialog-backdrop">
        <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="phase2-dialog-title">
          <header class="dialog-header">
            <h2 id="phase2-dialog-title">${escapeHtml(title)}</h2>
            <button class="icon-button" data-action="dialog-close" type="button" aria-label="关闭">×</button>
          </header>
          <div class="dialog-body">${body}</div>
          <footer class="dialog-footer">${footer}</footer>
        </section>
      </div>`;
    dialogRoot.querySelector('input, select, textarea, button')?.focus();
  }

  function closeDialog() {
    dialogRoot.innerHTML = '';
    pendingAdoption = null;
  }

  function setBusy(value) {
    busy = value;
    document.querySelectorAll('[data-phase2-submit]').forEach((button) => {
      button.disabled = value;
    });
  }

  function refreshCurrentPage() {
    document.getElementById('refresh-button')?.click();
  }

  async function showCreatePersona() {
    const roots = await api('/api/v1/persona-roots');
    showDialog(
      '新建 Persona',
      `<div class="form-grid">
        <div class="field"><label for="persona-create-id">Persona ID</label><input class="input" id="persona-create-id" autocomplete="off" placeholder="xiaoyou"><div class="field-help">仅使用小写字母、数字和连字符。</div></div>
        <div class="field"><label for="persona-create-name">显示名称</label><input class="input" id="persona-create-name" autocomplete="off" placeholder="小柚"></div>
        <div class="field"><label for="persona-create-locale">语言</label><select class="select" id="persona-create-locale"><option value="zh-CN">简体中文</option><option value="zh-TW">繁體中文</option><option value="en-US">English</option><option value="ja-JP">日本語</option></select></div>
        <div class="field"><label for="persona-create-folder">工程文件夹</label><input class="input" id="persona-create-folder" autocomplete="off" placeholder="默认与 Persona ID 相同"><div class="field-help">相对于 ${escapeHtml(roots.default_root)}</div></div>
      </div>
      <div class="notice" style="margin-top:14px">将创建 Canonical Persona v3 工程并自动注册。网页不能写入配置根目录之外的位置。</div>`,
      '<button class="button" data-action="dialog-close" type="button">取消</button><button class="button primary" data-action="persona-create-submit" data-phase2-submit type="button">创建人格</button>',
    );
  }

  async function submitCreatePersona() {
    const id = document.getElementById('persona-create-id')?.value.trim();
    const name = document.getElementById('persona-create-name')?.value.trim();
    const locale = document.getElementById('persona-create-locale')?.value || 'zh-CN';
    const folder = document.getElementById('persona-create-folder')?.value.trim() || null;
    if (!id || !name) throw new Error('Persona ID 和显示名称不能为空');
    setBusy(true);
    try {
      const result = await api('/api/v1/personas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, name, locale, folder }),
      });
      closeDialog();
      toast(`已创建 Persona：${result.persona.name}`);
      location.hash = `#/personas/${encodeURIComponent(result.persona.id)}`;
    } finally {
      setBusy(false);
    }
  }

  async function showRegisterPersona() {
    const roots = await api('/api/v1/persona-roots');
    showDialog(
      '注册现有 Persona 工程',
      `<div class="field"><label for="persona-register-path">工程路径</label><input class="input" id="persona-register-path" autocomplete="off" placeholder="${escapeHtml(roots.default_root)}/existing-persona"><div class="field-help">允许根目录：${roots.roots.map(escapeHtml).join('；')}</div></div>
       <div class="notice warning" style="margin-top:14px">注册只写入 Persona Registry，不复制或删除原工程。工程必须通过现有校验。</div>`,
      '<button class="button" data-action="dialog-close" type="button">取消</button><button class="button primary" data-action="persona-register-submit" data-phase2-submit type="button">验证并注册</button>',
    );
  }

  async function submitRegisterPersona() {
    const path = document.getElementById('persona-register-path')?.value.trim();
    if (!path) throw new Error('请输入 Persona 工程路径');
    setBusy(true);
    try {
      const result = await api('/api/v1/personas/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      closeDialog();
      toast(`已注册 Persona：${result.persona.name}`);
      location.hash = `#/personas/${encodeURIComponent(result.persona.id)}`;
    } finally {
      setBusy(false);
    }
  }

  async function discoverRuntimes() {
    if (busy) return;
    busy = true;
    try {
      const value = await api('/api/v1/runtimes/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: null }),
      });
      toast(`扫描完成：发现 ${value.result.instances?.length ?? 0} 个运行实例`);
      refreshCurrentPage();
    } finally {
      busy = false;
    }
  }

  async function previewAdoption(instanceId) {
    const preview = await api('/api/v1/adoptions/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instance_id: instanceId }),
    });
    pendingAdoption = { instance_id: instanceId };
    showDialog(
      '接管运行实例',
      `<div class="notice warning">接管前会创建快照。Memory 只进入待审核候选，不会立即成为共享记忆。</div>
       <div class="form-grid" style="margin-top:14px">
         <div class="field"><label>Adapter</label><div>${escapeHtml(preview.instance?.adapter)}</div></div>
         <div class="field"><label>平台实例</label><div class="code">${escapeHtml(preview.instance?.platform_instance_id)}</div></div>
         <div class="field"><label>Persona ID</label><div class="code">${escapeHtml(preview.persona_id)}</div></div>
         <div class="field"><label>目标工程</label><div class="code">${escapeHtml(preview.destination)}</div></div>
         <div class="field"><label>导入 Skills</label><div>${escapeHtml(preview.skills?.length ?? 0)}</div></div>
         <div class="field"><label>Memory 候选</label><div>${escapeHtml(preview.memory_documents?.length ?? 0)}</div></div>
       </div>`,
      '<button class="button" data-action="dialog-close" type="button">取消</button><button class="button primary" data-action="adopt-confirm-v1" data-phase2-submit type="button">创建快照并接管</button>',
    );
  }

  async function confirmAdoption() {
    if (!pendingAdoption) return;
    setBusy(true);
    try {
      const value = await api('/api/v1/adoptions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pendingAdoption),
      });
      const result = value.result;
      closeDialog();
      toast(`已接管为 Persona：${result.persona_id}`);
      refreshCurrentPage();
    } finally {
      setBusy(false);
    }
  }

  function enhancePersonaPage() {
    if (location.hash !== '#/personas') return;
    const create = document.querySelector('[data-action="phase-info"][data-phase="2"]');
    if (create) {
      create.dataset.action = 'persona-create';
      create.textContent = '新建人格';
      if (!document.querySelector('[data-action="persona-register"]')) {
        create.insertAdjacentHTML('beforebegin', '<button class="button" data-action="persona-register" type="button">注册现有工程</button>');
      }
    }
    const summary = document.querySelector('.page-summary');
    if (summary && summary.textContent.includes('Phase 2')) {
      summary.textContent = '新建、注册和管理 Canonical Persona；编辑、测试和导出继续使用统一详情入口。';
    }
  }

  const observer = new MutationObserver(() => enhancePersonaPage());
  observer.observe(document.getElementById('workspace'), { childList: true, subtree: true });
  window.addEventListener('hashchange', () => window.setTimeout(enhancePersonaPage, 0));

  document.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-action]');
    if (!target) return;
    const action = target.dataset.action;
    const handled = new Set([
      'persona-create', 'persona-register', 'persona-create-submit',
      'persona-register-submit', 'discover', 'adopt-preview', 'adopt-confirm-v1',
    ]);
    if (!handled.has(action)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      if (action === 'persona-create') await showCreatePersona();
      else if (action === 'persona-register') await showRegisterPersona();
      else if (action === 'persona-create-submit') await submitCreatePersona();
      else if (action === 'persona-register-submit') await submitRegisterPersona();
      else if (action === 'discover') await discoverRuntimes();
      else if (action === 'adopt-preview') await previewAdoption(target.dataset.instanceId);
      else if (action === 'adopt-confirm-v1') await confirmAdoption();
    } catch (error) {
      toast(error.message || String(error), 'error');
    }
  }, true);

  document.addEventListener('click', (event) => {
    const target = event.target.closest('[data-action="dialog-close"]');
    if (target) pendingAdoption = null;
  }, true);

  enhancePersonaPage();
})();
