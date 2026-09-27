import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

const SCENARIOS = [
  'drunk_first_class',
  'lost_child',
  'medical_chest_pain',
  'panic_attack',
  'smoking_vestibule',
  'unattended_bag',
  'upgrade_and_seat',
  'wheelchair_boarding',
];
const MAX_MOVES = 20;

// По одному пути через каждый сценарий: реальные API и база, без подмены ответов.
// Остальные ветки и формулы проверяются серверными тестами движка и контента.
for (const scenarioId of SCENARIOS) {
  test(`каталог: ${scenarioId} сохраняется, завершается и открывает карту`, async ({ page, request }) => {
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    const created = await request.post('/api/integration/employees', {
      headers: { 'X-API-Key': process.env.INTEGRATION_API_KEY || 'demo-integration-key' },
      data: {
        employee_code: `CAT-${randomUUID().slice(0, 16)}`,
        display_name: 'Проверка каталога',
        brigade: 'М-01',
      },
    });
    expect(created.status()).toBe(201);
    const employee = await created.json();
    await page.goto('/login');
    await page.getByLabel('Код сотрудника').fill(employee.employee_code);
    await page.getByLabel('PIN').fill(employee.pin);
    await page.getByRole('button', { name: 'Войти', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Мой прогресс', exact: true })).toBeVisible();
    const token = await page.evaluate(() => localStorage.getItem('provodnik.token'));
    async function readApi(path) {
      const response = await request.get(path, { headers: { Authorization: `Bearer ${token}` } });
      expect(response.status(), path).toBe(200);
      return response.json();
    }
    const before = await readApi('/api/profile');

    await page.goto(`/scenarios/${scenarioId}/map`);
    await expect(page.locator('.error')).toHaveText('Карта сценария откроется после первого прохождения');
    await expect(page.locator('svg.graph')).toHaveCount(0);
    await page.getByRole('link', { name: 'В каталог', exact: true }).click();
    await expect(page.locator('.scenario-card')).toHaveCount(SCENARIOS.length);
    const card = page.locator(`#${scenarioId}`);
    const title = await card.getByRole('heading', { level: 2 }).textContent();
    await card.getByRole('button', { name: 'Начать', exact: true }).click();
    await expect(page).toHaveURL(/\/play\/\d+$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(title);
    const runId = Number(page.url().match(/\/play\/(\d+)$/)[1]);

    for (let moves = 0; moves < MAX_MOVES && (await page.locator('.ending').count()) === 0; moves += 1) {
      const step = await page.locator('.step-no').textContent();
      await page.locator('.option-button').first().click();
      await expect(page.locator('.step-no')).not.toHaveText(step);
      if (moves === 0) {
        const saved = await readApi(`/api/sessions/${runId}`);
        await page.reload();
        await expect(page.locator('.step-no')).toHaveText(`Ход ${saved.step_no + 1}`);
        const restored = await readApi(`/api/sessions/${runId}`);
        expect(restored.run_id).toBe(saved.run_id);
        expect(restored.step_no).toBe(saved.step_no);
        expect(restored.node.id).toBe(saved.node.id);
        expect(restored.deadline_at).toBe(saved.deadline_at);
        await expect(page.locator('.scale-value')).toHaveText([String(saved.loyalty), String(saved.safety)]);
      }
    }
    await expect(page.locator('.ending')).toContainText('Исход');
    await expect(page.locator('.error')).toHaveCount(0);
    await page.getByRole('link', { name: 'Перейти к разбору', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/debrief/${runId}$`));
    const debrief = await readApi(`/api/runs/${runId}/debrief`);
    expect(debrief.scenario_id).toBe(scenarioId);
    expect(debrief.steps.length).toBeGreaterThan(0);
    expect(debrief.xp).toBeGreaterThan(0);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(title);
    await expect(page.locator('.debrief-step')).toHaveCount(debrief.steps.length);
    await expect(page.locator('.debrief-outcome .outcome')).toHaveClass(`outcome outcome-${debrief.outcome}`);
    await expect(page.locator('.scale-value')).toHaveText([String(debrief.loyalty_final), String(debrief.safety_final)]);
    await expect(page.getByRole('heading', { name: `Очки опыта: ${debrief.xp} XP`, exact: true })).toBeVisible();
    const after = await readApi('/api/profile');
    expect(after.xp_total).toBe(before.xp_total + debrief.xp);
    expect(after.runs_count).toBe(1);
    await page.reload();
    await expect(page.locator('.debrief-step')).toHaveCount(debrief.steps.length);
    const reloaded = await readApi('/api/profile');
    expect(reloaded.xp_total).toBe(after.xp_total);
    expect(reloaded.runs_count).toBe(1);
    await expect(page.locator('.topbar-user')).toContainText(`${after.xp_total} XP`);

    await page.getByRole('link', { name: 'В каталог', exact: true }).click();
    await expect(page.locator(`#${scenarioId} .scenario-result`)).toContainText('1 прохождение');
    await page.locator(`#${scenarioId}`).getByRole('link', { name: 'Как устроен сценарий' }).click();
    await expect(page.locator('svg.graph')).toBeVisible();
    const graph = await readApi(`/api/scenarios/${scenarioId}/graph`);
    await expect(page.locator('.graph-node')).toHaveCount(graph.nodes.length);
    expect(pageErrors).toEqual([]);
  });
}
