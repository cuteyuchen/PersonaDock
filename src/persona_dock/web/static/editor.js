(() => {
  'use strict';

  const workspace = document.getElementById('workspace');
  const dialogRoot = document.getElementById('dialog-root');
  const toastRegion = document.getElementById('toast-region');
  let editorState = null;
  let rendering = false;

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function attr(value) {
    return escapeHtml(value);
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
    window.setTimeout(() => item.remove(), 4500);
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

  function statusBadge(status, label = null) {
    return `<span class="status ${attr(status)}">${escapeHtml(label || status)}</span>`;
  }

  function pageHeader(kicker, title, summary, actions = '') {
    return `<header class="page-header"><div><div class="page-kicker">${escapeHtml(kicker)}</div><h1>${escapeHtml(title)}</h1><p class="page-summary">${escapeHtml(summary)}</p></div>${actions ? `<div class="actions">${actions}</div>` : ''}</header>`;
  }

  function emptyState(title, text) {
    return `<div class="empty-state"><strong>${escapeHtml(title)}</strong>${escapeHtml(text)}</div>`;
  }

  function routeParts() {
    return location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  }

  function phase3Route() {
    const parts = routeParts();
    if (parts[0] === 'diff') return { kind: 'diff' };
    if (parts[0] !== 'personas' || !parts[1] || !parts[2]) return null;
    if (['editor', 'revisions', 'tests'].includes(parts[2])) {
      return { kind: parts[2], personaId: parts[1] };
    }
    return null;
  }

  function setPageTitle(value) {
    document.getElementById('route-title').textContent = value;
    document.title = `${value} · PersonaDock`;
  }

  function enhancePersonaDetail() {
    const parts = routeParts();
    if (parts[0] !== 'personas' || !parts[1] || parts[2]) return;
    const personaId = parts[1];
    const phaseButton = document.querySelector('[data-action="phase-info"][data-phase="3"]');
    if (phaseButton) {
      phaseButton.outerHTML = `<a class="button" href="#/personas/${attr(personaId)}/tests">验证与测试</a><a class="button" href="#/personas/${attr(personaId)}/revisions">版本与差异</a>`;
    }
    const canonical = document.querySelector('a.button[href="/canonical"]');
    if (canonical) {
      canonical.href = `#/personas/${encodeURIComponent(personaId)}/editor`;
      canonical.textContent = '编辑 Canonical';
      canonical.classList.add('primary');
    }
  }

  function showDialog(title, body, footer = '') {
    dialogRoot.innerHTML = `<div class="dialog-backdrop"><section class="dialog" role="dialog" aria-modal="true"><header class="dialog-header"><h2>${escapeHtml(title)}</h2><button class="icon-button" data-editor-action="dialog-close" type="button">×</button></header><div class="dialog-body">${body}</div>${footer ? `<footer class="dialog-footer">${footer}</footer>` : ''}</section></div>`;
  }

  function closeDialog() {
    dialogRoot.innerHTML = '';
  }

  function lines(value) {
    return Array.isArray(value) ? value.join('\n') : '';
  }

  function values(value) {
    return String(value || '').split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  }

  function editorTabs(active) {
    const tabs = [
      ['structured', '结构化'],
      ['source', 'JSON'],
      ['preview', '编译预览'],
    ];
    return `<div class="tabs">${tabs.map(([id, label]) => `<button class="tab ${active === id ? 'active' : ''}" data-editor-action="tab" data-tab="${id}" type="button">${label}</button>`).join('')}</div>`;
  }

  function renderStructured(model) {
    const behaviors = model.behaviors || [];
    const boundaries = model.boundaries || [];
    return `<div class="editor-form">
      <section class="panel"><header class="panel-header"><div class="panel-title"><h2>基础信息</h2><p>ID 在创建后不可修改</p></div><span class="status">Schema v${escapeHtml(model.schema_version)}</span></header><div class="panel-body"><div class="form-grid">
        <div class="field"><label>Persona ID</label><input class="input" value="${attr(model.id)}" disabled></div>
        <div class="field"><label for="edit-version">版本</label><input class="input" id="edit-version" value="${attr(model.version)}"></div>
        <div class="field"><label for="edit-name">显示名称</label><input class="input" id="edit-name" value="${attr(model.name)}"></div>
        <div class="field"><label>语言</label><input class="input" value="${attr(model.locale)}" disabled></div>
        <div class="field" style="grid-column:1/-1"><label for="edit-summary">摘要</label><textarea class="textarea compact" id="edit-summary">${escapeHtml(model.summary)}</textarea></div>
      </div></div></section>
      <section class="panel"><header class="panel-header"><div class="panel-title"><h2>身份与表达</h2><p>稳定身份、核心特征和表达原则</p></div></header><div class="panel-body"><div class="form-grid">
        <div class="field" style="grid-column:1/-1"><label for="edit-identity">身份陈述</label><textarea class="textarea compact" id="edit-identity">${escapeHtml(model.identity?.statement)}</textarea></div>
        <div class="field"><label for="edit-traits">核心特征</label><textarea class="textarea" id="edit-traits">${escapeHtml(lines(model.identity?.core_traits))}</textarea><div class="field-help">每行一个特征</div></div>
        <div class="field"><label for="edit-voice">表达风格</label><textarea class="textarea" id="edit-voice">${escapeHtml(model.voice?.style)}</textarea></div>
        <div class="field" style="grid-column:1/-1"><label for="edit-principles">表达原则</label><textarea class="textarea" id="edit-principles">${escapeHtml(lines(model.voice?.principles))}</textarea><div class="field-help">每行一个原则</div></div>
      </div></div></section>
      <div class="grid-equal">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>行为规则</h2><p>复杂字段可在 JSON 模式完整编辑</p></div><span class="status">${behaviors.length}</span></header><div class="list">${behaviors.map((item) => `<div class="list-row"><div class="list-primary"><div class="list-title code">${escapeHtml(item.id)}</div><div class="list-meta">${escapeHtml(item.trigger?.intent || 'general')} · ${(item.behavior || []).map(escapeHtml).join('；')}</div></div>${statusBadge(item.priority)}</div>`).join('') || emptyState('没有行为规则', '请在 JSON 模式中添加。')}</div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>边界</h2><p>高风险字段修改会在保存后标记</p></div><span class="status">${boundaries.length}</span></header><div class="list">${boundaries.map((item) => `<div class="list-row"><div class="list-primary"><div class="list-title">${escapeHtml(item.rule)}</div><div class="list-meta code">${escapeHtml(item.id)}</div></div>${statusBadge(item.priority)}</div>`).join('') || emptyState('没有边界', '请在 JSON 模式中添加。')}</div></section>
      </div>
    </div>`;
  }

  function renderSource(model) {
    return `<section class="panel"><header class="panel-header"><div class="panel-title"><h2>Canonical Persona JSON</h2><p>保存时会执行 normalize、Schema 校验和场景测试</p></div><button class="button small" data-editor-action="format-json" type="button">格式化</button></header><div class="panel-body"><textarea class="source-editor" id="canonical-source" spellcheck="false">${escapeHtml(JSON.stringify(model, null, 2))}</textarea></div></section>`;
  }

  function renderPreview(preview) {
    return `<div class="grid-equal">
      <section class="panel"><header class="panel-header"><div class="panel-title"><h2>SOUL.md</h2><p>${escapeHtml(preview.soul_chars)} 字符 · 目标 ${escapeHtml(preview.target_chars || '—')} · 上限 ${escapeHtml(preview.hard_limit_chars || '—')}</p></div></header><pre class="mono-box preview-box">${escapeHtml(preview.soul)}</pre></section>
      <section class="panel"><header class="panel-header"><div class="panel-title"><h2>Persona Skill</h2><p>${(preview.targets || []).map(escapeHtml).join(' / ')}</p></div></header><pre class="mono-box preview-box">${escapeHtml(preview.skill)}</pre></section>
    </div>`;
  }

  async function renderEditor(personaId) {
    const [persona, canonical, preview] = await Promise.all([
      api(`/api/v1/personas/${encodeURIComponent(personaId)}`),
      api(`/api/v1/personas/${encodeURIComponent(personaId)}/canonical`),
      api(`/api/v1/personas/${encodeURIComponent(personaId)}/compile-preview`),
    ]);
    editorState = {
      personaId,
      model: canonical.model,
      originalHash: canonical.content_hash,
      preview,
      tab: 'structured',
    };
    setPageTitle(`${persona.name} · 编辑`);
    renderEditorBody(persona);
  }

  function renderEditorBody(persona = null) {
    if (!editorState) return;
    const model = editorState.model;
    const title = persona?.name || model.name;
    workspace.innerHTML = `<div data-phase3-view="editor">
      ${pageHeader('Canonical Editor', `${title} · 编辑`, '保存会自动创建 Revision、运行校验和场景测试，并返回语义差异与风险级别。', `<a class="button" href="#/personas/${attr(editorState.personaId)}">返回详情</a><a class="button" href="#/personas/${attr(editorState.personaId)}/revisions">版本历史</a><button class="button primary" data-editor-action="save" type="button">保存 Revision</button>`)}
      <div class="editor-toolbar">${editorTabs(editorState.tab)}<div class="editor-toolbar-spacer"></div><span class="code">${escapeHtml(editorState.originalHash.slice(0, 12))}</span></div>
      <div id="editor-content">${editorState.tab === 'structured' ? renderStructured(model) : editorState.tab === 'source' ? renderSource(model) : renderPreview(editorState.preview)}</div>
    </div>`;
  }

  function syncStructuredModel() {
    if (!editorState || editorState.tab !== 'structured') return;
    const model = editorState.model;
    model.version = document.getElementById('edit-version')?.value.trim() || model.version;
    model.name = document.getElementById('edit-name')?.value.trim() || model.name;
    model.summary = document.getElementById('edit-summary')?.value.trim() || '';
    model.identity.statement = document.getElementById('edit-identity')?.value.trim() || '';
    model.identity.core_traits = values(document.getElementById('edit-traits')?.value);
    model.voice.style = document.getElementById('edit-voice')?.value.trim() || '';
    model.voice.principles = values(document.getElementById('edit-principles')?.value);
  }

  function syncSourceModel() {
    if (!editorState || editorState.tab !== 'source') return;
    const source = document.getElementById('canonical-source')?.value || '';
    editorState.model = JSON.parse(source);
  }

  async function switchTab(tab) {
    if (!editorState || tab === editorState.tab) return;
    if (editorState.tab === 'structured') syncStructuredModel();
    if (editorState.tab === 'source') syncSourceModel();
    editorState.tab = tab;
    if (tab === 'preview') {
      // Preview reflects the last validated on-disk Revision. Unsaved changes are intentionally not compiled.
      editorState.preview = await api(`/api/v1/personas/${encodeURIComponent(editorState.personaId)}/compile-preview`);
    }
    renderEditorBody();
  }

  async function saveEditor() {
    if (!editorState) return;
    if (editorState.tab === 'structured') syncStructuredModel();
    if (editorState.tab === 'source') syncSourceModel();
    showDialog('保存 Revision', `<div class="field"><label for="revision-summary">修改摘要</label><input class="input" id="revision-summary" placeholder="例如：调整表达风格并补充边界"><div class="field-help">摘要会进入 Revision 历史和审计日志。</div></div>`, '<button class="button" data-editor-action="dialog-close" type="button">取消</button><button class="button primary" data-editor-action="save-confirm" type="button">校验并保存</button>');
  }

  async function confirmSave() {
    if (!editorState) return;
    const summary = document.getElementById('revision-summary')?.value.trim() || '保存 Canonical Persona';
    const result = await api(`/api/v1/personas/${encodeURIComponent(editorState.personaId)}/canonical`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: editorState.model, summary, source: 'manual' }),
    });
    closeDialog();
    editorState.model = result.model;
    editorState.originalHash = result.revision.content_hash;
    editorState.preview = await api(`/api/v1/personas/${encodeURIComponent(editorState.personaId)}/compile-preview`);
    renderEditorBody();
    const risk = result.diff?.risk || { level: 'none', reasons: [] };
    showDiffDialog('Revision 已保存', result.diff, `<div class="notice ${risk.level === 'high' ? 'warning' : ''}">风险：${escapeHtml(risk.level)}${risk.reasons?.length ? ` · ${risk.reasons.map(escapeHtml).join('；')}` : ''}</div>`);
  }

  function diffRows(diff) {
    const groups = [
      ['新增行为', diff.added_behaviors], ['删除行为', diff.removed_behaviors], ['修改行为', diff.changed_behaviors],
      ['新增边界', diff.added_boundaries], ['删除边界', diff.removed_boundaries], ['修改边界', diff.changed_boundaries],
    ];
    const rows = groups.filter(([, items]) => items?.length).map(([label, items]) => `<div class="diff-row"><strong>${escapeHtml(label)}</strong><span>${items.map((item) => `<code>${escapeHtml(item)}</code>`).join(' ')}</span></div>`);
    for (const item of diff.field_changes || []) {
      rows.push(`<div class="diff-row"><strong>${escapeHtml(item.path)}</strong><span><del>${escapeHtml(JSON.stringify(item.before))}</del><ins>${escapeHtml(JSON.stringify(item.after))}</ins></span></div>`);
    }
    return rows.join('') || emptyState('没有语义变化', '两个版本的 Canonical 内容一致。');
  }

  function showDiffDialog(title, diff, preamble = '') {
    const risk = diff.risk || { level: 'none', reasons: [] };
    showDialog(title, `${preamble}<div class="diff-summary"><span>${statusBadge(risk.level, `风险 ${risk.level}`)}</span><span class="code">${escapeHtml((diff.before_hash || '').slice(0, 12))} → ${escapeHtml((diff.after_hash || '').slice(0, 12))}</span></div><div class="diff-list">${diffRows(diff)}</div>`, '<button class="button primary" data-editor-action="dialog-close" type="button">关闭</button>');
  }

  async function renderRevisions(personaId) {
    const [persona, result] = await Promise.all([
      api(`/api/v1/personas/${encodeURIComponent(personaId)}`),
      api(`/api/v1/personas/${encodeURIComponent(personaId)}/revisions`),
    ]);
    setPageTitle(`${persona.name} · 版本`);
    const revisions = result.items || [];
    const options = [`<option value="current">当前工程</option>`, ...revisions.map((item) => `<option value="${attr(item.revision_id)}">${escapeHtml(formatDate(item.created_at))} · ${escapeHtml(item.summary || item.source)}</option>`)].join('');
    workspace.innerHTML = `<div data-phase3-view="revisions">
      ${pageHeader('Revision Store', `${persona.name} · 版本与差异`, 'Revision 是确定性 Canonical 快照；恢复前必须生成基于当前内容哈希的计划。', `<a class="button" href="#/personas/${attr(personaId)}">返回详情</a><a class="button primary" href="#/personas/${attr(personaId)}/editor">编辑人格</a>`)}
      <section class="panel" style="margin-bottom:16px"><header class="panel-header"><div class="panel-title"><h2>比较版本</h2><p>可比较任意 Revision 与当前工程</p></div></header><div class="panel-body"><div class="compare-bar"><div class="field"><label>之前</label><select class="select" id="diff-before">${options}</select></div><div class="compare-arrow">→</div><div class="field"><label>之后</label><select class="select" id="diff-after">${options}</select></div><button class="button primary" data-editor-action="revision-diff" data-persona-id="${attr(personaId)}" type="button">比较</button></div></div></section>
      <section class="panel"><header class="panel-header"><div class="panel-title"><h2>Revision 历史</h2><p>当前内容 ${escapeHtml(result.current_hash.slice(0, 12))}</p></div><span class="status">${revisions.length}</span></header><div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>时间</th><th>摘要</th><th>来源</th><th>内容</th><th>测试</th><th></th></tr></thead><tbody>${revisions.map((item) => `<tr><td>${formatDate(item.created_at)}</td><td>${escapeHtml(item.summary || '—')}</td><td>${statusBadge(item.source)}</td><td class="code">${escapeHtml(item.content_hash.slice(0, 12))}</td><td>${item.test_result?.ok === true ? statusBadge('success', '通过') : item.test_result?.ok === false ? statusBadge('failed', '失败') : '—'}</td><td><button class="button small" data-editor-action="revision-view" data-persona-id="${attr(personaId)}" data-revision-id="${attr(item.revision_id)}" type="button">查看</button> <button class="button small" data-editor-action="restore-preview" data-persona-id="${attr(personaId)}" data-revision-id="${attr(item.revision_id)}" type="button">恢复</button></td></tr>`).join('') || `<tr><td colspan="6">${emptyState('暂无 Revision', '打开编辑器保存一次后会创建正式 Revision。')}</td></tr>`}</tbody></table></div></section>
    </div>`;
  }

  async function compareRevisions(personaId) {
    const before = document.getElementById('diff-before')?.value || 'current';
    const after = document.getElementById('diff-after')?.value || 'current';
    const diff = await api(`/api/v1/personas/${encodeURIComponent(personaId)}/diff`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ before_revision_id: before, after_revision_id: after }),
    });
    showDiffDialog('Revision 差异', diff);
  }

  async function viewRevision(personaId, revisionId) {
    const value = await api(`/api/v1/personas/${encodeURIComponent(personaId)}/revisions/${encodeURIComponent(revisionId)}`);
    showDialog('Revision 内容', `<div class="diff-summary"><span>${statusBadge(value.revision.source)}</span><span>${escapeHtml(formatDate(value.revision.created_at))}</span><span class="code">${escapeHtml(value.revision.content_hash)}</span></div><pre class="mono-box preview-box">${escapeHtml(JSON.stringify(value.model, null, 2))}</pre>`, '<button class="button primary" data-editor-action="dialog-close" type="button">关闭</button>');
  }

  async function previewRestore(personaId, revisionId) {
    const value = await api(`/api/v1/personas/${encodeURIComponent(personaId)}/revisions/${encodeURIComponent(revisionId)}/restore/preview`, { method: 'POST' });
    const plan = value.plan;
    showDialog('恢复 Revision', `<div class="notice warning">恢复会替换当前 Canonical 文件并立即校验。若文件在预览后发生变化，此计划会失效。</div><div class="diff-summary" style="margin-top:14px"><span class="code">当前 ${escapeHtml(plan.current_hash.slice(0, 12))}</span><span>→</span><span class="code">目标 ${escapeHtml(plan.target_hash.slice(0, 12))}</span></div><div class="diff-list">${diffRows(value.diff)}</div>`, `<button class="button" data-editor-action="dialog-close" type="button">取消</button><button class="button danger" data-editor-action="restore-confirm" data-persona-id="${attr(personaId)}" data-revision-id="${attr(revisionId)}" data-plan-hash="${attr(plan.plan_hash)}" type="button">确认恢复</button>`);
  }

  async function confirmRestore(target) {
    const personaId = target.dataset.personaId;
    const revisionId = target.dataset.revisionId;
    await api(`/api/v1/personas/${encodeURIComponent(personaId)}/revisions/${encodeURIComponent(revisionId)}/restore`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_hash: target.dataset.planHash, summary: '从 Web 恢复历史 Revision' }),
    });
    closeDialog();
    toast('Revision 已恢复并创建新的恢复记录');
    await renderRevisions(personaId);
  }

  async function renderTests(personaId) {
    const [persona, validation, preview] = await Promise.all([
      api(`/api/v1/personas/${encodeURIComponent(personaId)}`),
      api(`/api/v1/personas/${encodeURIComponent(personaId)}/validation`),
      api(`/api/v1/personas/${encodeURIComponent(personaId)}/compile-preview`),
    ]);
    setPageTitle(`${persona.name} · 测试`);
    workspace.innerHTML = `<div data-phase3-view="tests">
      ${pageHeader('Quality Gate', `${persona.name} · 验证与测试`, '验证 Canonical 工程、运行确定性场景测试，并检查编译后 SOUL 的字符预算。', `<a class="button" href="#/personas/${attr(personaId)}">返回详情</a><button class="button primary" data-editor-action="run-tests" data-persona-id="${attr(personaId)}" type="button">运行场景测试</button>`)}
      <div class="grid-two"><section class="panel"><header class="panel-header"><div class="panel-title"><h2>工程验证</h2><p>Schema、文件和引用完整性</p></div>${validation.ok ? statusBadge('success', '通过') : statusBadge('failed', '失败')}</header><div class="panel-body">${validation.ok ? '<div class="notice">Canonical Persona 工程验证通过。</div>' : `<div class="diff-list">${validation.errors.map((item) => `<div class="diff-row"><strong>错误</strong><span>${escapeHtml(item)}</span></div>`).join('')}</div>`}</div></section><section class="panel"><header class="panel-header"><div class="panel-title"><h2>编译预算</h2><p>SOUL.md 静态预览</p></div>${preview.soul_chars <= preview.hard_limit_chars ? statusBadge('success', '预算内') : statusBadge('failed', '超出')}</header><div class="panel-body"><div class="stat-strip compact-stats">${['soul_chars','target_chars','hard_limit_chars'].map((key) => `<div class="stat-cell"><div class="stat-label">${key}</div><div class="stat-value">${escapeHtml(preview[key] || 0)}</div></div>`).join('')}</div><div class="legacy-links">${(preview.targets || []).map((item) => `<span class="legacy-link">${escapeHtml(item)}</span>`).join('')}</div></div></section></div>
      <section class="panel" style="margin-top:16px" id="test-results"><div class="empty-state"><strong>尚未运行场景测试</strong>点击右上角运行，结果会记录到任务中心。</div></section>
    </div>`;
  }

  async function runTests(personaId) {
    const value = await api(`/api/v1/personas/${encodeURIComponent(personaId)}/tests`, { method: 'POST' });
    const result = value.result;
    document.getElementById('test-results').innerHTML = `<header class="panel-header"><div class="panel-title"><h2>场景测试</h2><p>通过 ${escapeHtml(result.passed)}，失败 ${escapeHtml(result.failed)}</p></div>${result.ok ? statusBadge('success', '全部通过') : statusBadge('failed', '存在失败')}</header><div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>场景</th><th>状态</th><th>说明</th><th>关联行为</th></tr></thead><tbody>${result.results.map((item) => `<tr><td class="code">${escapeHtml(item.id)}</td><td>${item.passed ? statusBadge('success', '通过') : statusBadge('failed', '失败')}</td><td>${escapeHtml(item.message)}</td><td>${(item.linked_behaviors || []).map((id) => `<code>${escapeHtml(id)}</code>`).join(' ') || '—'}</td></tr>`).join('')}</tbody></table></div>`;
    toast(result.ok ? '场景测试全部通过' : '场景测试存在失败', result.ok ? 'info' : 'error');
  }

  async function renderGlobalDiff() {
    const personas = await api('/api/personas');
    setPageTitle('差异中心');
    const options = personas.map((item) => `<option value="${attr(item.id)}">${escapeHtml(item.name)} (${escapeHtml(item.id)})</option>`).join('');
    workspace.innerHTML = `<div data-phase3-view="diff">${pageHeader('Semantic Diff', '差异中心', '比较两个已注册 Canonical Persona；版本内比较请进入对应 Persona 的 Revision 页面。')}<section class="panel"><header class="panel-header"><div class="panel-title"><h2>Persona 对比</h2><p>行为、边界和关键字段的语义差异</p></div></header><div class="panel-body">${personas.length >= 2 ? `<div class="compare-bar"><div class="field"><label>之前</label><select class="select" id="persona-diff-before">${options}</select></div><div class="compare-arrow">→</div><div class="field"><label>之后</label><select class="select" id="persona-diff-after">${options}</select></div><button class="button primary" data-editor-action="persona-diff" type="button">比较</button></div>` : '<div class="notice warning">至少需要两个已注册 Persona 才能进行跨人格对比。</div>'}</div></section><section class="panel" style="margin-top:16px" id="global-diff-result">${emptyState('尚未比较', '选择两个 Persona 后查看语义变化。')}</section></div>`;
  }

  async function comparePersonas() {
    const before = document.getElementById('persona-diff-before')?.value;
    const after = document.getElementById('persona-diff-after')?.value;
    if (!before || !after) throw new Error('请选择两个 Persona');
    const diff = await api('/api/personas/diff', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ before_persona_id: before, after_persona_id: after }) });
    document.getElementById('global-diff-result').innerHTML = `<header class="panel-header"><div class="panel-title"><h2>比较结果</h2><p>${escapeHtml(before)} → ${escapeHtml(after)}</p></div>${diff.changed ? statusBadge('warning', '有变化') : statusBadge('success', '一致')}</header><div class="panel-body"><div class="diff-list">${diffRows(diff)}</div></div>`;
  }

  async function renderPhase3() {
    const route = phase3Route();
    if (!route || rendering) {
      enhancePersonaDetail();
      return;
    }
    const marker = workspace.querySelector(`[data-phase3-view="${route.kind}"]`);
    if (marker) return;
    rendering = true;
    try {
      if (route.kind === 'editor') await renderEditor(route.personaId);
      else if (route.kind === 'revisions') await renderRevisions(route.personaId);
      else if (route.kind === 'tests') await renderTests(route.personaId);
      else if (route.kind === 'diff') await renderGlobalDiff();
    } catch (error) {
      workspace.innerHTML = `<div data-phase3-view="${attr(route.kind)}">${pageHeader('Error', '页面加载失败', error.message || String(error))}<section class="panel"><div class="panel-body"><div class="notice danger">${escapeHtml(error.message || error)}</div></div></section></div>`;
    } finally {
      rendering = false;
    }
  }

  const observer = new MutationObserver(() => {
    enhancePersonaDetail();
    window.setTimeout(renderPhase3, 0);
  });
  observer.observe(workspace, { childList: true, subtree: true });
  window.addEventListener('hashchange', () => {
    editorState = null;
    window.setTimeout(renderPhase3, 0);
  });

  document.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-editor-action]');
    if (!target) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const action = target.dataset.editorAction;
    try {
      if (action === 'dialog-close') closeDialog();
      else if (action === 'tab') await switchTab(target.dataset.tab);
      else if (action === 'format-json') {
        syncSourceModel();
        document.getElementById('canonical-source').value = JSON.stringify(editorState.model, null, 2);
      }
      else if (action === 'save') await saveEditor();
      else if (action === 'save-confirm') await confirmSave();
      else if (action === 'revision-diff') await compareRevisions(target.dataset.personaId);
      else if (action === 'revision-view') await viewRevision(target.dataset.personaId, target.dataset.revisionId);
      else if (action === 'restore-preview') await previewRestore(target.dataset.personaId, target.dataset.revisionId);
      else if (action === 'restore-confirm') await confirmRestore(target);
      else if (action === 'run-tests') await runTests(target.dataset.personaId);
      else if (action === 'persona-diff') await comparePersonas();
    } catch (error) {
      toast(error.message || String(error), 'error');
    }
  }, true);

  enhancePersonaDetail();
  renderPhase3();
})();
