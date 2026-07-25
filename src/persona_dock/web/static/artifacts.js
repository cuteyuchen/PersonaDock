(() => {
  'use strict';

  const workspace = document.getElementById('workspace');
  const dialogRoot = document.getElementById('dialog-root');
  const toastRegion = document.getElementById('toast-region');
  let rendering = false;

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function attr(value) { return escapeHtml(value); }
  function token() { return sessionStorage.getItem('personadock.web.token') || ''; }
  function headers(extra = {}) {
    const value = token();
    return value ? { ...extra, Authorization: `Bearer ${value}` } : extra;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: headers(options.headers || {}) });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json();
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body);
      } catch (_) {
        // Keep status text.
      }
      throw new Error(detail);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function toast(message, type = 'info') {
    const item = document.createElement('div');
    item.className = `toast ${type === 'error' ? 'error' : ''}`;
    item.textContent = message;
    toastRegion.appendChild(item);
    window.setTimeout(() => item.remove(), 4500);
  }

  function pageHeader(kicker, title, summary, actions = '') {
    return `<header class="page-header"><div><div class="page-kicker">${escapeHtml(kicker)}</div><h1>${escapeHtml(title)}</h1><p class="page-summary">${escapeHtml(summary)}</p></div>${actions ? `<div class="actions">${actions}</div>` : ''}</header>`;
  }

  function statusBadge(status, label = null) {
    return `<span class="status ${attr(status)}">${escapeHtml(label || status)}</span>`;
  }

  function emptyState(title, text) {
    return `<div class="empty-state"><strong>${escapeHtml(title)}</strong>${escapeHtml(text)}</div>`;
  }

  function formatSize(value) {
    const bytes = Number(value) || 0;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
  }

  function formatDate(value) {
    if (!value) return '—';
    const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(date);
  }

  function setPageTitle(value) {
    document.getElementById('route-title').textContent = value;
    document.title = `${value} · PersonaDock`;
  }

  function route() {
    const raw = location.hash.replace(/^#\/?/, '');
    const [path, query = ''] = raw.split('?');
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    return { root: parts[0] || 'overview', parts, query: new URLSearchParams(query) };
  }

  function personaOptions(personas, selected = '') {
    return personas.map((item) => `<option value="${attr(item.id)}" ${item.id === selected ? 'selected' : ''}>${escapeHtml(item.name)} (${escapeHtml(item.id)})</option>`).join('');
  }

  function artifactOptions(items, suffix = '') {
    const filtered = suffix ? items.filter((item) => item.name.endsWith(suffix)) : items;
    return filtered.map((item) => `<option value="${attr(item.path)}">${escapeHtml(item.name)}</option>`).join('');
  }

  function showDialog(title, body, footer = '') {
    dialogRoot.innerHTML = `<div class="dialog-backdrop"><section class="dialog" role="dialog" aria-modal="true"><header class="dialog-header"><h2>${escapeHtml(title)}</h2><button class="icon-button" data-artifact-action="dialog-close" type="button">×</button></header><div class="dialog-body">${body}</div>${footer ? `<footer class="dialog-footer">${footer}</footer>` : ''}</section></div>`;
  }

  function closeDialog() { dialogRoot.innerHTML = ''; }

  function resultRows(value) {
    if (value === null || value === undefined) return '<div class="result-row"><strong>结果</strong><div>—</div></div>';
    if (typeof value !== 'object') return `<div class="result-row"><strong>结果</strong><div>${escapeHtml(value)}</div></div>`;
    return Object.entries(value).map(([key, item]) => `<div class="result-row"><strong>${escapeHtml(key)}</strong><div>${typeof item === 'object' ? `<pre class="mono-box" style="max-height:180px">${escapeHtml(JSON.stringify(item, null, 2))}</pre>` : escapeHtml(item)}</div></div>`).join('');
  }

  function showResult(title, value) {
    showDialog(title, `<div class="result-box">${resultRows(value)}</div>`, '<button class="button primary" data-artifact-action="dialog-close" type="button">关闭</button>');
  }

  async function fileBase64(file) {
    if (!file) throw new Error('请选择文件');
    if (file.size > 16 * 1024 * 1024) throw new Error('文件不能超过 16 MiB');
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    const step = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += step) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + step));
    }
    return btoa(binary);
  }

  async function uploadFrom(inputId) {
    const file = document.getElementById(inputId)?.files?.[0];
    if (!file) throw new Error('请选择文件');
    return api('/api/v1/uploads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: file.name, content_base64: await fileBase64(file) }),
    });
  }

  async function downloadArtifact(path) {
    const response = await fetch(`/api/v1/artifacts/download?path=${encodeURIComponent(path)}`, { headers: headers() });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = path.split(/[\\/]/).pop() || 'artifact';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function selectedTargets(prefix) {
    const values = [...document.querySelectorAll(`[data-target-group="${prefix}"]:checked`)].map((item) => item.value);
    return values.length ? values : null;
  }

  function artifactTable(items, emptyText) {
    if (!items.length) return emptyState('暂无文件', emptyText);
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>文件</th><th>大小</th><th>修改时间</th><th></th></tr></thead><tbody>${items.map((item) => `<tr><td><strong>${escapeHtml(item.name)}</strong><div class="list-meta artifact-path" title="${attr(item.path)}">${escapeHtml(item.path)}</div></td><td>${formatSize(item.size)}</td><td>${formatDate(item.modified_at)}</td><td><button class="button small" data-artifact-action="download" data-path="${attr(item.path)}" type="button">下载</button></td></tr>`).join('')}</tbody></table></div>`;
  }

  function enhancePersonaDetail() {
    const current = route();
    if (current.root !== 'personas' || !current.parts[1] || current.parts[2]) return;
    const id = current.parts[1];
    const panel = [...document.querySelectorAll('.panel-header h2')].find((item) => item.textContent === '可用操作')?.closest('.panel');
    const links = panel?.querySelector('.legacy-links');
    if (links && !links.querySelector('[data-phase4-link]')) {
      links.insertAdjacentHTML('afterbegin', `<a class="legacy-link" data-phase4-link href="#/packages?persona=${encodeURIComponent(id)}">构建、打包与签名</a><a class="legacy-link" data-phase4-link href="#/backups?persona=${encodeURIComponent(id)}">加密备份</a><a class="legacy-link" data-phase4-link href="#/character-cards?persona=${encodeURIComponent(id)}">Character Card</a>`);
    }
  }

  async function renderPackages() {
    const selected = route().query.get('persona') || '';
    const [personas, exportsResult, keysResult] = await Promise.all([
      api('/api/personas'),
      api('/api/v1/artifacts?category=exports'),
      api('/api/v1/trust/keys'),
    ]);
    setPageTitle('PersonaPack 与信任');
    const exports = exportsResult.items || [];
    const packages = exports.filter((item) => item.name.endsWith('.personapack'));
    const signatures = exports.filter((item) => item.name.endsWith('.sig.json'));
    const keys = keysResult.items || [];
    workspace.innerHTML = `<div data-artifact-view="packages">
      ${pageHeader('Build & Trust', 'PersonaPack 与信任', '构建、打包、检查和签名均使用确定性 PersonaPack 实现。私钥只保存在本机 Key Store。')}
      <div class="tool-layout"><div class="tool-sections">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>从 Persona 生成</h2><p>Build、PersonaPack 和公开工程</p></div></header><div class="panel-body"><div class="form-grid"><div class="field"><label>Persona</label><select class="select" id="package-persona">${personaOptions(personas, selected)}</select></div><div class="field"><label>目标</label><div class="check-row"><label><input type="checkbox" value="hermes" data-target-group="package" checked>Hermes</label><label><input type="checkbox" value="openclaw" data-target-group="package" checked>OpenClaw</label><label><input type="checkbox" value="generic" data-target-group="package">Generic</label></div></div></div><div class="operation-grid" style="margin-top:14px"><div class="operation-cell"><h3>Build</h3><p>编译目标文件并生成可下载归档。</p><button class="button" data-artifact-action="build" type="button">开始构建</button></div><div class="operation-cell"><h3>PersonaPack</h3><p>生成可验证、可签名的确定性包。</p><button class="button primary" data-artifact-action="pack" type="button">创建 PersonaPack</button></div><div class="operation-cell"><h3>公开工程</h3><p>移除 Memory 与私有目录后导出。</p><button class="button" data-artifact-action="public-export" type="button">导出公开工程</button></div></div></div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>检查外部 PersonaPack</h2><p>上传文件仅进入受控 Upload Store</p></div></header><div class="panel-body"><input class="file-input" id="package-upload" type="file" accept=".personapack,.zip"><div class="form-actions"><button class="button primary" data-artifact-action="inspect-package" type="button">上传并检查</button></div></div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>导出文件</h2><p>PersonaDock 管理的 Export Store</p></div><span class="status">${exports.length}</span></header><div class="panel-body flush">${artifactTable(exports, '构建或打包后会出现在这里。')}</div></section>
      </div><aside class="tool-sidebar">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>签名密钥</h2><p>Ed25519，私钥不可下载</p></div><span class="status">${keys.length}</span></header><div class="panel-body"><div class="inline-form"><div class="field"><label for="key-name">密钥名称</label><input class="input" id="key-name" placeholder="release-signing"></div><button class="button" data-artifact-action="create-key" type="button">生成</button></div><div class="list" style="margin:12px -14px -14px">${keys.length ? keys.map((key) => `<div class="list-row"><div class="list-primary"><div class="list-title">${escapeHtml(key.name)}</div><span class="key-fingerprint" title="${attr(key.key_id)}">${escapeHtml(key.key_id)}</span></div>${key.private_key_available ? statusBadge('ready', '可签名') : statusBadge('failed', '缺私钥')}</div>`).join('') : emptyState('尚无签名密钥', '生成后只允许下载公钥。')}</div></div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>签名与验证</h2><p>显式选择本地信任 Key</p></div></header><div class="panel-body compact-form"><div class="field"><label>PersonaPack</label><select class="select" id="trust-package"><option value="">选择包</option>${artifactOptions(packages)}</select></div><div class="field"><label>签名密钥</label><select class="select" id="trust-key"><option value="">选择 Key</option>${keys.map((key) => `<option value="${attr(key.key_id)}">${escapeHtml(key.name)}</option>`).join('')}</select></div><button class="button primary" data-artifact-action="sign-package" type="button">创建分离式签名</button><div class="field"><label>签名文件</label><select class="select" id="trust-signature"><option value="">自动查找或无签名</option>${artifactOptions(signatures)}</select></div><button class="button" data-artifact-action="verify-package" type="button">验证完整性与信任</button><div class="security-note"><strong>信任边界</strong><span>包内携带的公钥不会自动获得信任；Web 只信任本地 Key Store 中的显式公钥。</span></div></div></section>
      </aside></div>
    </div>`;
  }

  async function renderBackups() {
    const selected = route().query.get('persona') || '';
    const [personas, backupsResult] = await Promise.all([
      api('/api/personas'),
      api('/api/v1/artifacts?category=backups'),
    ]);
    const backups = backupsResult.items || [];
    setPageTitle('备份');
    workspace.innerHTML = `<div data-artifact-view="backups">
      ${pageHeader('Private Backup', '加密私有备份', '备份使用 Scrypt + AES-256-GCM。密码只存在于本次请求内，不写入 Job、日志或控制面数据库。')}
      <div class="tool-layout"><div class="tool-sections"><section class="panel"><header class="panel-header"><div class="panel-title"><h2>创建备份</h2><p>包含 Persona 私有工程，不扫描 Runtime Auth 或 Session</p></div></header><div class="panel-body"><div class="form-grid"><div class="field"><label>Persona</label><select class="select" id="backup-persona">${personaOptions(personas, selected)}</select></div><div class="field"><label>备份密码</label><input class="input" id="backup-password" type="password" autocomplete="new-password" placeholder="至少 8 个字符"></div></div><div class="form-actions"><button class="button primary" data-artifact-action="create-backup" type="button">创建加密备份</button></div></div></section><section class="panel"><header class="panel-header"><div class="panel-title"><h2>已有备份</h2><p>Backup Store</p></div><span class="status">${backups.length}</span></header><div class="panel-body flush">${artifactTable(backups, '创建或上传备份后会显示。')}</div></section></div><aside class="tool-sidebar"><section class="panel"><header class="panel-header"><div class="panel-title"><h2>检查与恢复</h2><p>恢复到新文件夹，不静默覆盖</p></div></header><div class="panel-body compact-form"><input class="file-input" id="backup-upload" type="file" accept=".pdbackup"><button class="button" data-artifact-action="inspect-backup" type="button">上传并检查</button><div class="field"><label>恢复文件夹</label><input class="input" id="backup-folder" placeholder="xiaoyou-restored"><div class="field-help">相对于配置的人格根目录</div></div><div class="field"><label>备份密码</label><input class="input" id="backup-restore-password" type="password" autocomplete="off"></div><button class="button danger" data-artifact-action="restore-backup" type="button">恢复并注册</button><div class="security-note"><strong>恢复约束</strong><span>目标文件夹已存在时拒绝恢复；签名私钥不会被自动加入备份。</span></div></div></section></aside></div>
    </div>`;
  }

  async function renderCards() {
    const selected = route().query.get('persona') || '';
    const [personas, exportsResult] = await Promise.all([
      api('/api/personas'),
      api('/api/v1/artifacts?category=exports'),
    ]);
    const cards = (exportsResult.items || []).filter((item) => item.name.includes('character-card'));
    setPageTitle('Character Card');
    workspace.innerHTML = `<div data-artifact-view="character-cards">
      ${pageHeader('Compatibility', 'Character Card', '检查、导入和导出 V2/V3 JSON、PNG Metadata 与 CHARX。Memory 和原始 Session 不进入 Character Card。')}
      <div class="tool-layout"><div class="tool-sections"><section class="panel"><header class="panel-header"><div class="panel-title"><h2>导入 Character Card</h2><p>先检查，再创建 Canonical Persona v3 工程</p></div></header><div class="panel-body compact-form"><input class="file-input" id="card-upload" type="file" accept=".json,.png,.charx"><div class="actions"><button class="button" data-artifact-action="inspect-card" type="button">上传并检查</button></div><div class="form-grid"><div class="field"><label>目标文件夹</label><input class="input" id="card-folder" placeholder="imported-character"></div><div class="field"><label>Persona ID 覆盖</label><input class="input" id="card-persona-id" placeholder="留空自动生成"></div><div class="field"><label>语言</label><select class="select" id="card-locale"><option value="zh-CN">简体中文</option><option value="zh-TW">繁體中文</option><option value="en-US">English</option><option value="ja-JP">日本語</option></select></div></div><div class="form-actions"><button class="button primary" data-artifact-action="import-card" type="button">导入为 Persona</button></div></div></section><section class="panel"><header class="panel-header"><div class="panel-title"><h2>已导出卡片</h2><p>未知 Extensions 会尽量往返保留</p></div><span class="status">${cards.length}</span></header><div class="panel-body flush">${artifactTable(cards, '导出 Character Card 后会显示。')}</div></section></div><aside class="tool-sidebar"><section class="panel"><header class="panel-header"><div class="panel-title"><h2>从 Persona 导出</h2><p>只导出人格定义</p></div></header><div class="panel-body compact-form"><div class="field"><label>Persona</label><select class="select" id="card-export-persona">${personaOptions(personas, selected)}</select></div><div class="field"><label>Card Version</label><select class="select" id="card-version"><option value="3">V3</option><option value="2">V2</option></select></div><label><input type="checkbox" id="card-charx"> 导出 CHARX</label><button class="button primary" data-artifact-action="export-card" type="button">导出 Character Card</button><div class="security-note"><strong>隐私</strong><span>Memory、Session、认证和工具状态不会写入卡片。</span></div></div></section></aside></div>
    </div>`;
  }

  async function renderAdapters() {
    const [summary, personas, skills] = await Promise.all([
      api('/api/v1/adapters'),
      api('/api/personas'),
      api('/api/v1/skills'),
    ]);
    setPageTitle('Adapter 与 Skill');
    const adapters = summary.adapters || [];
    workspace.innerHTML = `<div data-artifact-view="adapters">
      ${pageHeader('Extension Surface', 'Adapter 与 Skill', '检查内置和第三方 Adapter 契约，并安装统一 persona-builder Skill。')}
      <div class="tool-layout"><div class="tool-sections"><section class="panel"><header class="panel-header"><div class="panel-title"><h2>Adapter Registry</h2><p>API ${escapeHtml(summary.adapter_api_version)} · ${escapeHtml(summary.entry_point_group)}</p></div><span class="status">${adapters.length}</span></header><div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>Adapter</th><th>来源</th><th>传输</th><th>能力</th><th></th></tr></thead><tbody>${adapters.map((item) => `<tr><td><strong>${escapeHtml(item.display_name)}</strong><div class="list-meta code">${escapeHtml(item.name)}</div></td><td>${item.builtin ? statusBadge('ready', '内置') : statusBadge('info', '插件')}</td><td>${(item.transports || []).map((value) => `<span class="status">${escapeHtml(value)}</span>`).join(' ')}</td><td><div class="adapter-capabilities">${Object.entries(item.capabilities || {}).filter(([, enabled]) => enabled).map(([name]) => `<span class="status">${escapeHtml(name)}</span>`).join('')}</div></td><td><button class="button small" data-artifact-action="adapter-doctor" data-adapter="${attr(item.name)}" type="button">Doctor</button></td></tr>`).join('')}</tbody></table></div>${(summary.plugin_errors || []).length ? `<div class="panel-body"><div class="notice warning">${summary.plugin_errors.map((item) => escapeHtml(JSON.stringify(item))).join('<br>')}</div></div>` : ''}</section></div><aside class="tool-sidebar"><section class="panel"><header class="panel-header"><div class="panel-title"><h2>persona-builder Skill</h2><p>覆盖 Codex、Claude、OpenCode 等编辑器</p></div></header><div class="panel-body compact-form"><div class="field"><label>目标</label><select class="select" id="skill-target">${(skills.targets || []).map((value) => `<option value="${attr(value)}">${escapeHtml(value)}</option>`).join('')}</select></div><div class="field"><label>范围</label><select class="select" id="skill-scope"><option value="global">全局</option><option value="project">Persona 工程</option></select></div><div class="field"><label>Persona（项目范围）</label><select class="select" id="skill-persona"><option value="">请选择</option>${personaOptions(personas)}</select></div><div class="actions"><button class="button" data-artifact-action="skill-plan" type="button">预览</button><button class="button primary" data-artifact-action="skill-install" type="button">安装</button></div><div class="security-note"><strong>覆盖规则</strong><span>已有 persona-builder 目录会被替换；安装前可先查看目标路径。</span></div></div></section></aside></div>
    </div>`;
  }

  async function renderCurrent() {
    const current = route();
    if (!['packages', 'backups', 'character-cards', 'adapters'].includes(current.root) || rendering) {
      enhancePersonaDetail();
      return;
    }
    if (workspace.querySelector(`[data-artifact-view="${current.root}"]`)) return;
    rendering = true;
    try {
      if (current.root === 'packages') await renderPackages();
      else if (current.root === 'backups') await renderBackups();
      else if (current.root === 'character-cards') await renderCards();
      else if (current.root === 'adapters') await renderAdapters();
    } catch (error) {
      workspace.innerHTML = `<div data-artifact-view="${attr(current.root)}">${pageHeader('Error', '页面加载失败', error.message || String(error))}<section class="panel"><div class="panel-body"><div class="notice danger">${escapeHtml(error.message || error)}</div></div></section></div>`;
    } finally {
      rendering = false;
    }
  }

  async function personaOperation(action) {
    const personaId = document.getElementById('package-persona')?.value;
    if (!personaId) throw new Error('请选择 Persona');
    const targets = selectedTargets('package');
    const map = {
      build: [`/api/v1/personas/${encodeURIComponent(personaId)}/builds`, { targets }],
      pack: [`/api/v1/personas/${encodeURIComponent(personaId)}/packages`, { targets }],
      'public-export': [`/api/v1/personas/${encodeURIComponent(personaId)}/public-export`, null],
    };
    const [path, body] = map[action];
    const result = await api(path, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    toast(result.job ? `${result.job.label}完成` : '操作完成');
    showResult('操作结果', result.result || result);
  }

  async function inspectPackage() {
    const upload = await uploadFrom('package-upload');
    showResult('PersonaPack 检查结果', await api('/api/v1/packages/inspect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: upload.path }) }));
  }

  async function createKey() {
    const name = document.getElementById('key-name')?.value.trim();
    if (!name) throw new Error('请输入密钥名称');
    const result = await api('/api/v1/trust/keys', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    toast(`签名密钥已生成：${result.name}`);
    workspace.querySelector('[data-artifact-view="packages"]')?.remove();
    await renderCurrent();
  }

  async function signPackage() {
    const packagePath = document.getElementById('trust-package')?.value;
    const keyId = document.getElementById('trust-key')?.value;
    if (!packagePath || !keyId) throw new Error('请选择 PersonaPack 和签名密钥');
    const result = await api('/api/v1/trust/signatures', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ package_path: packagePath, key_id: keyId }) });
    toast('分离式签名已创建');
    showResult('签名结果', result.result || result);
  }

  async function verifyPackage() {
    const packagePath = document.getElementById('trust-package')?.value;
    const signaturePath = document.getElementById('trust-signature')?.value || null;
    if (!packagePath) throw new Error('请选择 PersonaPack');
    const result = await api('/api/v1/trust/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ package_path: packagePath, signature_path: signaturePath, trust_local_keys: true }) });
    showResult('验证结果', result.result || result);
  }

  async function createBackup() {
    const personaId = document.getElementById('backup-persona')?.value;
    const password = document.getElementById('backup-password')?.value || '';
    if (!personaId || password.length < 8) throw new Error('请选择 Persona，并输入至少 8 个字符的密码');
    const result = await api(`/api/v1/personas/${encodeURIComponent(personaId)}/backups`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) });
    document.getElementById('backup-password').value = '';
    toast('加密备份已创建');
    showResult('备份结果', result.result || result);
  }

  async function inspectBackup() {
    const upload = await uploadFrom('backup-upload');
    showResult('备份元数据', await api('/api/v1/backups/inspect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: upload.path }) }));
  }

  async function restoreBackup() {
    const upload = await uploadFrom('backup-upload');
    const folder = document.getElementById('backup-folder')?.value.trim();
    const password = document.getElementById('backup-restore-password')?.value || '';
    if (!folder || !password) throw new Error('请输入恢复文件夹和密码');
    const result = await api('/api/v1/backups/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: upload.path, folder, password }) });
    document.getElementById('backup-restore-password').value = '';
    toast('备份已恢复并注册');
    showResult('恢复结果', result.result || result);
  }

  async function inspectCard() {
    const upload = await uploadFrom('card-upload');
    showResult('Character Card 信息', await api('/api/v1/character-cards/inspect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: upload.path }) }));
  }

  async function importCard() {
    const upload = await uploadFrom('card-upload');
    const folder = document.getElementById('card-folder')?.value.trim();
    if (!folder) throw new Error('请输入目标文件夹');
    const result = await api('/api/v1/character-cards/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: upload.path, folder, persona_id: document.getElementById('card-persona-id')?.value.trim() || null, locale: document.getElementById('card-locale')?.value || 'zh-CN' }) });
    toast('Character Card 已导入为 Persona');
    showResult('导入结果', result.result || result);
  }

  async function exportCard() {
    const personaId = document.getElementById('card-export-persona')?.value;
    if (!personaId) throw new Error('请选择 Persona');
    const result = await api(`/api/v1/personas/${encodeURIComponent(personaId)}/character-card`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ version: Number(document.getElementById('card-version')?.value || 3), charx: Boolean(document.getElementById('card-charx')?.checked) }) });
    toast('Character Card 已导出');
    showResult('导出结果', result.result || result);
  }

  async function adapterDoctor(name) {
    const result = await api(`/api/v1/adapters/${encodeURIComponent(name)}/doctor`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ container: null, ssh_host: null }) });
    showResult(`${name} Doctor`, result.result || result);
  }

  function skillPayload() {
    return {
      target: document.getElementById('skill-target')?.value,
      scope: document.getElementById('skill-scope')?.value || 'global',
      persona_id: document.getElementById('skill-persona')?.value || null,
    };
  }

  async function skillAction(action) {
    const payload = skillPayload();
    const result = await api(`/api/v1/skills/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (action === 'install') toast('persona-builder Skill 已安装');
    showResult(action === 'plan' ? 'Skill 安装预览' : 'Skill 安装结果', result.result || result);
  }

  const observer = new MutationObserver(() => {
    enhancePersonaDetail();
    window.setTimeout(renderCurrent, 0);
  });
  observer.observe(workspace, { childList: true, subtree: true });
  window.addEventListener('hashchange', () => window.setTimeout(renderCurrent, 0));

  document.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-artifact-action]');
    if (!target) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      const action = target.dataset.artifactAction;
      if (action === 'dialog-close') closeDialog();
      else if (action === 'download') await downloadArtifact(target.dataset.path);
      else if (['build', 'pack', 'public-export'].includes(action)) await personaOperation(action);
      else if (action === 'inspect-package') await inspectPackage();
      else if (action === 'create-key') await createKey();
      else if (action === 'sign-package') await signPackage();
      else if (action === 'verify-package') await verifyPackage();
      else if (action === 'create-backup') await createBackup();
      else if (action === 'inspect-backup') await inspectBackup();
      else if (action === 'restore-backup') await restoreBackup();
      else if (action === 'inspect-card') await inspectCard();
      else if (action === 'import-card') await importCard();
      else if (action === 'export-card') await exportCard();
      else if (action === 'adapter-doctor') await adapterDoctor(target.dataset.adapter);
      else if (action === 'skill-plan') await skillAction('plan');
      else if (action === 'skill-install') await skillAction('install');
    } catch (error) {
      toast(error.message || String(error), 'error');
    }
  }, true);

  enhancePersonaDetail();
  renderCurrent();
})();
