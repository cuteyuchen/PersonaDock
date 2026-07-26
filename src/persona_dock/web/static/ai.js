(() => {
  'use strict';

  const workspace = document.getElementById('workspace');
  const dialogRoot = document.getElementById('dialog-root');
  const toastRegion = document.getElementById('toast-region');
  let rendering = false;
  let aiMode = 'create';
  let targetExisting = false;
  let resultTab = 'canonical';
  let currentGeneration = null;
  let editingProvider = null;
  const formState = {
    provider_id: '', persona_id: '', requested_persona_id: '', requested_name: '',
    locale: 'zh-CN', instruction: '', evidence: '',
  };

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  }
  function attr(value) { return escapeHtml(value); }
  function authToken() { return sessionStorage.getItem('personadock.web.token') || ''; }
  function headers(extra = {}) {
    const token = authToken();
    return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: headers(options.headers || {}) });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json();
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body);
      } catch (_) {}
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
    window.setTimeout(() => item.remove(), 4800);
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
  function route() {
    const raw = location.hash.replace(/^#\/?/, '');
    const [path] = raw.split('?');
    return path.split('/').filter(Boolean).map(decodeURIComponent)[0] || 'overview';
  }
  function showDialog(title, body, footer = '') {
    dialogRoot.innerHTML = `<div class="dialog-backdrop"><section class="dialog" role="dialog" aria-modal="true"><header class="dialog-header"><h2>${escapeHtml(title)}</h2><button class="icon-button" data-ai-action="dialog-close" type="button">×</button></header><div class="dialog-body">${body}</div>${footer ? `<footer class="dialog-footer">${footer}</footer>` : ''}</section></div>`;
  }
  function closeDialog() { dialogRoot.innerHTML = ''; editingProvider = null; }
  function formatDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date);
  }

  function readFormState() {
    for (const key of Object.keys(formState)) {
      const element = document.getElementById(`ai-${key.replaceAll('_', '-')}`);
      if (element) formState[key] = element.value;
    }
  }
  function modeLabel(mode) {
    return ({ create: '新建', refine: '优化', distill: '蒸馏', hybrid: '混合' })[mode] || mode;
  }
  function providerOptions(providers) {
    return providers.map((item) => `<option value="${attr(item.id)}" ${item.id === formState.provider_id ? 'selected' : ''}>${escapeHtml(item.name)} · ${escapeHtml(item.model)}</option>`).join('');
  }
  function personaOptions(personas) {
    return personas.map((item) => `<option value="${attr(item.id)}" ${item.id === formState.persona_id ? 'selected' : ''}>${escapeHtml(item.name)} (${escapeHtml(item.id)})</option>`).join('');
  }
  function targetFields(personas) {
    const existing = aiMode === 'refine' || ((aiMode === 'distill' || aiMode === 'hybrid') && targetExisting);
    if (existing) {
      return `<div class="field"><label>目标 Persona</label><select class="select" id="ai-persona-id"><option value="">选择 Persona</option>${personaOptions(personas)}</select></div>`;
    }
    return `<div class="form-grid"><div class="field"><label>Persona ID</label><input class="input" id="ai-requested-persona-id" value="${attr(formState.requested_persona_id)}" placeholder="lowercase-id"></div><div class="field"><label>名称</label><input class="input" id="ai-requested-name" value="${attr(formState.requested_name)}" placeholder="人格名称"></div><div class="field"><label>Locale</label><input class="input" id="ai-locale" value="${attr(formState.locale)}"></div></div>`;
  }
  function modeHelp(mode) {
    return ({
      create: '根据明确设计创建新的 Canonical Persona。',
      refine: '基于现有人格生成完整修订草稿，不直接覆盖。',
      distill: '从本次提供的材料提取可审核规则；原文不写入历史。',
      hybrid: '明确设计优先，并用本次证据补充可审核行为。',
    })[mode];
  }

  function diffRows(diff) {
    const rows = [];
    for (const item of diff.field_changes || []) rows.push(['字段', `${item.path}: ${JSON.stringify(item.before)} → ${JSON.stringify(item.after)}`]);
    for (const key of ['added_behaviors', 'removed_behaviors', 'changed_behaviors', 'added_boundaries', 'removed_boundaries', 'changed_boundaries']) {
      for (const item of diff[key] || []) rows.push([key.replaceAll('_', ' '), typeof item === 'string' ? item : JSON.stringify(item)]);
    }
    if (!rows.length) return emptyState('没有语义变化', 'AI 草稿与基线内容一致。');
    return `<div class="ai-diff-list">${rows.map(([kind, value]) => `<div class="ai-diff-row"><div class="ai-diff-kind">${escapeHtml(kind)}</div><div class="ai-diff-value">${escapeHtml(value)}</div></div>`).join('')}</div>`;
  }
  function compileText(preview) {
    const files = preview?.files || {};
    const sections = [];
    for (const [path, content] of Object.entries(files)) sections.push(`===== ${path} =====\n${content}`);
    return sections.join('\n\n') || JSON.stringify(preview || {}, null, 2);
  }
  function resultPane(generation) {
    if (!generation) return emptyState('尚无草稿', '配置 Provider，填写任务后生成可审核的 Persona 草稿。');
    const risk = generation.diff?.risk || { level: 'none', reasons: [] };
    const tabs = [
      ['canonical', 'Canonical JSON'], ['diff', '语义 Diff'], ['preview', '编译预览'], ['tests', '验证与测试'],
    ];
    const usage = generation.usage || {};
    const promptTokens = usage.prompt_tokens ?? usage.input_tokens ?? usage.promptTokenCount ?? '—';
    const completionTokens = usage.completion_tokens ?? usage.output_tokens ?? usage.candidatesTokenCount ?? '—';
    return `<div>
      <div class="ai-result-header"><div><strong>${escapeHtml(modeLabel(generation.mode))}草稿</strong><div class="list-meta code">${escapeHtml(generation.id)}</div></div><div class="ai-result-status">${statusBadge(generation.status)}${statusBadge(generation.validation?.valid ? 'success' : 'error', generation.validation?.valid ? 'Schema 有效' : 'Schema 失败')}${statusBadge(risk.level, `风险 ${risk.level}`)}</div></div>
      <div class="ai-risk ${attr(risk.level)}">${escapeHtml((risk.reasons || []).join('；') || '未检测到风险变化')}</div>
      <div class="panel-header"><div class="ai-result-tabs">${tabs.map(([id, label]) => `<button class="button small ${resultTab === id ? 'active' : ''}" data-ai-action="result-tab" data-tab="${id}" type="button">${label}</button>`).join('')}</div></div>
      <div class="ai-result-body">
        <div class="ai-pane ${resultTab === 'canonical' ? 'active' : ''}" data-ai-pane="canonical"><pre class="ai-json">${escapeHtml(JSON.stringify(generation.draft || {}, null, 2))}</pre></div>
        <div class="ai-pane ${resultTab === 'diff' ? 'active' : ''}" data-ai-pane="diff">${diffRows(generation.diff || {})}</div>
        <div class="ai-pane ${resultTab === 'preview' ? 'active' : ''}" data-ai-pane="preview"><pre class="ai-preview">${escapeHtml(compileText(generation.compile_preview))}</pre></div>
        <div class="ai-pane ${resultTab === 'tests' ? 'active' : ''}" data-ai-pane="tests"><pre class="ai-preview">${escapeHtml(JSON.stringify({ validation: generation.validation, tests: generation.tests }, null, 2))}</pre></div>
      </div>
      <div class="ai-usage"><div><span>Prompt tokens</span><strong>${escapeHtml(promptTokens)}</strong></div><div><span>Output tokens</span><strong>${escapeHtml(completionTokens)}</strong></div><div><span>Prompt hash</span><strong class="code">${escapeHtml((generation.prompt_hash || '').slice(0, 16))}</strong></div></div>
      ${generation.status === 'draft' ? `<div class="ai-apply-bar"><p>应用只会创建或更新 Persona Revision，不会自动部署、同步 Memory 或传播 Session。</p><button class="button primary" data-ai-action="apply-dialog" type="button">应用已审核草稿</button></div>` : ''}
    </div>`;
  }
  function historyRows(items) {
    if (!items.length) return `<tr><td colspan="6">${emptyState('没有生成历史', '成功或失败的生成任务会显示在这里，但不保存原始输入。')}</td></tr>`;
    return items.map((item) => `<tr class="ai-history-row" data-ai-action="select-generation" data-id="${attr(item.id)}"><td><strong>${escapeHtml(item.requested_name || item.persona_id || item.requested_persona_id || 'Persona')}</strong><div class="list-meta code">${escapeHtml(item.id)}</div></td><td>${escapeHtml(modeLabel(item.mode))}</td><td>${escapeHtml(item.provider_id)}</td><td>${statusBadge(item.status)}</td><td>${escapeHtml(item.diff?.risk?.level || '—')}</td><td>${formatDate(item.created_at)}</td></tr>`).join('');
  }

  async function renderStudio() {
    const [providerData, personas, generations] = await Promise.all([
      api('/api/v1/ai/providers'), api('/api/personas'), api('/api/v1/ai/generations?limit=50'),
    ]);
    const providers = providerData.items || [];
    if (!formState.provider_id && providers[0]) formState.provider_id = providers[0].id;
    if (!currentGeneration && generations.items?.length) currentGeneration = generations.items[0];
    setTitle('AI 人格工作室');
    const evidenceVisible = aiMode === 'distill' || aiMode === 'hybrid';
    const targetSwitcher = evidenceVisible ? `<div class="field"><label>应用目标</label><div class="ai-mode-tabs"><button class="button small ${!targetExisting ? 'active' : ''}" data-ai-action="target-mode" data-existing="false" type="button">新 Persona</button><button class="button small ${targetExisting ? 'active' : ''}" data-ai-action="target-mode" data-existing="true" type="button">现有 Persona</button></div></div>` : '';
    workspace.innerHTML = `<div data-ai-view="studio" class="ai-shell">
      ${pageHeader('Reviewed Generation', 'AI 人格工作室', '模型只生成 Canonical Persona 草稿。Schema、测试、Diff 和编译预览通过后，仍需人工确认才能写入 Revision。', '<a class="button" href="#/settings">配置大模型</a>')}
      <div class="ai-layout">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>生成任务</h2><p>${escapeHtml(modeHelp(aiMode))}</p></div></header><div class="panel-body ai-form">
          <div class="field"><label>模式</label><div class="ai-mode-tabs">${['create', 'refine', 'distill', 'hybrid'].map((mode) => `<button class="button small ${aiMode === mode ? 'active' : ''}" data-ai-action="mode" data-mode="${mode}" type="button">${modeLabel(mode)}</button>`).join('')}</div></div>
          <div class="field"><label>Provider / Model</label><select class="select" id="ai-provider-id"><option value="">选择 Provider</option>${providerOptions(providers)}</select>${!providers.length ? '<div class="field-help">尚未配置 Provider，请先进入系统设置。</div>' : ''}</div>
          ${targetSwitcher}${targetFields(personas)}
          <div class="field"><label>明确设计或修改要求</label><textarea class="textarea ai-instruction" id="ai-instruction" placeholder="描述身份、性格、语气、边界、场景和不希望出现的行为">${escapeHtml(formState.instruction)}</textarea></div>
          ${evidenceVisible ? `<div class="field"><label>本次证据材料</label><textarea class="textarea ai-evidence" id="ai-evidence" placeholder="粘贴用户主动选择的聊天摘录或参考材料；生成后不保存原文">${escapeHtml(formState.evidence)}</textarea></div><div class="ai-privacy-note">证据只随本次请求发送给所选 Provider。PersonaDock 历史只保存输入哈希、Canonical 草稿和评估结果，不保存这段原文。</div>` : ''}
          <div class="form-actions"><button class="button primary" data-ai-action="generate" type="button" ${providers.length ? '' : 'disabled'}>生成并评估草稿</button></div>
        </div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>审查结果</h2><p>Canonical、Diff、编译产物与场景测试</p></div></header><div id="ai-result">${resultPane(currentGeneration)}</div></section>
      </div>
      <section class="panel"><header class="panel-header"><div class="panel-title"><h2>生成历史</h2><p>原始描述和证据不进入历史</p></div><span class="status">${generations.count || 0}</span></header><div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>目标</th><th>模式</th><th>Provider</th><th>状态</th><th>风险</th><th>时间</th></tr></thead><tbody>${historyRows(generations.items || [])}</tbody></table></div></section>
    </div>`;
  }

  function providerRows(items) {
    if (!items.length) return `<tr><td colspan="7">${emptyState('尚未配置大模型', '添加 OpenAI、兼容 API、Anthropic、Gemini 或 Ollama Provider。')}</td></tr>`;
    return items.map((item) => `<tr><td><strong>${escapeHtml(item.name)}</strong><div class="list-meta code">${escapeHtml(item.id)}</div></td><td><span class="status provider-kind">${escapeHtml(item.kind)}</span></td><td>${escapeHtml(item.model)}</td><td class="code">${escapeHtml(item.base_url)}</td><td>${item.secret_configured ? statusBadge('success', '已配置') : statusBadge('warning', item.kind === 'ollama' ? '可选' : '未配置')}</td><td>${item.structured_output ? 'JSON' : '文本'}</td><td><div class="provider-actions"><button class="button small" data-ai-action="provider-test" data-id="${attr(item.id)}" type="button">测试</button><button class="button small" data-ai-action="provider-models" data-id="${attr(item.id)}" type="button">模型</button><button class="button small" data-ai-action="provider-edit" data-id="${attr(item.id)}" type="button">编辑</button><button class="button small danger" data-ai-action="provider-delete" data-id="${attr(item.id)}" type="button">删除</button></div></td></tr>`).join('');
  }

  async function renderSettings() {
    const data = await api('/api/v1/ai/providers');
    setTitle('系统设置');
    workspace.innerHTML = `<div data-ai-view="settings" class="ai-shell">
      ${pageHeader('Local Control Plane', '系统设置', '管理大模型 Provider 与本地密钥边界。API Key 永不返回浏览器，也不写入普通数据库。', '<button class="button primary" data-ai-action="provider-add" type="button">添加 Provider</button>')}
      <div class="settings-grid"><section class="panel provider-table"><header class="panel-header"><div class="panel-title"><h2>大模型 Provider</h2><p>${data.count || 0} 个配置</p></div></header><div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>名称</th><th>类型</th><th>模型</th><th>Base URL</th><th>Secret</th><th>输出</th><th></th></tr></thead><tbody>${providerRows(data.items || [])}</tbody></table></div></section><aside class="stack"><section class="panel"><header class="panel-header"><div class="panel-title"><h2>密钥边界</h2><p>本地加密 Vault</p></div></header><div class="panel-body security-facts"><div class="security-fact"><strong>AES-256-GCM</strong><span>API Key 与自定义 Header 整体加密；主密钥与密文分离保存。</span></div><div class="security-fact"><strong>浏览器不可读</strong><span>Provider API 只返回 secret_configured，不返回密钥、Header 或 secret_ref。</span></div><div class="security-fact"><strong>生成输入不落库</strong><span>任务历史仅保存输入哈希，聊天证据和设计描述不写入 Job 或 Generation 表。</span></div><div class="security-fact"><strong>人工应用</strong><span>AI 草稿通过 Schema、测试和 Diff 后，仍需输入 APPLY；不会自动部署。</span></div></div></section><section class="panel"><header class="panel-header"><div class="panel-title"><h2>兼容范围</h2><p>REST Provider</p></div></header><div class="panel-body"><ul class="plan-list"><li>OpenAI 与 OpenAI-compatible Chat Completions</li><li>Anthropic Messages</li><li>Gemini generateContent</li><li>Ollama /api/chat</li></ul></div></section></aside></div>
    </div>`;
  }

  function providerDialog(provider = null) {
    editingProvider = provider;
    const headersValue = '';
    showDialog(provider ? '编辑 Provider' : '添加 Provider', `<div class="provider-form">
      <div class="form-grid"><div class="field"><label>名称</label><input class="input" id="provider-name" value="${attr(provider?.name || '')}"></div><div class="field"><label>类型</label><select class="select" id="provider-kind">${['openai', 'openai-compatible', 'anthropic', 'gemini', 'ollama'].map((kind) => `<option value="${kind}" ${provider?.kind === kind ? 'selected' : ''}>${kind}</option>`).join('')}</select></div><div class="field"><label>Base URL</label><input class="input" id="provider-base-url" value="${attr(provider?.base_url || '')}" placeholder="留空使用默认地址"></div><div class="field"><label>Model</label><input class="input" id="provider-model" value="${attr(provider?.model || '')}"></div><div class="field"><label>Temperature</label><input class="input" id="provider-temperature" type="number" min="0" max="2" step="0.1" value="${attr(provider?.temperature ?? 0.4)}"></div><div class="field"><label>Max output tokens</label><input class="input" id="provider-max-tokens" type="number" min="64" value="${attr(provider?.max_output_tokens ?? 4096)}"></div><div class="field"><label>Timeout 秒</label><input class="input" id="provider-timeout" type="number" min="1" max="600" value="${attr(provider?.timeout_seconds ?? 90)}"></div><label class="notice"><input type="checkbox" id="provider-structured" ${provider?.structured_output !== false ? 'checked' : ''}> 请求结构化 JSON 输出</label></div>
      <div class="provider-secret-row"><p>${provider?.secret_configured ? '已配置 Secret。API Key 留空表示保留现有值。' : 'API Key 和 Header 将直接写入本地加密 Vault。'}</p><div class="field"><label>API Key</label><input class="input" id="provider-api-key" type="password" autocomplete="new-password"></div><div class="field" style="margin-top:10px"><label>自定义 Header JSON</label><textarea class="textarea provider-headers" id="provider-headers" placeholder='{"X-Custom-Key":"value"}'>${escapeHtml(headersValue)}</textarea></div>${provider ? '<label class="notice warning" style="margin-top:10px"><input type="checkbox" id="provider-clear-secret"> 清除现有 Secret</label>' : ''}</div>
    </div>`, '<button class="button" data-ai-action="dialog-close" type="button">取消</button><button class="button primary" data-ai-action="provider-save" type="button">保存 Provider</button>');
  }

  function providerPayload() {
    let customHeaders = {};
    const rawHeaders = document.getElementById('provider-headers')?.value.trim() || '';
    if (rawHeaders) {
      try { customHeaders = JSON.parse(rawHeaders); } catch (error) { throw new Error(`Header JSON 无效：${error.message}`); }
      if (!customHeaders || Array.isArray(customHeaders) || typeof customHeaders !== 'object') throw new Error('Header 必须是 JSON object');
    }
    return {
      name: document.getElementById('provider-name')?.value.trim() || '',
      kind: document.getElementById('provider-kind')?.value || 'openai',
      base_url: document.getElementById('provider-base-url')?.value.trim() || null,
      model: document.getElementById('provider-model')?.value.trim() || '',
      temperature: Number(document.getElementById('provider-temperature')?.value || 0.4),
      max_output_tokens: Number(document.getElementById('provider-max-tokens')?.value || 4096),
      timeout_seconds: Number(document.getElementById('provider-timeout')?.value || 90),
      structured_output: Boolean(document.getElementById('provider-structured')?.checked),
      api_key: document.getElementById('provider-api-key')?.value || null,
      headers: customHeaders,
      clear_secret: Boolean(document.getElementById('provider-clear-secret')?.checked),
    };
  }

  async function saveProvider() {
    const payload = providerPayload();
    const path = editingProvider ? `/api/v1/ai/providers/${encodeURIComponent(editingProvider.id)}` : '/api/v1/ai/providers';
    if (!editingProvider) delete payload.clear_secret;
    await api(path, { method: editingProvider ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    closeDialog();
    toast('Provider 已保存，Secret 未返回浏览器');
    await renderCurrent(true);
  }

  async function testProvider(id) {
    const result = await api(`/api/v1/ai/providers/${encodeURIComponent(id)}/test`, { method: 'POST' });
    showDialog('连接测试', `<pre class="mono-box">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`, '<button class="button" data-ai-action="dialog-close" type="button">关闭</button>');
  }
  async function showModels(id) {
    const result = await api(`/api/v1/ai/providers/${encodeURIComponent(id)}/models`);
    showDialog('可用模型', result.items?.length ? `<div class="review-list">${result.items.map((item) => `<div class="review-item code">${escapeHtml(item)}</div>`).join('')}</div>` : emptyState('未返回模型列表', '某些兼容服务不提供模型枚举，可直接填写模型 ID。'), '<button class="button" data-ai-action="dialog-close" type="button">关闭</button>');
  }
  async function deleteProvider(id) {
    if (!window.confirm('删除 Provider 及其本地加密 Secret？')) return;
    await api(`/api/v1/ai/providers/${encodeURIComponent(id)}`, { method: 'DELETE' });
    toast('Provider 和 Secret 已删除');
    await renderCurrent(true);
  }

  function generationPayload() {
    readFormState();
    if (!formState.provider_id) throw new Error('请选择 Provider');
    if (!formState.instruction.trim()) throw new Error('请输入明确设计或修改要求');
    const existing = aiMode === 'refine' || ((aiMode === 'distill' || aiMode === 'hybrid') && targetExisting);
    if (existing && !formState.persona_id) throw new Error('请选择目标 Persona');
    if (!existing && (!formState.requested_persona_id || !formState.requested_name)) throw new Error('请输入新 Persona ID 和名称');
    return {
      provider_id: formState.provider_id, mode: aiMode,
      instruction: formState.instruction, evidence: (aiMode === 'distill' || aiMode === 'hybrid') ? formState.evidence : '',
      persona_id: existing ? formState.persona_id : null,
      requested_persona_id: existing ? null : formState.requested_persona_id,
      requested_name: existing ? null : formState.requested_name,
      locale: formState.locale || 'zh-CN',
    };
  }
  async function generate() {
    const button = document.querySelector('[data-ai-action="generate"]');
    button.disabled = true;
    button.textContent = '生成、验证与编译中…';
    try {
      const result = await api('/api/v1/ai/generations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(generationPayload()) });
      currentGeneration = result.result;
      resultTab = 'canonical';
      toast('AI 草稿已生成并完成本地评估');
      await renderCurrent(true);
    } finally {
      if (button.isConnected) { button.disabled = false; button.textContent = '生成并评估草稿'; }
    }
  }
  async function selectGeneration(id) {
    currentGeneration = await api(`/api/v1/ai/generations/${encodeURIComponent(id)}`);
    resultTab = 'canonical';
    document.getElementById('ai-result').innerHTML = resultPane(currentGeneration);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  function applyDialog() {
    if (!currentGeneration) return;
    const isNew = !currentGeneration.persona_id;
    showDialog('应用 AI Persona 草稿', `<div class="notice warning">应用会写入 Persona 工程并创建 Revision，但不会部署或同步。若现有人格在生成后已变化，操作会被拒绝。</div>${isNew ? `<div class="field" style="margin-top:12px"><label>文件夹（留空使用 ${escapeHtml(currentGeneration.requested_persona_id || '')}）</label><input class="input" id="ai-apply-folder"></div>` : ''}<div class="field" style="margin-top:12px"><label>输入 APPLY 继续</label><input class="input" id="ai-apply-confirmation" autocomplete="off"></div>`, '<button class="button" data-ai-action="dialog-close" type="button">取消</button><button class="button primary" data-ai-action="apply-confirm" type="button">写入 Revision</button>');
  }
  async function applyGeneration() {
    if (document.getElementById('ai-apply-confirmation')?.value !== 'APPLY') throw new Error('请输入 APPLY');
    const result = await api(`/api/v1/ai/generations/${encodeURIComponent(currentGeneration.id)}/apply`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmation: 'APPLY', folder: document.getElementById('ai-apply-folder')?.value.trim() || null }) });
    currentGeneration = result.result;
    closeDialog();
    toast('AI 草稿已写入 Persona Revision；未执行部署');
    await renderCurrent(true);
  }

  async function renderCurrent(force = false) {
    const root = route();
    if (!['ai-studio', 'settings'].includes(root) || rendering) return;
    if (!force && workspace.querySelector(`[data-ai-view="${root === 'ai-studio' ? 'studio' : 'settings'}"]`)) return;
    rendering = true;
    try {
      if (root === 'ai-studio') await renderStudio(); else await renderSettings();
    } catch (error) {
      workspace.innerHTML = `${pageHeader('AI Studio Error', '页面加载失败', error.message || String(error))}<div class="notice error">${escapeHtml(error.message || error)}</div>`;
    } finally { rendering = false; }
  }

  const observer = new MutationObserver(() => window.setTimeout(() => renderCurrent(), 0));
  observer.observe(workspace, { childList: true, subtree: true });
  window.addEventListener('hashchange', () => window.setTimeout(() => renderCurrent(true), 0));

  document.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-ai-action]');
    if (!target) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      const action = target.dataset.aiAction;
      if (action === 'dialog-close') closeDialog();
      else if (action === 'mode') { readFormState(); aiMode = target.dataset.mode; if (aiMode === 'refine') targetExisting = true; if (aiMode === 'create') targetExisting = false; await renderCurrent(true); }
      else if (action === 'target-mode') { readFormState(); targetExisting = target.dataset.existing === 'true'; await renderCurrent(true); }
      else if (action === 'result-tab') { resultTab = target.dataset.tab; document.getElementById('ai-result').innerHTML = resultPane(currentGeneration); }
      else if (action === 'generate') await generate();
      else if (action === 'select-generation') await selectGeneration(target.dataset.id);
      else if (action === 'apply-dialog') applyDialog();
      else if (action === 'apply-confirm') await applyGeneration();
      else if (action === 'provider-add') providerDialog();
      else if (action === 'provider-edit') { const data = await api('/api/v1/ai/providers'); providerDialog(data.items.find((item) => item.id === target.dataset.id)); }
      else if (action === 'provider-save') await saveProvider();
      else if (action === 'provider-test') await testProvider(target.dataset.id);
      else if (action === 'provider-models') await showModels(target.dataset.id);
      else if (action === 'provider-delete') await deleteProvider(target.dataset.id);
    } catch (error) { toast(error.message || String(error), 'error'); }
  }, true);

  renderCurrent();
})();
