import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

import ArtifactWorkspaceView from '@/views/ArtifactWorkspaceView.vue'
import DashboardView from '@/views/DashboardView.vue'
import DeploymentWorkspaceView from '@/views/DeploymentWorkspaceView.vue'
import DiffCenterView from '@/views/DiffCenterView.vue'
import JobsView from '@/views/JobsView.vue'
import PersonaCreateView from '@/views/PersonaCreateView.vue'
import PersonaDetailView from '@/views/PersonaDetailView.vue'
import PersonaEditorView from '@/views/PersonaEditorView.vue'
import PersonaRegisterView from '@/views/PersonaRegisterView.vue'
import PersonaRevisionsView from '@/views/PersonaRevisionsView.vue'
import PersonasView from '@/views/PersonasView.vue'
import PersonaTestsView from '@/views/PersonaTestsView.vue'
import PlaceholderView from '@/views/PlaceholderView.vue'
import RuntimesView from '@/views/RuntimesView.vue'
import SettingsView from '@/views/SettingsView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/overview' },
  { path: '/overview', name: 'overview', component: DashboardView, meta: { title: '概览' } },
  { path: '/personas', name: 'personas', component: PersonasView, meta: { title: '人格' } },
  { path: '/personas/new', name: 'persona-create', component: PersonaCreateView, meta: { title: '新建 Persona' } },
  { path: '/personas/register', name: 'persona-register', component: PersonaRegisterView, meta: { title: '注册 Persona' } },
  { path: '/personas/:personaId', name: 'persona-detail', component: PersonaDetailView, meta: { title: 'Persona 详情', personaTab: 'overview' } },
  { path: '/personas/:personaId/editor', name: 'persona-editor', component: PersonaEditorView, meta: { title: 'Canonical 编辑', personaTab: 'editor' } },
  { path: '/personas/:personaId/revisions', name: 'persona-revisions', component: PersonaRevisionsView, meta: { title: 'Revision 与 Diff', personaTab: 'revisions' } },
  { path: '/personas/:personaId/tests', name: 'persona-tests', component: PersonaTestsView, meta: { title: '验证与测试', personaTab: 'tests' } },
  { path: '/diff', name: 'diff', component: DiffCenterView, meta: { title: '差异中心' } },
  { path: '/runtimes', name: 'runtimes', component: RuntimesView, meta: { title: '运行实例' } },
  { path: '/runtimes/:runtimeId', name: 'runtime-detail', component: DeploymentWorkspaceView, meta: { title: '运行实例详情', workspace: 'runtime' } },
  { path: '/deployments', name: 'deployments', component: DeploymentWorkspaceView, meta: { title: '部署', workspace: 'deployments' } },
  { path: '/jobs', name: 'jobs', component: JobsView, meta: { title: '任务中心' } },
  { path: '/settings', name: 'settings', component: SettingsView, meta: { title: '系统设置' } },
  { path: '/ai-studio', name: 'ai-studio', component: PlaceholderView, meta: { title: 'AI 人格工作室', legacyHash: '#/ai-studio' } },
  { path: '/memory', name: 'memory', component: PlaceholderView, meta: { title: 'Memory 同步', legacyHash: '#/memory' } },
  { path: '/sessions', name: 'sessions', component: PlaceholderView, meta: { title: 'Session Summary', legacyHash: '#/sessions' } },
  { path: '/packages', name: 'packages', component: ArtifactWorkspaceView, meta: { title: 'PersonaPack 与信任', workspace: 'packages' } },
  { path: '/backups', name: 'backups', component: ArtifactWorkspaceView, meta: { title: '备份', workspace: 'backups' } },
  { path: '/character-cards', name: 'character-cards', component: ArtifactWorkspaceView, meta: { title: 'Character Card', workspace: 'character-cards' } },
  { path: '/adapters', name: 'adapters', component: ArtifactWorkspaceView, meta: { title: 'Adapter 与 Skill', workspace: 'adapters' } },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((route) => {
  document.title = `${String(route.meta.title ?? '控制面')} · PersonaDock`
})
