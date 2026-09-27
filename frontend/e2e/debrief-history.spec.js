import { expect, test } from '@playwright/test';

test('разбор отличает сохранённую историю от старых и частичных пояснений', async ({ page, request }) => {
  const created = await request.post('/api/integration/employees', {
    headers: { 'X-API-Key': process.env.INTEGRATION_API_KEY || 'demo-integration-key' },
    data: { employee_code: `HIST-${Date.now()}`, display_name: 'История разбора', brigade: 'М-01' },
  });
  expect(created.status()).toBe(201);
  const employee = await created.json();
  await page.goto('/login');
  await page.getByLabel('Код сотрудника').fill(employee.employee_code);
  await page.getByLabel('PIN').fill(employee.pin);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Мой прогресс', exact: true })).toBeVisible();
  const token = await page.evaluate(() => localStorage.getItem('provodnik.token'));
  const headers = { Authorization: `Bearer ${token}` };
  const started = await request.post('/api/sessions', { headers, data: { scenario_id: 'smoking_vestibule' } });
  expect(started.status()).toBe(201);
  let run = await started.json();
  for (let move = 0; run.status === 'active' && move < 20; move += 1) {
    const chosen = await request.post(`/api/sessions/${run.run_id}/choose`, {
      headers, data: { option_id: run.node.type === 'event' ? 'continue' : run.node.options[0].id, step_no: run.step_no },
    });
    expect(chosen.status()).toBe(200);
    run = await chosen.json();
  }
  expect(run.status).toBe('finished');
  const response = await request.get(`/api/runs/${run.run_id}/debrief`, { headers });
  expect(response.status()).toBe(200);
  const saved = await response.json();
  expect(saved.history_status).toBe('snapshot');
  await page.goto(`/debrief/${run.run_id}`);
  await expect(page.getByRole('heading', { name: saved.title, exact: true })).toBeVisible();
  await expect(page.getByText('Исторические пояснения этого шага не сохранены.', { exact: true })).toHaveCount(0);
  // API compatibility states are injected only to exercise their visible disclosure.
  for (const status of ['legacy', 'partial']) {
    await page.route(`**/api/runs/${run.run_id}/debrief`, (route) => route.fulfill({
      json: { ...saved, history_status: status, steps: saved.steps.map((step) => ({ ...step, history_status: 'legacy' })) },
    }));
    await page.reload();
    const warning = status === 'legacy' ? 'Это старое прохождение' : 'Разбор сохранён частично';
    await expect(page.getByRole('status').filter({ hasText: warning })).toBeVisible();
    await expect(page.getByText('Исторические пояснения этого шага не сохранены.', { exact: true })).toHaveCount(saved.steps.length);
    await page.unroute(`**/api/runs/${run.run_id}/debrief`);
  }
});
