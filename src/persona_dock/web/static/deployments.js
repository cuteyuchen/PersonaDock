(() => {
  'use strict';

  const workspace = document.getElementById('workspace');
  const dialogRoot = document.getElementById('dialog-root');
  const toastRegion = document.getElementById('toast-region');
  let rendering = false;
  let sourceMode = 'persona';
  let targetMode = 'hermes';
  let pendingPlan = null;
  let pendingRollback = null;

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function attr(value) { return escapeHtml(value); }
  function authToken() { return sessionStorage.getItem('personadock.web.token') || ''; }
  function headers(extra = {}) {
    const value = authToken();
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
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function toast(message, type = 'info') {
    const item = document.createElement('div');
    item.className = `toast ${type === 'error' ? 'error' : ''}`;
    item.textContent = message;
    toastRegion.appendChild(item);
    window.setTimeout(() => item.remove(), 4600);
  }

  function setTitle(value) {
    document.getElementById('route-title').textContent = value;
    document.title = `${value} · PersonaDock`;
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

  function formatDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(date);
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

  function packageOptions(items) {
    return items.filter((item) => item.name.endsWith('.personapack')).map((item) => `<option value="${attr(item.path)}">${escapeHtml(item.name)}</option>`).join('');
  }

  function showDialog(title, body, footer = '') {
    dialogRoot.innerHTML = `<div class="dialog-backdrop"><section class="dialog" role="dialog" aria-modal="true"><header class="dialog-header"><h2>${escapeHtml(title)}</h2><button class="icon-button" data-deployment-action="dialog-close" type="button">×</button></header><div class="dialog-body">${body}</div>${footer ? `<footer class="dialog-footer">${footer}</footer>` : ''}</section></div>`;
  }

  function closeDialog() {
    dialogRoot.innerHTML = '';
    pendingRollback = null;
  }

  function list(values, className = '') {
    if (!values?.length) return '<div class="list-meta">无</div>';
    return `<ul class="plan-list ${className}">${values.map((item) => `<li>${escapeHtml(Array.isArray(item) ? item.join(' ') : item)}</li>`).join('')}</ul>`;
  }

  function planSection(title, subtitle, body) {
    return `<section class="plan-section"><header class="plan-section-header"><strong>${escapeHtml(title)}</strong><span class="list-meta">${escapeHtml(subtitle)}</span></header><div class="plan-section-body">${body}</div></section>`;
  }

  function renderPlan(plan) {
    const targetName = plan.transport === 'ssh'
      ? `ssh://${plan.ssh_host}/${plan.agent}`
      : plan.transport === 'docker'
        ? `docker://${plan.container}/${plan.profile || plan.agent}`
        : (plan.profile || plan.agent);
    const conflicts = plan.conflicts || [];
    const operations = plan.commands || [];
    return `<div class="deployment-plan">
      <div class="plan-summary">
        <div class="plan-summary-cell"><span>目标</span><strong>${escapeHtml(plan.target || (plan.profile ? 'Hermes' : 'OpenClaw'))}</strong></div>
        <div class="plan-summary-cell"><span>实例</span><strong>${escapeHtml(targetName || '—')}</strong></div>
        <div class="plan-summary-cell"><span>传输</span><strong>${escapeHtml(plan.transport || 'local')}</strong></div>
        <div class="plan-summary-cell"><span>版本</span><strong>${escapeHtml(plan.persona_id)}@${escapeHtml(plan.persona_version)}</strong></div>
      </div>
      ${conflicts.length ? `<div class="risk-banner">发现未纳入 PersonaDock 所有权的文件。只有明确启用“接管已有文件”后，计划才会允许覆盖。</div>` : ''}
      ${planSection('将执行', `${operations.length} 项`, `<div class="command-list">${list(operations)}</div>`)}
      ${conflicts.length ? planSection('所有权冲突', `${conflicts.length} 项`, list(conflicts, 'conflict-list')) : ''}
      ${planSection('将保留', `${(plan.preserves || []).length} 项`, list(plan.preserves || [], 'preserve-list'))}
      ${planSection('警告', `${(plan.warnings || []).length} 项`, list(plan.warnings || [], 'warning-list'))}
      ${planSection('恢复点', plan.snapshot_path ? '计划创建快照' : '当前无需快照', `<div class="code">${escapeHtml(plan.snapshot_path || '新建目标或当前目标没有 PersonaDock 所有内容，不创建预部署快照。')}</div>`)}
      <div class="apply-strip"><p>Apply 前会重新读取 Runtime 状态并比较计划哈希。目标状态发生变化时，本计划将失效。</p><button class="button primary" data-deployment-action="apply-plan" type="button">确认并应用计划</button></div>
    </div>`;
  }

  function deploymentRows(items) {
    if (!items.length) return `<tr><td colspan="7">${emptyState('暂无部署记录', '生成计划后会保留在控制面历史中。')}</td></tr>`;
    return items.map((item) => {
      const request = item.request || {};
      const plan = item.plan || {};
      const destination = plan.profile || plan.agent || '—';
      return `<tr>
        <td><a href="#/deployments/${attr(item.id)}"><strong>${escapeHtml(request.persona_id || plan.persona_id || '外部包')}</strong></a><div class="list-meta code deployment-id">${escapeHtml(item.id)}</div></td>
        <td>${escapeHtml(item.kind)}</td>
        <td>${escapeHtml(destination)}</td>
        <td>${escapeHtml(plan.transport || 'local')}</td>
        <td>${statusBadge(item.status)}</td>
        <td>${formatDate(item.created_at)}</td>
        <td>${item.status === 'applied' ? `<button class="button small danger" data-deployment-action="rollback-dialog" data-deployment-id="${attr(item.id)}" type="button">回滚</button>` : ''}</td>
      </tr>`;
    }).join('');
  }

  async function renderDeployments() {
    const selectedPersona = route().query.get('persona') || '';
    const [personas, artifacts, history] = await Promise.all([
      api('/api/personas'),
      api('/api/v1/artifacts?category=exports'),
      api('/api/v1/deployments?limit=100'),
    ]);
    setTitle('部署');
    const packages = artifacts.items || [];
    workspace.innerHTML = `<div data-deployment-view="list" class="deployment-shell">
      ${pageHeader('Native Deployment', '部署', '从 Persona 或 PersonaPack 生成原生 Hermes Profile / OpenClaw Agent 计划。默认不使用旧 Filesystem 安装器。')}
      <div class="deployment-layout">
        <section class="panel">
          <header class="panel-header"><div class="panel-title"><h2>新部署计划</h2><p>Plan → 审核 → Apply → Verify</p></div></header>
          <div class="panel-body deployment-form">
            <div class="field"><label>来源</label><div class="deployment-source-tabs"><button class="deployment-tab ${sourceMode === 'persona' ? 'active' : ''}" data-deployment-action="source-mode" data-mode="persona" type="button">Registry Persona</button><button class="deployment-tab ${sourceMode === 'package' ? 'active' : ''}" data-deployment-action="source-mode" data-mode="package" type="button">现有 PersonaPack</button></div></div>
            <div class="field" id="deployment-persona-source" ${sourceMode === 'persona' ? '' : 'hidden'}><label>Persona</label><select class="select" id="deployment-persona"><option value="">选择 Persona</option>${personaOptions(personas, selectedPersona)}</select></div>
            <div class="field" id="deployment-package-source" ${sourceMode === 'package' ? '' : 'hidden'}><label>PersonaPack</label><select class="select" id="deployment-package"><option value="">选择已生成的包</option>${packageOptions(packages)}</select><div class="field-help">外部 PersonaPack 可先在“PersonaPack 与信任”页面上传、检查并验证。</div></div>
            <div class="field"><label>目标平台</label><div class="deployment-target-tabs"><button class="deployment-tab ${targetMode === 'hermes' ? 'active' : ''}" data-deployment-action="target-mode" data-mode="hermes" type="button">Hermes</button><button class="deployment-tab ${targetMode === 'openclaw' ? 'active' : ''}" data-deployment-action="target-mode" data-mode="openclaw" type="button">OpenClaw</button></div></div>
            <div class="deployment-options" id="hermes-options" ${targetMode === 'hermes' ? '' : 'hidden'}>
              <div class="form-grid"><div class="field"><label>Profile 名称</label><input class="input" id="deployment-profile" placeholder="留空使用 Persona ID"></div><div class="field"><label>Docker 容器</label><input class="input" id="deployment-hermes-container" placeholder="留空使用本机 Hermes"></div></div>
              <div class="check-row"><label><input type="checkbox" id="deployment-activate">部署后设为活动 Profile</label><label><input type="checkbox" id="deployment-alias">请求 Hermes 创建 Alias</label></div>
            </div>
            <div class="deployment-options" id="openclaw-options" ${targetMode === 'openclaw' ? '' : 'hidden'}>
              <div class="form-grid"><div class="field"><label>Agent ID</label><input class="input" id="deployment-agent" placeholder="留空使用 Persona ID"></div><div class="field"><label>新 Agent Workspace</label><input class="input" id="deployment-workspace" placeholder="现有 Agent 自动使用发现的 Workspace"></div><div class="field"><label>新 Agent Model</label><input class="input" id="deployment-model" placeholder="仅新建 Agent 时使用"></div><div class="field"><label>传输</label><div class="transport-row"><input class="input" id="deployment-openclaw-container" placeholder="Docker 容器"><input class="input" id="deployment-ssh-host" placeholder="SSH host"></div></div></div>
              <div class="field"><label>Channel Bindings</label><textarea class="textarea binding-editor" id="deployment-bindings" placeholder="每行一个绑定，仅新建 Agent 时使用"></textarea></div>
              <label class="notice warning"><input type="checkbox" id="deployment-take-ownership"> 我已审核 Diff，允许 PersonaDock 接管现有 SOUL / IDENTITY / Persona Skill 文件</label>
            </div>
            <div class="form-actions"><button class="button primary" data-deployment-action="create-plan" type="button">生成部署计划</button></div>
          </div>
        </section>
        <aside class="stack">
          <section class="panel"><header class="panel-header"><div class="panel-title"><h2>执行边界</h2><p>原生 Adapter 所有权</p></div></header><div class="panel-body"><ul class="plan-list preserve-list"><li>Hermes 保留 Memory、Session、认证、state.db 和本地覆盖。</li><li>OpenClaw 保留 Memory、Session、agentDir、认证和非 PersonaDock Skill。</li><li>Apply 前重新计划；状态变化会拒绝旧令牌。</li><li>失败时调用原生回滚路径。</li></ul></div></section>
          <section class="panel"><header class="panel-header"><div class="panel-title"><h2>当前计划</h2><p>令牌只存在当前页面内存</p></div></header><div class="panel-body" id="deployment-plan-output">${emptyState('尚未生成计划', '填写来源和目标后生成只读计划。')}</div></section>
        </aside>
      </div>
      <section class="panel deployment-history"><header class="panel-header"><div class="panel-title"><h2>部署历史</h2><p>计划、执行和回滚状态</p></div><span class="status">${history.count || 0}</span></header><div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>Persona / 计划</th><th>平台</th><th>目标</th><th>传输</th><th>状态</th><th>创建时间</th><th></th></tr></thead><tbody>${deploymentRows(history.items || [])}</tbody></table></div></section>
    </div>`;
  }

  async function renderDeploymentDetail(id) {
    const item = await api(`/api/v1/deployments/${encodeURIComponent(id)}`);
    setTitle('部署详情');
    const plan = item.plan || {};
    workspace.innerHTML = `<div data-deployment-view="detail" class="deployment-shell">
      ${pageHeader('Deployment', plan.persona_id || item.id, `${item.kind} · ${plan.transport || 'local'}`, `<a class="button" href="#/deployments">返回部署</a>${item.status === 'applied' ? `<button class="button danger" data-deployment-action="rollback-dialog" data-deployment-id="${attr(item.id)}" type="button">回滚</button>` : ''}`)}
      <div class="deployment-detail-grid">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>状态</h2><p class="code">${escapeHtml(item.id)}</p></div>${statusBadge(item.status)}</header><div class="panel-body"><div class="form-grid"><div class="field"><label>创建</label><div>${formatDate(item.created_at)}</div></div><div class="field"><label>应用</label><div>${formatDate(item.applied_at)}</div></div><div class="field"><label>回滚</label><div>${formatDate(item.rolled_back_at)}</div></div><div class="field"><label>计划哈希</label><div class="code">${escapeHtml(item.semantic_hash)}</div></div></div>${item.error ? `<div class="risk-banner" style="margin-top:14px">${escapeHtml(item.error)}</div>` : ''}</div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>请求</h2><p>不包含确认令牌</p></div></header><pre class="mono-box">${escapeHtml(JSON.stringify(item.request, null, 2))}</pre></section>
      </div>
      <section class="panel"><header class="panel-header"><div class="panel-title"><h2>已审核计划</h2><p>创建时保存的计划快照</p></div></header><div class="panel-body">${renderPlan({ ...plan, commands: plan.commands || [] }).replace(/<div class="apply-strip">[\s\S]*?<\/div>\s*<\/div>$/, '</div>')}</div></section>
      <section class="panel"><header class="panel-header"><div class="panel-title"><h2>执行结果</h2><p>原生 Adapter 验证输出</p></div></header><pre class="mono-box">${escapeHtml(JSON.stringify(item.output || {}, null, 2))}</pre></section>
    </div>`;
  }

  function deploymentPayload() {
    const payload = {
      target: targetMode,
      persona_id: sourceMode === 'persona' ? (document.getElementById('deployment-persona')?.value || null) : null,
      package_path: sourceMode === 'package' ? (document.getElementById('deployment-package')?.value || null) : null,
      profile: null,
      activate: false,
      alias: false,
      agent: null,
      workspace: null,
      model: null,
      bindings: [],
      take_ownership: false,
      container: null,
      ssh_host: null,
    };
    if (!payload.persona_id && !payload.package_path) throw new Error('请选择 Persona 或 PersonaPack');
    if (targetMode === 'hermes') {
      payload.profile = document.getElementById('deployment-profile')?.value.trim() || null;
      payload.activate = Boolean(document.getElementById('deployment-activate')?.checked);
      payload.alias = Boolean(document.getElementById('deployment-alias')?.checked);
      payload.container = document.getElementById('deployment-hermes-container')?.value.trim() || null;
    } else {
      payload.agent = document.getElementById('deployment-agent')?.value.trim() || null;
      payload.workspace = document.getElementById('deployment-workspace')?.value.trim() || null;
      payload.model = document.getElementById('deployment-model')?.value.trim() || null;
      payload.bindings = (document.getElementById('deployment-bindings')?.value || '').split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
      payload.take_ownership = Boolean(document.getElementById('deployment-take-ownership')?.checked);
      payload.container = document.getElementById('deployment-openclaw-container')?.value.trim() || null;
      payload.ssh_host = document.getElementById('deployment-ssh-host')?.value.trim() || null;
      if (payload.container && payload.ssh_host) throw new Error('Docker 与 SSH 只能选择一种传输方式');
    }
    return payload;
  }

  async function createPlan() {
    pendingPlan = null;
    const output = document.getElementById('deployment-plan-output');
    output.innerHTML = emptyState('正在生成计划', '正在检查 PersonaPack、Runtime 和所有权状态。');
    try {
      const result = await api('/api/v1/deployment-plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(deploymentPayload()),
      });
      pendingPlan = {
        id: result.deployment.id,
        token: result.confirmation_token,
      };
      output.innerHTML = renderPlan(result.deployment.plan);
      toast('部署计划已生成，请审核后再应用');
    } catch (error) {
      output.innerHTML = `<div class="risk-banner">${escapeHtml(error.message || error)}</div>`;
      throw error;
    }
  }

  async function applyPlan() {
    if (!pendingPlan) throw new Error('当前页面没有可用确认令牌，请重新生成计划');
    const value = pendingPlan;
    pendingPlan = null;
    try {
      const result = await api('/api/v1/deployments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: value.id, confirmation_token: value.token }),
      });
      toast('部署完成并已执行原生验证');
      location.hash = `#/deployments/${encodeURIComponent(result.result.id)}`;
    } catch (error) {
      if (error.status === 409) toast('Runtime 状态已变化，旧计划被拒绝，请重新生成', 'error');
      throw error;
    }
  }

  function showRollbackDialog(id) {
    pendingRollback = id;
    showDialog(
      '回滚部署',
      `<div class="risk-banner">回滚会调用目标平台的原生恢复路径。已有目标恢复预部署快照；由 PersonaDock 新建且无快照的目标会被删除。</div><div class="field" style="margin-top:14px"><label for="rollback-confirmation">输入 ROLLBACK 继续</label><input class="input" id="rollback-confirmation" autocomplete="off"></div>`,
      '<button class="button" data-deployment-action="dialog-close" type="button">取消</button><button class="button danger" data-deployment-action="rollback-confirm" type="button">执行回滚</button>',
    );
  }

  async function confirmRollback() {
    const value = document.getElementById('rollback-confirmation')?.value || '';
    if (value !== 'ROLLBACK') throw new Error('请输入 ROLLBACK');
    const id = pendingRollback;
    if (!id) return;
    await api(`/api/v1/deployments/${encodeURIComponent(id)}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmation: 'ROLLBACK' }),
    });
    closeDialog();
    toast('部署已回滚');
    if (route().parts[1]) await renderCurrent(true);
    else await renderCurrent(true);
  }

  function updateMode(kind, value) {
    if (kind === 'source') sourceMode = value;
    else targetMode = value;
    const current = route();
    const persona = document.getElementById('deployment-persona')?.value || current.query.get('persona') || '';
    renderDeployments().then(() => {
      if (persona) document.getElementById('deployment-persona').value = persona;
    }).catch((error) => toast(error.message || error, 'error'));
  }

  async function renderCurrent(force = false) {
    const current = route();
    if (current.root !== 'deployments' || rendering) return;
    const expected = current.parts[1] ? 'detail' : 'list';
    if (!force && workspace.querySelector(`[data-deployment-view="${expected}"]`)) return;
    rendering = true;
    try {
      pendingPlan = null;
      if (current.parts[1]) await renderDeploymentDetail(current.parts[1]);
      else await renderDeployments();
    } catch (error) {
      workspace.innerHTML = `${pageHeader('Deployment Error', '部署页面加载失败', error.message || String(error))}<div class="risk-banner">${escapeHtml(error.message || error)}</div>`;
    } finally {
      rendering = false;
    }
  }

  const observer = new MutationObserver(() => window.setTimeout(() => renderCurrent(), 0));
  observer.observe(workspace, { childList: true, subtree: true });
  window.addEventListener('hashchange', () => window.setTimeout(() => renderCurrent(true), 0));

  document.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-deployment-action]');
    if (!target) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      const action = target.dataset.deploymentAction;
      if (action === 'dialog-close') closeDialog();
      else if (action === 'source-mode') updateMode('source', target.dataset.mode);
      else if (action === 'target-mode') updateMode('target', target.dataset.mode);
      else if (action === 'create-plan') await createPlan();
      else if (action === 'apply-plan') await applyPlan();
      else if (action === 'rollback-dialog') showRollbackDialog(target.dataset.deploymentId);
      else if (action === 'rollback-confirm') await confirmRollback();
    } catch (error) {
      toast(error.message || String(error), 'error');
    }
  }, true);

  renderCurrent();
})();
