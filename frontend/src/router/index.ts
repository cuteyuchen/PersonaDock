import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

import DashboardView from '@/views/DashboardView.vue'
import JobsView from '@/views/JobsView.vue'
import PersonasView from '@/views/PersonasView.vue'
import PlaceholderView from '@/views/PlaceholderView.vue'
import RuntimesView from '@/views/RuntimesView.vue'
import SettingsView from '@/views/SettingsView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/overview' },
  { path: '/overview', name: 'overview', component: DashboardView, meta: { title: '概览' } },
  { path: '/personas', name: 'personas', component: PersonasView, meta: { title: '人格' } },
  { path: '/runtimes', name: 'runtimes', component: RuntimesView, meta: { title: '运行实例' } },
  { path: '/jobs', name: 'jobs', component: JobsView, meta: { title: '任务中心' } },
  { path: '/settings', name: 'settings', component: SettingsView, meta: { title: '系统设置' } },
  { path: '/ai-studio', name: 'ai-studio', component: PlaceholderView, meta: { title: 'AI 人格工作室', legacyHash: '#/ai-studio' } },
  { path: '/diff', name: 'diff', component: PlaceholderView, meta: { title: '差异中心', legacyHash: '#/diff' } },
  { path: '/deployments', name: 'deployments', component: PlaceholderView, meta: { title: '部署', legacyHash: '#/deployments' } },
  { path: '/memory', name: 'memory', component: PlaceholderView, meta: { title: 'Memory 同步', legacyHash: '#/memory' } },
  { path: '/sessions', name: 'sessions', component: PlaceholderView, meta: { title: 'Session Summary', legacyHash: '#/sessions' } },
  { path: '/packages', name: 'packages', component: PlaceholderView, meta: { title: 'PersonaPack 与信任', legacyHash: '#/packages' } },
  { path: '/backups', name: 'backups', component: PlaceholderView, meta: { title: '备份', legacyHash: '#/backups' } },
  { path: '/character-cards', name: 'character-cards', component: PlaceholderView, meta: { title: 'Character Card', legacyHash: '#/character-cards' } },
  { path: '/adapters', name: 'adapters', component: PlaceholderView, meta: { title: 'Adapter 与 Skill', legacyHash: '#/adapters' } },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((route) => {
  document.title = `${String(route.meta.title ?? '控制面')} · PersonaDock`
})
