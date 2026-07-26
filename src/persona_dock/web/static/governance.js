(() => {
  'use strict';

  const workspace = document.getElementById('workspace');
  const dialogRoot = document.getElementById('dialog-root');
  const toastRegion = document.getElementById('toast-region');
  let rendering = false;
  let memoryFilter = 'pending';
  let sessionFilter = 'pending';

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

  function pageHeader(kicker, title, summary, actions = '') {
    return `<header class="page-header"><div><div class="page-kicker">${escapeHtml(kicker)}</div><h1>${escapeHtml(title)}</h1><p class="page-summary">${escapeHtml(summary)}</p></div>${actions ? `<div class="actions">${actions}</div>` : ''}</header>`;
  }

  function setTitle(value) {
    document.getElementById('route-title').textContent = value;
    document.title = `${value} · PersonaDock`;
  }

  function statusBadge(status, label = null) {
    return `<span class="status ${attr(status)}">${escapeHtml(label || status)}</span>`;
  }

  function emptyState(title, text) {
    return `<div class="empty-state"><strong>${escapeHtml(title)}</strong>${escapeHtml(text)}</div>`;
  }

  function route() {
    const raw = location.hash.replace(/^#\/?/, '');
    const [path, query = ''] = raw.split('?');
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    return { root: parts[0] || 'overview', query: new URLSearchParams(query) };
  }

  function personaOptions(personas, selected) {
    return personas.map((item) => `<option value="${attr(item.id)}" ${item.id === selected ? 'selected' : ''}>${escapeHtml(item.name)} (${escapeHtml(item.id)})</option>`).join('');
  }

  function metric(label, value, detail = '') {
    return `<div class="governance-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? 0)}</strong><div class="list-meta">${escapeHtml(detail)}</div></div>`;
  }

  function jsonEditor(id, value, className = 'policy-editor') {
    return `<textarea class="textarea ${className}" id="${attr(id)}" spellcheck="false">${escapeHtml(JSON.stringify(value ?? {}, null, 2))}</textarea>`;
  }

  function showDialog(title, body, footer = '') {
    dialogRoot.innerHTML = `<div class="dialog-backdrop"><section class="dialog" role="dialog" aria-modal="true"><header class="dialog-header"><h2>${escapeHtml(title)}</h2><button class="icon-button" data-governance-action="dialog-close" type="button">×</button></header><div class="dialog-body">${body}</div>${footer ? `<footer class="dialog-footer">${footer}</footer>` : ''}</section></div>`;
  }

  function closeDialog() { dialogRoot.innerHTML = ''; }

  function selectedPersona() {
    const value = document.getElementById('governance-persona')?.value || '';
    if (!value) throw new Error('请选择 Persona');
    return value;
  }

  function reviewTabs(kind, current) {
    return `<div class="governance-tabs">${['pending', 'approved', 'rejected', 'all'].map((value) => `<button class="button small ${current === value ? 'active' : ''}" data-governance-action="filter" data-kind="${attr(kind)}" data-filter="${attr(value)}" type="button">${({ pending: '待审核', approved: '已批准', rejected: '已拒绝', all: '全部' })[value]}</button>`).join('')}</div>`;
  }

  function memoryRows(items) {
    if (!items.length) return emptyState('当前筛选没有 Memory', '收集后候选会先进入待审核队列。');
    return `<div class="review-list">${items.map((item) => `<article class="review-item">
      <div class="review-head"><div><div class="review-title">${escapeHtml(item.memory_type || item.memory_key || 'Memory')}</div><div class="list-meta code">${escapeHtml(item.memory_key || item.id)}</div></div><div class="review-meta">${statusBadge(item.status)}${statusBadge(item.sensitivity)}${statusBadge(item.sync_scope || 'local-only')}</div></div>
      <p class="review-summary">${escapeHtml(item.summary || '')}</p>
      <div class="review-meta"><span>来源 ${escapeHtml(item.source_adapter || 'canonical')}</span><span class="code">${escapeHtml(item.source_path || item.source_record_id || '—')}</span></div>
      ${item.status === 'pending' ? `<div class="review-actions"><button class="button small primary" data-governance-action="memory-approve" data-id="${attr(item.id)}" data-scope="shared" type="button">批准并共享</button><button class="button small" data-governance-action="memory-approve" data-id="${attr(item.id)}" data-scope="local-only" type="button">仅本地批准</button><button class="button small danger" data-governance-action="memory-reject" data-id="${attr(item.id)}" type="button">拒绝</button></div>` : ''}
    </article>`).join('')}</div>`;
  }

  function conflictRows(items) {
    if (!items.length) return emptyState('没有待处理冲突', '内容指纹和来源检查未发现冲突。');
    return `<div class="review-list">${items.map((item) => {
      const details = item.details || {};
      const candidate = details.candidate || {};
      const existing = details.existing || {};
      return `<article class="review-item"><div class="review-head"><div class="review-title">${escapeHtml(item.conflict_type || 'Memory conflict')}</div>${statusBadge(item.status || 'pending')}</div><div class="conflict-compare"><div class="conflict-side"><strong>候选</strong><p>${escapeHtml(candidate.summary || item.candidate_id || '—')}</p></div><div class="conflict-side"><strong>现有</strong><p>${escapeHtml(existing.summary || item.existing_item_id || '—')}</p></div></div>${item.status !== 'resolved' ? `<div class="review-actions"><button class="button small" data-governance-action="conflict-resolve" data-id="${attr(item.id)}" data-resolution="keep-existing" type="button">保留现有</button><button class="button small danger" data-governance-action="conflict-resolve" data-id="${attr(item.id)}" data-resolution="replace" type="button">候选替换</button><button class="button small primary" data-governance-action="conflict-resolve" data-id="${attr(item.id)}" data-resolution="keep-both" type="button">两者并存</button></div>` : ''}</article>`;
    }).join('')}</div>`;
  }

  function sessionRows(items) {
    if (!items.length) return emptyState('当前筛选没有摘要', '平台摘要和手动摘要会先进入待审核队列。');
    return `<div class="review-list">${items.map((item) => `<article class="review-item">
      <div class="review-head"><div><div class="review-title">${escapeHtml(item.source_title || 'Session Summary')}</div><div class="list-meta code">${escapeHtml(item.id)}</div></div><div class="review-meta">${statusBadge(item.status)}${statusBadge(item.source_adapter || 'manual')}${statusBadge(item.sensitivity || 'internal')}</div></div>
      <p class="review-summary">${escapeHtml(item.summary || '')}</p>
      ${(item.pending_tasks || []).length ? `<div class="review-meta"><strong>待办：</strong>${(item.pending_tasks || []).map(escapeHtml).join('；')}</div>` : ''}
      ${item.status === 'pending' ? `<div class="review-actions"><button class="button small primary" data-governance-action="session-approve" data-id="${attr(item.id)}" data-scope="shared" type="button">批准并共享</button><button class="button small" data-governance-action="session-approve" data-id="${attr(item.id)}" data-scope="local-only" type="button">仅本地批准</button><button class="button small danger" data-governance-action="session-reject" data-id="${attr(item.id)}" type="button">拒绝</button></div>` : ''}
    </article>`).join('')}</div>`;
  }

  async function renderMemory() {
    const personas = await api('/api/personas');
    const requested = route().query.get('persona') || '';
    const personaId = requested || personas[0]?.id || '';
    setTitle('Memory 同步');
    if (!personaId) {
      workspace.innerHTML = `${pageHeader('Governance', 'Memory 同步', '跨 Runtime 的 Memory 默认先审核。')}${emptyState('没有 Persona', '请先创建或注册 Persona。')}`;
      return;
    }
    const [dashboard, policy, items, conflicts, plan, runs] = await Promise.all([
      api(`/api/sync/${encodeURIComponent(personaId)}`),
      api(`/api/sync/${encodeURIComponent(personaId)}/policy`),
      api(`/api/sync/${encodeURIComponent(personaId)}/memory`),
      api(`/api/sync/${encodeURIComponent(personaId)}/conflicts?status=pending`),
      api(`/api/sync/${encodeURIComponent(personaId)}/plan`),
      api(`/api/sync/${encodeURIComponent(personaId)}/runs?limit=20`),
    ]);
    const filtered = memoryFilter === 'all' ? items : items.filter((item) => item.status === memoryFilter);
    const counts = dashboard.counts || {};
    workspace.innerHTML = `<div data-governance-view="memory" class="governance-shell">
      ${pageHeader('Governed Memory', 'Memory 同步', '候选先审核、冲突显式解决、传播按来源和内容指纹追踪。原始 Session 不参与 Memory 同步。')}
      <div class="governance-toolbar"><div class="field"><label>Persona</label><select class="select" id="governance-persona">${personaOptions(personas, personaId)}</select></div><button class="button" data-governance-action="memory-collect" type="button">从绑定 Runtime 收集</button><div class="toolbar-spacer"></div><a class="button small" href="/sync">兼容审核页</a></div>
      <section class="governance-metrics">${metric('待审核', counts.pending ?? items.filter((item) => item.status === 'pending').length)}${metric('已批准', counts.approved ?? items.filter((item) => item.status === 'approved').length)}${metric('冲突', counts.conflicts ?? conflicts.length)}${metric('Memory 操作', counts.memory_actions ?? 0)}${metric('同步运行', runs.length)}</section>
      <div class="governance-layout"><div class="stack">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>审核队列</h2><p>${items.length} 条 Memory</p></div>${reviewTabs('memory', memoryFilter)}</header><div class="panel-body flush">${memoryRows(filtered)}</div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>冲突对比</h2><p>不会静默覆盖</p></div><span class="status">${conflicts.length}</span></header><div class="panel-body flush">${conflictRows(conflicts)}</div></section>
      </div><aside class="stack">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>Sync Policy</h2><p>默认 Review 模式</p></div></header><div class="panel-body">${jsonEditor('memory-policy', policy)}<div class="form-actions"><button class="button" data-governance-action="memory-policy-save" type="button">验证并保存</button></div></div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>传播计划</h2><p>Apply 时重新生成</p></div></header><div class="panel-body">${jsonEditor('memory-plan', plan, 'plan-editor')}<div class="plan-actions"><label><input type="checkbox" id="memory-include-definitions"> 包含过期人格定义</label><button class="button primary" data-governance-action="memory-apply-dialog" type="button">审核并应用</button></div></div></section>
      </aside></div>
    </div>`;
  }

  async function renderSessions() {
    const personas = await api('/api/personas');
    const requested = route().query.get('persona') || '';
    const personaId = requested || personas[0]?.id || '';
    setTitle('Session Summary');
    if (!personaId) {
      workspace.innerHTML = `${pageHeader('Governance', 'Session Summary', '只传播已审核摘要。')}${emptyState('没有 Persona', '请先创建或注册 Persona。')}`;
      return;
    }
    const [dashboard, policy, items, plan] = await Promise.all([
      api(`/api/sessions/${encodeURIComponent(personaId)}`),
      api(`/api/sessions/${encodeURIComponent(personaId)}/policy`),
      api(`/api/sessions/${encodeURIComponent(personaId)}/items`),
      api(`/api/sessions/${encodeURIComponent(personaId)}/plan`),
    ]);
    const filtered = sessionFilter === 'all' ? items : items.filter((item) => item.status === sessionFilter);
    const counts = dashboard.counts || {};
    workspace.innerHTML = `<div data-governance-view="sessions" class="governance-shell">
      ${pageHeader('Reviewed Handoff', 'Session Summary', '采集平台已有摘要或手动交接，审核后再传播。默认不读取、不保存、不同步原始 Session。')}
      <div class="governance-toolbar"><div class="field"><label>Persona</label><select class="select" id="governance-persona">${personaOptions(personas, personaId)}</select></div><button class="button" data-governance-action="session-collect" type="button">收集平台摘要</button><button class="button" data-governance-action="manual-dialog" type="button">添加手动摘要</button><div class="toolbar-spacer"></div><a class="button small" href="/sessions">兼容审核页</a></div>
      <section class="governance-metrics">${metric('待审核', counts.pending ?? items.filter((item) => item.status === 'pending').length)}${metric('已批准', counts.approved ?? items.filter((item) => item.status === 'approved').length)}${metric('已拒绝', counts.rejected ?? items.filter((item) => item.status === 'rejected').length)}${metric('来源 Runtime', dashboard.runtime_instances?.length ?? 0)}${metric('原始 Session 同步', '关闭')}</section>
      <div class="governance-layout"><div class="stack">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>摘要审核队列</h2><p>${items.length} 条摘要</p></div>${reviewTabs('sessions', sessionFilter)}</header><div class="panel-body flush">${sessionRows(filtered)}</div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>实验性原始预览</h2><p>不写入 Registry</p></div></header><div class="panel-body"><div class="governance-danger">只在策略显式启用时工作，并过滤系统消息、工具调用、工具结果和内部推理。该功能不是原始 Session 同步。</div><div class="raw-preview-fields" style="margin-top:12px"><div class="field"><label>Runtime Instance ID</label><input class="input" id="raw-runtime"></div><div class="field"><label>Session / Transcript Selector</label><input class="input" id="raw-session"></div><button class="button danger" data-governance-action="raw-preview-dialog" type="button">执行一次风险预览</button></div><pre class="mono-box" id="raw-preview-output" style="margin-top:12px">尚未执行</pre></div></section>
      </div><aside class="stack">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>Session Policy</h2><p>Review-first</p></div></header><div class="panel-body">${jsonEditor('session-policy', policy)}<div class="form-actions"><button class="button" data-governance-action="session-policy-save" type="button">验证并保存</button></div></div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>传播计划</h2><p>只含已批准摘要</p></div></header><div class="panel-body">${jsonEditor('session-plan', plan, 'plan-editor')}<div class="plan-actions"><span class="list-meta">Apply 前重新生成</span><button class="button primary" data-governance-action="session-apply-dialog" type="button">审核并应用</button></div></div></section>
      </aside></div>
    </div>`;
  }

  async function savePolicy(kind) {
    const personaId = selectedPersona();
    const editor = document.getElementById(kind === 'memory' ? 'memory-policy' : 'session-policy');
    let config;
    try { config = JSON.parse(editor.value); } catch (error) { throw new Error(`策略 JSON 无效：${error.message}`); }
    const prefix = kind === 'memory' ? '/api/sync' : '/api/sessions';
    await api(`${prefix}/${encodeURIComponent(personaId)}/policy`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config, replace: true }),
    });
    toast('策略已验证并保存');
    await renderCurrent(true);
  }

  async function collect(kind) {
    const personaId = selectedPersona();
    await api(`/api/v1/governance/${kind}/${encodeURIComponent(personaId)}/collect`, { method: 'POST' });
    toast(kind === 'memory' ? 'Memory 候选收集完成' : 'Session Summary 收集完成');
    await renderCurrent(true);
  }

  async function memoryReview(id, approve, scope = 'shared') {
    const action = approve ? 'approve' : 'reject';
    const body = approve ? { reviewer: 'web-2', scope } : { reviewer: 'web-2', reason: 'Rejected in Web Control Plane' };
    await api(`/api/sync/memory/${encodeURIComponent(id)}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    toast(approve ? 'Memory 已批准' : 'Memory 已拒绝');
    await renderCurrent(true);
  }

  async function resolveConflict(id, resolution) {
    await api(`/api/sync/conflicts/${encodeURIComponent(id)}/resolve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resolution, reviewer: 'web-2' }) });
    toast('冲突已解决');
    await renderCurrent(true);
  }

  async function sessionReview(id, approve, scope = 'shared') {
    const action = approve ? 'approve' : 'reject';
    const body = approve ? { reviewer: 'web-2', scope } : { reviewer: 'web-2', scope: 'local-only', reason: 'Rejected in Web Control Plane' };
    await api(`/api/session-summaries/${encodeURIComponent(id)}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    toast(approve ? '摘要已批准' : '摘要已拒绝');
    await renderCurrent(true);
  }

  function showApplyDialog(kind) {
    showDialog(
      kind === 'memory' ? '应用 Memory 同步计划' : '应用 Session Summary 计划',
      `<div class="governance-warning">Apply 会重新生成计划，只传播已审核内容。目标 Runtime 状态和 Adapter 验证仍由底层治理引擎负责。</div><div class="field" style="margin-top:14px"><label>输入 APPLY 继续</label><input class="input" id="governance-confirmation" autocomplete="off"></div>`,
      `<button class="button" data-governance-action="dialog-close" type="button">取消</button><button class="button primary" data-governance-action="apply-confirm" data-kind="${attr(kind)}" type="button">应用计划</button>`,
    );
  }

  async function applyPlan(kind) {
    if (document.getElementById('governance-confirmation')?.value !== 'APPLY') throw new Error('请输入 APPLY');
    const personaId = selectedPersona();
    const body = kind === 'memory'
      ? { confirmed: true, include_definitions: Boolean(document.getElementById('memory-include-definitions')?.checked) }
      : { confirmed: true };
    await api(`/api/v1/governance/${kind}/${encodeURIComponent(personaId)}/apply`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    closeDialog();
    toast('治理计划已应用');
    await renderCurrent(true);
  }

  function showManualDialog() {
    showDialog('添加手动 Session Summary', `<div class="field"><label>标题</label><input class="input" id="manual-title" value="Manual summary"></div><div class="field" style="margin-top:10px"><label>摘要</label><textarea class="textarea manual-summary-editor" id="manual-summary" placeholder="只写需要交接的事实、上下文和结论"></textarea></div><div class="field" style="margin-top:10px"><label>待办（每行一个）</label><textarea class="textarea" id="manual-tasks" style="min-height:90px"></textarea></div><div class="form-grid" style="margin-top:10px"><div class="field"><label>情绪标签</label><input class="input" id="manual-emotion"></div><div class="field"><label>敏感度</label><select class="select" id="manual-sensitivity"><option>internal</option><option>public</option><option>private</option><option>restricted</option></select></div></div>`, '<button class="button" data-governance-action="dialog-close" type="button">取消</button><button class="button primary" data-governance-action="manual-save" type="button">加入待审核队列</button>');
  }

  async function saveManual() {
    const personaId = selectedPersona();
    const summary = document.getElementById('manual-summary')?.value.trim() || '';
    if (!summary) throw new Error('请输入摘要');
    const emotion = document.getElementById('manual-emotion')?.value.trim() || '';
    await api(`/api/sessions/${encodeURIComponent(personaId)}/manual`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ summary, title: document.getElementById('manual-title')?.value.trim() || 'Manual summary', pending_tasks: (document.getElementById('manual-tasks')?.value || '').split(/\r?\n/).map((item) => item.trim()).filter(Boolean), emotional_context: emotion ? { label: emotion } : {}, sensitivity: document.getElementById('manual-sensitivity')?.value || 'internal' }) });
    closeDialog();
    toast('手动摘要已加入待审核队列');
    await renderCurrent(true);
  }

  function showRawPreviewDialog() {
    showDialog('实验性原始 Session 预览', '<div class="governance-danger">可能读取目标平台原始会话。只显示过滤和脱敏后的用户/助手消息，不写入 PersonaDock。输入 PREVIEW 表示理解风险。</div><div class="field" style="margin-top:14px"><label>输入 PREVIEW 继续</label><input class="input" id="raw-confirmation" autocomplete="off"></div>', '<button class="button" data-governance-action="dialog-close" type="button">取消</button><button class="button danger" data-governance-action="raw-preview-confirm" type="button">执行一次预览</button>');
  }

  async function rawPreview() {
    if (document.getElementById('raw-confirmation')?.value !== 'PREVIEW') throw new Error('请输入 PREVIEW');
    const personaId = selectedPersona();
    const runtime = document.getElementById('raw-runtime')?.value.trim() || '';
    const session = document.getElementById('raw-session')?.value.trim() || '';
    if (!runtime || !session) throw new Error('请输入 Runtime 与 Session Selector');
    const result = await api(`/api/sessions/${encodeURIComponent(personaId)}/preview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ runtime_instance_id: runtime, session_id: session, experimental: true }) });
    closeDialog();
    document.getElementById('raw-preview-output').textContent = JSON.stringify(result, null, 2);
    toast('实验性预览完成；内容未写入 Registry');
  }

  async function renderCurrent(force = false) {
    const current = route();
    if (!['memory', 'sessions'].includes(current.root) || rendering) return;
    if (!force && workspace.querySelector(`[data-governance-view="${current.root}"]`)) return;
    rendering = true;
    try {
      if (current.root === 'memory') await renderMemory();
      else await renderSessions();
    } catch (error) {
      workspace.innerHTML = `${pageHeader('Governance Error', '治理页面加载失败', error.message || String(error))}<div class="governance-danger">${escapeHtml(error.message || error)}</div>`;
    } finally {
      rendering = false;
    }
  }

  const observer = new MutationObserver(() => window.setTimeout(() => renderCurrent(), 0));
  observer.observe(workspace, { childList: true, subtree: true });
  window.addEventListener('hashchange', () => window.setTimeout(() => renderCurrent(true), 0));

  document.addEventListener('change', async (event) => {
    if (event.target.id !== 'governance-persona') return;
    const root = route().root;
    location.hash = `#/${root}?persona=${encodeURIComponent(event.target.value)}`;
  }, true);

  document.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-governance-action]');
    if (!target) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      const action = target.dataset.governanceAction;
      if (action === 'dialog-close') closeDialog();
      else if (action === 'filter') {
        if (target.dataset.kind === 'memory') memoryFilter = target.dataset.filter;
        else sessionFilter = target.dataset.filter;
        await renderCurrent(true);
      } else if (action === 'memory-policy-save') await savePolicy('memory');
      else if (action === 'session-policy-save') await savePolicy('sessions');
      else if (action === 'memory-collect') await collect('memory');
      else if (action === 'session-collect') await collect('sessions');
      else if (action === 'memory-approve') await memoryReview(target.dataset.id, true, target.dataset.scope);
      else if (action === 'memory-reject') await memoryReview(target.dataset.id, false);
      else if (action === 'conflict-resolve') await resolveConflict(target.dataset.id, target.dataset.resolution);
      else if (action === 'session-approve') await sessionReview(target.dataset.id, true, target.dataset.scope);
      else if (action === 'session-reject') await sessionReview(target.dataset.id, false);
      else if (action === 'memory-apply-dialog') showApplyDialog('memory');
      else if (action === 'session-apply-dialog') showApplyDialog('sessions');
      else if (action === 'apply-confirm') await applyPlan(target.dataset.kind);
      else if (action === 'manual-dialog') showManualDialog();
      else if (action === 'manual-save') await saveManual();
      else if (action === 'raw-preview-dialog') showRawPreviewDialog();
      else if (action === 'raw-preview-confirm') await rawPreview();
    } catch (error) {
      toast(error.message || String(error), 'error');
    }
  }, true);

  renderCurrent();
})();
