import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

test('Vue control plane owns the root entry and keeps legacy compatibility', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/PersonaDock/)
  await expect(page.getByText('Vue Control Plane')).toBeVisible()
  await expect(page.getByRole('navigation')).toBeVisible()
  await page.getByRole('link', { name: '人格', exact: true }).click()
  await expect(page).toHaveURL(/#\/personas$/)
  await expect(page.getByRole('heading', { name: '人格' })).toBeVisible()

  const legacy = await page.request.get('/legacy')
  expect(legacy.ok()).toBeTruthy()
  expect(await legacy.text()).toContain('PersonaDock')
})

test('major workspaces are reachable without placeholder pages', async ({ page }) => {
  await page.goto('/')
  for (const route of ['/packages', '/deployments', '/memory', '/sessions', '/ai-studio']) {
    await page.goto(`/#${route}`)
    await expect(page.locator('main')).toBeVisible()
    await expect(page.getByText('迁移中', { exact: false })).toHaveCount(0)
  }
})

test('root shell has no serious or critical automated accessibility violations', async ({ page }) => {
  await page.goto('/')
  const results = await new AxeBuilder({ page })
    .disableRules(['color-contrast'])
    .analyze()
  const blocking = results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))
  expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([])
})

test('embedded frontend stays within the release size budget', async ({ request }) => {
  const [script, style, meta] = await Promise.all([
    request.get('/assets/vue/app.js'),
    request.get('/assets/vue/app.css'),
    request.get('/api/v1/meta'),
  ])
  expect(script.ok()).toBeTruthy()
  expect(style.ok()).toBeTruthy()
  expect(meta.ok()).toBeTruthy()
  const bytes = (await script.body()).byteLength + (await style.body()).byteLength
  expect(bytes).toBeLessThan(8 * 1024 * 1024)
  expect((await meta.json()).web_frontend_migration_phase).toBe(7)
})
