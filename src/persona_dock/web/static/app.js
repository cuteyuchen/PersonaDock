(() => {
  'use strict';

  const state = {
    meta: null,
    token: sessionStorage.getItem('personadock.web.token') || '',
    route: 'overview',
    loading: 0,
    pendingAdoption: null,
  };

  const workspace = document.getElementById('workspace');
  const nav = document.getElementById('sidebar-nav');
  const routeTitle = document.getElementById('route-title');
  const connectionState = document.getElementById('connection-state');
  const connectionLabel = document.getElementById('connection-label');
  const brandVersion = document.getElementById('brand-version');
  const loadingLine = document.getElementById('loading-line');
  const toastRegion = document.getElementById('toast-region');
  const dialogRoot = document.getElementById('dialog-root');

  const legacyPages = {
    canonical: { label: 'Canonical 编辑器', href: '/canonical' },
    hermes: { label: 'Hermes Profile 管理', href: '/hermes' },
    openclaw: { label: 'OpenClaw Agent 管理', href: '/openclaw' },
    memory: { label: 'Memory 审核中心', href: '/sync' },
    sessions: { label: 'Session Summary 审核', href: '/sessions' },
  };

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

  function formatDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    }).format(date);
  }

  function setLoading(active) {
    state.loading += active ? 1 : -1;
    state.loading = Math.max(0, state.loading);
    loadingLine.hidden = state.loading === 0;
  }

  function setConnection(kind, label) {
    connectionState.className = `connection-state ${kind}`;
    connectionLabel.textContent = label;
  }

  function headers(extra = {}) {
    return state.token
      ? { ...extra, Authorization: `Bearer ${state.token}` }
      : extra;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: headers(options.headers || {}),
    });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json();
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body);
      } catch (_) {
        // Keep HTTP status text.
      }
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async function download(path, filename) {
    const response = await fetch(path, { headers: headers() });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || 'personadock-export';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function run(task) {
    setLoading(true);
    try {
      return await task();
    } finally {
      setLoading(false);
    }
  }

  function toast(message, type = 'info') {
    const item = document.createElement('div');
    item.className = `toast ${type === 'error' ? 'error' : ''}`;
    item.textContent = message;
    toastRegion.appendChild(item);
    window.setTimeout(() => item.remove(), 4200);
  }

  function showDialog(title, body, footer = '') {
    dialogRoot.innerHTML = `
      <div class="dialog-backdrop" data-action="dialog-backdrop">
        <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
          <header class="dialog-header">
            <h2 id="dialog-title">${escapeHtml(title)}</h2>
            <button class="icon-button" data-action="dialog-close" type="button" aria-label="关闭">×</button>
          </header>
          <div class="dialog-body">${body}</div>
          ${footer ? `<footer class="dialog-footer">${footer}</footer>` : ''}
        </section>
      </div>`;
    const first = dialogRoot.querySelector('input, select, textarea, button');
    if (first) first.focus();
  }

  function closeDialog() {
    dialogRoot.innerHTML = '';
    state.pendingAdoption = null;
  }

  function pageHeader(kicker, title, summary, actions = '') {
    return `
      <header class="page-header">
        <div>
          <div class="page-kicker">${escapeHtml(kicker)}</div>
          <h1>${escapeHtml(title)}</h1>
          <p class="page-summary">${escapeHtml(summary)}</p>
        </div>
        ${actions ? `<div class="actions">${actions}</div>` : ''}
      </header>`;
  }

  function statusBadge(status, label = null) {
    const value = String(status || 'unknown');
    return `<span class="status ${attr(value)}">${escapeHtml(label || value)}</span>`;
  }

  function emptyState(title, text) {
    return `<div class="empty-state"><strong>${escapeHtml(title)}</strong>${escapeHtml(text)}</div>`;
  }

  function renderNavigation() {
    const items = state.meta?.navigation || [];
    const groups = [
      ['控制', ['overview', 'personas', 'ai-studio', 'diff', 'runtimes', 'deployments']],
      ['治理', ['memory', 'sessions', 'packages', 'backups', 'character-cards']],
      ['系统', ['adapters', 'jobs', 'settings']],
    ];
    const current = state.route.split('/')[0];
    nav.innerHTML = groups.map(([label, ids]) => {
      const links = ids.map((id) => items.find((item) => item.id === id)).filter(Boolean);
      return `
        <div class="nav-group-label">${escapeHtml(label)}</div>
        ${links.map((item) => `
          <a class="nav-item ${current === item.id ? 'active' : ''}" href="${attr(item.route)}">
            <span class="nav-glyph" aria-hidden="true"></span>
            <span class="nav-label">${escapeHtml(item.label)}</span>
            ${item.phase > 1 ? `<span class="nav-phase">P${item.phase}</span>` : ''}
          </a>`).join('')}`;
    }).join('');
  }

  function parseRoute() {
    const raw = location.hash.replace(/^#\/?/, '').trim();
    return raw || 'overview';
  }

  function setTitle(title) {
    routeTitle.textContent = title;
    document.title = `${title} · PersonaDock`;
  }

  function metricCell(label, value, detail = '') {
    return `<div class="stat-cell"><div class="stat-label">${escapeHtml(label)}</div><div class="stat-value">${escapeHtml(value)}</div><div class="stat-detail">${escapeHtml(detail)}</div></div>`;
  }

  function renderPersonaRows(personas) {
    if (!personas.length) {
      return `<tr><td colspan="6">${emptyState('尚未注册 Persona', '可使用 CLI 新建，Phase 2 将加入网页新建和注册向导。')}</td></tr>`;
    }
    return personas.map((persona) => `
      <tr>
        <td><a href="#/personas/${attr(persona.id)}">${escapeHtml(persona.name)}</a><div class="list-meta code">${escapeHtml(persona.id)}</div></td>
        <td>${escapeHtml(persona.version)}</td>
        <td>v${escapeHtml(persona.schema_version)}</td>
        <td>${escapeHtml(persona.summary || '—')}</td>
        <td class="code">${escapeHtml(persona.source_path || '未绑定工程')}</td>
        <td>${formatDate(persona.updated_at)}</td>
      </tr>`).join('');
  }

  function renderInstanceRows(instances) {
    if (!instances.length) {
      return `<tr><td colspan="6">${emptyState('尚未发现运行实例', '执行扫描后会列出 Hermes Profile 和 OpenClaw Agent。')}</td></tr>`;
    }
    return instances.map((instance) => `
      <tr>
        <td><strong>${escapeHtml(instance.display_name)}</strong><div class="list-meta code">${escapeHtml(instance.platform_instance_id)}</div></td>
        <td>${escapeHtml(instance.adapter)}</td>
        <td>${escapeHtml(instance.transport)}</td>
        <td>${statusBadge(instance.managed ? 'managed' : 'unmanaged', instance.managed ? '已管理' : '未管理')}</td>
        <td class="code">${escapeHtml(instance.location)}</td>
        <td>${instance.managed ? '' : `<button class="button small" data-action="adopt-preview" data-instance-id="${attr(instance.id)}" type="button">接管预览</button>`}</td>
      </tr>`).join('');
  }

  function renderJobRows(jobs) {
    if (!jobs.length) {
      return `<tr><td colspan="6">${emptyState('暂无任务记录', '后续构建、部署、备份和 AI 生成会统一进入任务中心。')}</td></tr>`;
    }
    return jobs.map((job) => `
      <tr>
        <td><a href="#/jobs/${attr(job.id)}">${escapeHtml(job.label)}</a><div class="list-meta code">${escapeHtml(job.kind)}</div></td>
        <td>${statusBadge(job.status)}</td>
        <td><div class="progress-track"><div class="progress-value" style="width:${Number(job.progress) || 0}%"></div></div><div class="list-meta">${escapeHtml(job.progress)}%</div></td>
        <td>${escapeHtml(job.persona_id || '—')}</td>
        <td>${formatDate(job.created_at)}</td>
        <td>${escapeHtml(job.error || '—')}</td>
      </tr>`).join('');
  }

  async function renderOverview() {
    setTitle('概览');
    workspace.innerHTML = pageHeader(
      'Control Plane',
      '本地人格控制面',
      '集中查看 Persona、运行实例和待处理任务。所有写操作仍遵循审核与可回滚原则。',
      '<button class="button" data-action="discover" type="button">扫描运行实例</button><a class="button primary" href="#/personas">查看人格</a>',
    ) + emptyState('正在读取 Registry', '');

    const [dashboard, doctor] = await Promise.all([
      api('/api/v1/dashboard'),
      api('/api/doctor').catch((error) => ({ adapters: [], error: error.message })),
    ]);
    const metrics = dashboard.metrics || {};
    const registry = dashboard.registry || {};
    const adapters = doctor.adapters || [];
    workspace.innerHTML = `
      ${pageHeader(
        'Control Plane',
        '本地人格控制面',
        '集中查看 Persona、运行实例和待处理任务。所有写操作仍遵循审核与可回滚原则。',
        '<button class="button" data-action="discover" type="button">扫描运行实例</button><a class="button primary" href="#/personas">查看人格</a>',
      )}
      <section class="stat-strip" aria-label="控制面统计">
        ${metricCell('Persona', metrics.personas ?? 0, 'Registry 中的人格')}
        ${metricCell('运行实例', metrics.runtime_instances ?? 0, 'Hermes 与 OpenClaw')}
        ${metricCell('已管理', metrics.managed_instances ?? 0, '已绑定 Persona')}
        ${metricCell('未管理', metrics.unmanaged_instances ?? 0, '可接管实例')}
        ${metricCell('活动任务', metrics.active_jobs ?? 0, '队列、运行或待审核')}
        ${metricCell('快照', registry.snapshots ?? 0, '可用于恢复')}
      </section>
      <div class="grid-two">
        <div class="stack">
          <section class="panel">
            <header class="panel-header"><div class="panel-title"><h2>最近 Persona</h2><p>按 Registry 更新时间显示</p></div><a class="button small" href="#/personas">全部</a></header>
            <div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>人格</th><th>版本</th><th>Schema</th><th>摘要</th><th>工程</th><th>更新时间</th></tr></thead><tbody>${renderPersonaRows(dashboard.personas || [])}</tbody></table></div>
          </section>
          <section class="panel">
            <header class="panel-header"><div class="panel-title"><h2>运行实例</h2><p>本地、Docker 和 SSH 发现结果</p></div><a class="button small" href="#/runtimes">全部</a></header>
            <div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>实例</th><th>Adapter</th><th>传输</th><th>状态</th><th>位置</th><th></th></tr></thead><tbody>${renderInstanceRows(dashboard.instances || [])}</tbody></table></div>
          </section>
        </div>
        <div class="stack">
          <section class="panel">
            <header class="panel-header"><div class="panel-title"><h2>Adapter 状态</h2><p>Doctor 只读诊断</p></div><button class="button small" data-action="refresh" type="button">重新检查</button></header>
            <div class="list">
              ${adapters.length ? adapters.map((adapter) => `
                <div class="list-row">
                  <div class="list-primary"><div class="list-title">${escapeHtml(adapter.adapter)}</div><div class="list-meta">${escapeHtml(adapter.message || adapter.executable || '')}</div></div>
                  ${statusBadge(adapter.status)}
                </div>`).join('') : emptyState('Doctor 暂不可用', doctor.error || '未返回 Adapter 状态')}
            </div>
          </section>
          <section class="panel">
            <header class="panel-header"><div class="panel-title"><h2>最近任务</h2><p>统一 Job Store</p></div><a class="button small" href="#/jobs">任务中心</a></header>
            <div class="list">
              ${(dashboard.jobs || []).length ? dashboard.jobs.map((job) => `
                <a class="list-row" href="#/jobs/${attr(job.id)}" style="color:inherit;text-decoration:none">
                  <div class="list-primary"><div class="list-title">${escapeHtml(job.label)}</div><div class="list-meta">${formatDate(job.created_at)}</div></div>
                  ${statusBadge(job.status)}
                </a>`).join('') : emptyState('暂无任务', '任务执行后会在这里保留状态和事件。')}
            </div>
          </section>
          <section class="panel">
            <header class="panel-header"><div class="panel-title"><h2>兼容页面</h2><p>重构期间继续可用</p></div><a class="button small" href="#/capabilities">能力映射</a></header>
            <div class="panel-body"><div class="legacy-links">${Object.values(legacyPages).map((page) => `<a class="legacy-link" href="${attr(page.href)}">${escapeHtml(page.label)}</a>`).join('')}</div></div>
          </section>
        </div>
      </div>`;
  }

  async function renderPersonas() {
    setTitle('人格');
    const personas = await api('/api/personas');
    workspace.innerHTML = `
      ${pageHeader('Persona Registry', '人格', '当前阶段先统一展示、详情、编辑入口和导出；网页新建与注册向导在 Phase 2 接入。', '<a class="button" href="/canonical">打开高级编辑器</a><button class="button primary" data-action="phase-info" data-phase="2" type="button">新建人格</button>')}
      <div class="toolbar"><input class="input" id="persona-search" type="search" placeholder="搜索名称、ID、摘要或路径"><div class="toolbar-spacer"></div><span class="status">${personas.length} 个 Persona</span></div>
      <section class="panel">
        <div class="panel-body flush table-wrap"><table class="data-table" id="persona-table"><thead><tr><th>人格</th><th>版本</th><th>Schema</th><th>摘要</th><th>工程</th><th>更新时间</th></tr></thead><tbody>${renderPersonaRows(personas)}</tbody></table></div>
      </section>`;
    const search = document.getElementById('persona-search');
    search.addEventListener('input', () => {
      const term = search.value.trim().toLowerCase();
      document.querySelectorAll('#persona-table tbody tr').forEach((row) => {
        row.hidden = term && !row.textContent.toLowerCase().includes(term);
      });
    });
  }

  async function renderPersonaDetail(personaId) {
    const persona = await api(`/api/personas/${encodeURIComponent(personaId)}`);
    setTitle(persona.name);
    workspace.innerHTML = `
      ${pageHeader('Persona', persona.name, persona.summary || '尚无人格摘要。', '<a class="button" href="/canonical">编辑 Canonical</a><button class="button" data-action="export" data-persona-id="' + attr(persona.id) + '" data-format="personapack" type="button">导出 PersonaPack</button><button class="button primary" data-action="phase-info" data-phase="3" type="button">版本与差异</button>')}
      <div class="grid-two">
        <section class="panel">
          <header class="panel-header"><div class="panel-title"><h2>人格信息</h2><p>Registry 当前记录</p></div>${statusBadge(`schema-${persona.schema_version}`, `Schema v${persona.schema_version}`)}</header>
          <div class="panel-body">
            <div class="form-grid">
              <div class="field"><label>Persona ID</label><div class="code">${escapeHtml(persona.id)}</div></div>
              <div class="field"><label>版本</label><div>${escapeHtml(persona.version)}</div></div>
              <div class="field"><label>创建时间</label><div>${formatDate(persona.created_at)}</div></div>
              <div class="field"><label>更新时间</label><div>${formatDate(persona.updated_at)}</div></div>
              <div class="field" style="grid-column:1/-1"><label>源工程</label><div class="code">${escapeHtml(persona.source_path || '未绑定')}</div></div>
            </div>
          </div>
        </section>
        <section class="panel">
          <header class="panel-header"><div class="panel-title"><h2>运行时绑定</h2><p>Persona 与 Runtime 的关系</p></div><span class="status">${(persona.bindings || []).length}</span></header>
          <div class="list">${(persona.bindings || []).length ? persona.bindings.map((binding) => `<div class="list-row"><div class="list-primary"><div class="list-title code">${escapeHtml(binding.runtime_instance_id)}</div><div class="list-meta">${binding.adopted ? '通过接管建立' : '部署绑定'} · ${formatDate(binding.managed_since)}</div></div>${statusBadge(binding.adopted ? 'managed' : 'info', binding.adopted ? '已接管' : '已绑定')}</div>`).join('') : emptyState('尚未绑定运行实例', '可在运行实例页面扫描并接管现有 Profile 或 Agent。')}</div>
        </section>
      </div>
      <section class="panel" style="margin-top:16px">
        <header class="panel-header"><div class="panel-title"><h2>可用操作</h2><p>兼容入口将在后续阶段迁入统一工作流</p></div></header>
        <div class="panel-body"><div class="legacy-links"><a class="legacy-link" href="/canonical">Canonical 编辑与测试</a><a class="legacy-link" href="/hermes">部署到 Hermes</a><a class="legacy-link" href="/openclaw">部署到 OpenClaw</a><a class="legacy-link" href="/sync">Memory 审核</a><a class="legacy-link" href="/sessions">Session Summary</a></div></div>
      </section>`;
  }

  async function renderRuntimes() {
    setTitle('运行实例');
    const instances = await api('/api/instances');
    workspace.innerHTML = `
      ${pageHeader('Runtime Registry', '运行实例', '只读发现 Hermes Profile 与 OpenClaw Agent。接管操作会先展示预览并创建快照。', '<button class="button primary" data-action="discover" type="button">扫描 Hermes 与 OpenClaw</button>')}
      <section class="panel">
        <div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>实例</th><th>Adapter</th><th>传输</th><th>状态</th><th>位置</th><th></th></tr></thead><tbody>${renderInstanceRows(instances)}</tbody></table></div>
      </section>`;
  }

  async function renderJobs() {
    setTitle('任务中心');
    const result = await api('/api/v1/jobs?limit=100');
    workspace.innerHTML = `
      ${pageHeader('Job Store', '任务中心', '构建、部署、同步、备份和 AI 生成会统一记录进度、事件、输出和错误。', '<button class="button" data-action="refresh" type="button">刷新</button>')}
      <section class="panel"><div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>任务</th><th>状态</th><th>进度</th><th>Persona</th><th>创建时间</th><th>错误</th></tr></thead><tbody>${renderJobRows(result.items || [])}</tbody></table></div></section>`;
  }

  async function renderJobDetail(jobId) {
    const job = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
    setTitle(job.label);
    workspace.innerHTML = `
      ${pageHeader('Job', job.label, job.kind, job.status === 'queued' || job.status === 'running' || job.status === 'waiting-review' ? `<button class="button danger" data-action="cancel-job" data-job-id="${attr(job.id)}" type="button">取消任务</button>` : '')}
      <div class="grid-two">
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>任务状态</h2><p class="code">${escapeHtml(job.id)}</p></div>${statusBadge(job.status)}</header><div class="panel-body"><div class="form-grid"><div class="field"><label>进度</label><div>${escapeHtml(job.progress)}%</div></div><div class="field"><label>Persona</label><div>${escapeHtml(job.persona_id || '—')}</div></div><div class="field"><label>创建</label><div>${formatDate(job.created_at)}</div></div><div class="field"><label>完成</label><div>${formatDate(job.finished_at)}</div></div></div>${job.error ? `<div class="notice danger" style="margin-top:14px">${escapeHtml(job.error)}</div>` : ''}</div></section>
        <section class="panel"><header class="panel-header"><div class="panel-title"><h2>输入与输出</h2><p>结构化任务数据</p></div></header><pre class="mono-box">${escapeHtml(JSON.stringify({ input: job.input, output: job.output }, null, 2))}</pre></section>
      </div>
      <section class="panel" style="margin-top:16px"><header class="panel-header"><div class="panel-title"><h2>事件</h2><p>按发生顺序记录</p></div><button class="button small" data-action="refresh" type="button">刷新</button></header><div class="list">${(job.events || []).length ? job.events.map((event) => `<div class="list-row"><div class="list-primary"><div class="list-title">${escapeHtml(event.message)}</div><div class="list-meta">${formatDate(event.created_at)} · ${escapeHtml(event.level)}</div></div><span class="code">#${escapeHtml(event.id)}</span></div>`).join('') : emptyState('暂无事件', '任务事件将在执行过程中写入。')}</div></section>`;
  }

  async function renderCapabilities() {
    setTitle('能力映射');
    const result = await api('/api/v1/capabilities');
    const summary = result.summary || {};
    workspace.innerHTML = `
      ${pageHeader('Capability Contract', 'CLI / API / Web 能力映射', '该表用于防止 CLI 新增功能后网页端长期缺失。planned 项会按开发阶段逐步转为 ready。')}
      <section class="stat-strip" style="grid-template-columns:repeat(4,minmax(120px,1fr))">
        ${metricCell('全部能力', summary.total ?? 0)}${metricCell('Web 2.0 Ready', summary.ready ?? 0)}${metricCell('旧页面兼容', summary.legacy ?? 0)}${metricCell('计划中', summary.planned ?? 0)}
      </section>
      <section class="panel"><div class="panel-body flush table-wrap"><table class="data-table"><thead><tr><th>能力</th><th>类别</th><th>CLI</th><th>API</th><th>Web</th><th>状态</th><th>属性</th></tr></thead><tbody>${(result.items || []).map((item) => `<tr><td><strong>${escapeHtml(item.label)}</strong><div class="list-meta code">${escapeHtml(item.id)}</div></td><td>${escapeHtml(item.category)}</td><td class="code">${escapeHtml(item.cli_command || '—')}</td><td class="code">${escapeHtml(item.api_route || '—')}</td><td class="code">${escapeHtml(item.web_route || item.web_not_applicable_reason || '—')}</td><td>${statusBadge(item.status)}</td><td>${[item.destructive && '写操作', item.supports_preview && '可预览', item.runs_as_job && 'Job'].filter(Boolean).map((label) => `<span class="status">${label}</span>`).join(' ') || '—'}</td></tr>`).join('')}</tbody></table></div></section>`;
  }

  function renderPlanned(route) {
    const item = state.meta?.navigation?.find((entry) => entry.id === route);
    const title = item?.label || route;
    setTitle(title);
    const compatibility = legacyPages[route];
    workspace.innerHTML = `
      ${pageHeader(`Web Phase ${item?.phase || '—'}`, title, '该模块已经纳入 Web 2.0 Capability 契约，正在按阶段迁入统一控制面。')}
      <section class="panel"><div class="panel-body">
        <div class="notice warning">当前页面不是最终实现。重构期间不会移除现有 CLI 或旧 Web 工作流。</div>
        ${compatibility ? `<div class="actions" style="margin-top:14px"><a class="button primary" href="${attr(compatibility.href)}">打开现有${escapeHtml(compatibility.label)}</a><a class="button" href="#/capabilities">查看能力映射</a></div>` : `<div class="actions" style="margin-top:14px"><a class="button" href="#/capabilities">查看能力映射</a></div>`}
      </div></section>`;
  }

  async function renderRoute() {
    state.route = parseRoute();
    renderNavigation();
    const parts = state.route.split('/').filter(Boolean);
    const root = parts[0] || 'overview';
    try {
      await run(async () => {
        if (root === 'overview') return renderOverview();
        if (root === 'personas' && parts[1]) return renderPersonaDetail(decodeURIComponent(parts[1]));
        if (root === 'personas') return renderPersonas();
        if (root === 'runtimes') return renderRuntimes();
        if (root === 'jobs' && parts[1]) return renderJobDetail(decodeURIComponent(parts[1]));
        if (root === 'jobs') return renderJobs();
        if (root === 'capabilities') return renderCapabilities();
        return renderPlanned(root);
      });
      setConnection('ready', '本地控制面已连接');
    } catch (error) {
      setConnection('error', error.status === 401 ? '需要访问令牌' : '控制面连接失败');
      workspace.innerHTML = `${pageHeader('Error', '页面加载失败', error.message || String(error))}<section class="panel"><div class="panel-body"><div class="notice danger">${escapeHtml(error.message || error)}</div><div class="actions" style="margin-top:14px"><button class="button" data-action="refresh" type="button">重试</button>${error.status === 401 ? '<button class="button primary" data-action="token-dialog" type="button">设置访问令牌</button>' : ''}</div></div></section>`;
    }
  }

  async function discover() {
    const report = await run(() => api('/api/discover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: null }),
    }));
    toast(`扫描完成：发现 ${report.instances?.length ?? 0} 个运行实例`);
    await renderRoute();
  }

  async function previewAdoption(instanceId) {
    const preview = await run(() => api('/api/adoptions/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instance_id: instanceId }),
    }));
    state.pendingAdoption = { instance_id: instanceId };
    showDialog(
      '接管运行实例',
      `<div class="notice warning">接管会先创建快照。Memory 只会进入待审核候选，不会立即传播。</div>
       <div class="form-grid" style="margin-top:14px">
         <div class="field"><label>Adapter</label><div>${escapeHtml(preview.instance?.adapter)}</div></div>
         <div class="field"><label>平台实例</label><div class="code">${escapeHtml(preview.instance?.platform_instance_id)}</div></div>
         <div class="field"><label>Persona ID</label><div class="code">${escapeHtml(preview.persona_id)}</div></div>
         <div class="field"><label>目标工程</label><div class="code">${escapeHtml(preview.destination)}</div></div>
         <div class="field"><label>Skills</label><div>${escapeHtml(preview.skills?.length ?? 0)}</div></div>
         <div class="field"><label>Memory 候选</label><div>${escapeHtml(preview.memory_documents?.length ?? 0)}</div></div>
       </div>`,
      '<button class="button" data-action="dialog-close" type="button">取消</button><button class="button primary" data-action="adopt-confirm" type="button">创建快照并接管</button>',
    );
  }

  async function confirmAdoption() {
    if (!state.pendingAdoption) return;
    const result = await run(() => api('/api/adoptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.pendingAdoption),
    }));
    closeDialog();
    toast(`已接管为 Persona：${result.persona_id}`);
    await renderRoute();
  }

  async function exportPersona(button) {
    const personaId = button.dataset.personaId;
    const format = button.dataset.format;
    const result = await run(() => api(`/api/personas/${encodeURIComponent(personaId)}/exports`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format, include_memory: false }),
    }));
    await download(result.download_url, result.path?.split(/[\\/]/).pop());
    toast('导出完成');
  }

  function showTokenDialog() {
    showDialog(
      '访问令牌',
      `<div class="field"><label for="token-input">Bearer Token</label><input class="input" id="token-input" type="password" autocomplete="off" value="${attr(state.token)}" placeholder="本机默认无需填写"><div class="field-help">令牌仅保存在当前浏览器标签的 sessionStorage，不写入本地持久化配置。</div></div>`,
      '<button class="button" data-action="token-clear" type="button">清除</button><button class="button primary" data-action="token-save" type="button">保存并重试</button>',
    );
  }

  function saveToken(clear = false) {
    const input = document.getElementById('token-input');
    state.token = clear ? '' : (input?.value.trim() || '');
    if (state.token) sessionStorage.setItem('personadock.web.token', state.token);
    else sessionStorage.removeItem('personadock.web.token');
    closeDialog();
    renderRoute();
  }

  function showPhaseInfo(phase) {
    showDialog(
      `Web Phase ${phase}`,
      `<p style="margin:0;color:var(--text-soft);line-height:1.6">该功能已经进入开发路线，但尚未在当前阶段开放写操作。现有 CLI 和兼容页面继续可用。</p>`,
      '<button class="button primary" data-action="dialog-close" type="button">知道了</button>',
    );
  }

  async function cancelJob(jobId) {
    await run(() => api(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }));
    toast('任务已标记为取消');
    await renderRoute();
  }

  document.getElementById('refresh-button').addEventListener('click', renderRoute);
  document.getElementById('token-button').addEventListener('click', showTokenDialog);
  window.addEventListener('hashchange', renderRoute);

  document.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-action]');
    if (!target) return;
    const action = target.dataset.action;
    try {
      if (action === 'dialog-backdrop' && event.target === target) closeDialog();
      else if (action === 'dialog-close') closeDialog();
      else if (action === 'token-dialog') showTokenDialog();
      else if (action === 'token-save') saveToken(false);
      else if (action === 'token-clear') saveToken(true);
      else if (action === 'refresh') await renderRoute();
      else if (action === 'discover') await discover();
      else if (action === 'adopt-preview') await previewAdoption(target.dataset.instanceId);
      else if (action === 'adopt-confirm') await confirmAdoption();
      else if (action === 'export') await exportPersona(target);
      else if (action === 'phase-info') showPhaseInfo(target.dataset.phase);
      else if (action === 'cancel-job') await cancelJob(target.dataset.jobId);
    } catch (error) {
      toast(error.message || String(error), 'error');
    }
  });

  async function boot() {
    if (!location.hash) location.hash = '#/overview';
    try {
      state.meta = await run(() => api('/api/v1/meta'));
      brandVersion.textContent = `v${state.meta.version} · Web ${state.meta.web_control_plane}.0`;
      setConnection('ready', '本地控制面已连接');
      renderNavigation();
      await renderRoute();
    } catch (error) {
      setConnection('error', error.status === 401 ? '需要访问令牌' : '连接失败');
      brandVersion.textContent = '控制面连接失败';
      workspace.innerHTML = `${pageHeader('Connection', '无法连接 PersonaDock', error.message || String(error))}<section class="panel"><div class="panel-body"><div class="actions"><button class="button primary" data-action="token-dialog" type="button">设置访问令牌</button><button class="button" data-action="refresh" type="button">重试</button></div></div></section>`;
    }
  }

  boot();
})();
