import { expect, test } from '@playwright/test';

async function login(page, request) {
  const response = await request.post('/api/integration/employees', {
    headers: { 'X-API-Key': process.env.INTEGRATION_API_KEY || 'demo-integration-key' },
    data: { employee_code: `REC-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`, display_name: 'Проверка восстановления', brigade: 'М-01' },
  });
  expect(response.status()).toBe(201);
  const employee = await response.json();
  await page.goto('/login');
  await page.getByLabel('Код сотрудника').fill(employee.employee_code);
  await page.getByLabel('PIN').fill(employee.pin);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Мой прогресс', exact: true })).toBeVisible();
}

async function startSmoke(page) {
  await page.goto('/scenarios');
  await page.locator('#smoking_vestibule').getByRole('button', { name: 'Начать' }).click();
  await expect(page.locator('.option-button').first()).toBeVisible();
}

test('таймер повторяет истечение после временного сбоя сети', async ({ page, request }) => {
  test.setTimeout(45_000);
  await login(page, request);
  await startSmoke(page);
  let attempts = 0;
  await page.route('**/api/sessions/*/expire', async (route) => {
    attempts += 1;
    if (attempts === 1) await route.abort('failed');
    else await route.continue();
  });
  await page.locator('.option-button').first().click();
  await expect(page.locator('.timer-ring')).toBeVisible();
  await expect(page.locator('.notice-expired')).toBeVisible({ timeout: 30_000 });
  expect(attempts).toBe(2);
  await expect(page.locator('.error')).toHaveCount(0);
});

test('отложенный повтор истечения отменяется при уходе со страницы', async ({ page, request }) => {
  await login(page, request);
  await page.clock.install();
  await startSmoke(page);
  let attempts = 0;
  await page.route('**/api/sessions/*/expire', async (route) => {
    attempts += 1;
    await route.abort('failed');
  });
  await page.locator('.option-button').first().click();
  await expect(page.locator('.timer-ring')).toBeVisible();
  await page.clock.fastForward(22_000);
  await expect(page.locator('.error')).toContainText('Сервер недоступен');
  await page.getByRole('button', { name: 'На главную' }).click();
  await expect(page.getByRole('heading', { name: 'Мой прогресс', exact: true })).toBeVisible();
  await page.clock.runFor(4000);
  expect(attempts).toBe(1);
});

test('два одновременных прочтения сохраняют оба уведомления прочитанными', async ({ page, request }) => {
  const items = [1, 2].map((id) => ({ id, kind: 'achievement', title: `Уведомление ${id}`, body: '', created_at: new Date().toISOString(), read_at: null }));
  await page.route('**/api/notifications', (route) => route.fulfill({ json: items }));
  const pending = [];
  await page.route('**/api/notifications/*/read', async (route) => {
    const id = Number(route.request().url().match(/notifications\/(\d+)/)[1]);
    await new Promise((resolve) => pending.push(resolve));
    await route.fulfill({ json: { ...items.find((item) => item.id === id), read_at: new Date().toISOString() } });
  });
  await login(page, request);
  await page.locator('.notification').nth(0).getByRole('button', { name: 'Прочитать', exact: true }).click();
  await page.locator('.notification').nth(1).getByRole('button', { name: 'Прочитать', exact: true }).click();
  await expect.poll(() => pending.length).toBe(2);
  pending[0]();
  await expect(page.locator('.notification-unread')).toHaveCount(1);
  pending[1]();
  await expect(page.locator('.notification-unread')).toHaveCount(0);
  await expect(page.locator('.topnav .unread-badge')).toHaveCount(0);
});

test('отозванный токен отправляет на вход при выборе ответа', async ({ page, request }) => {
  await login(page, request);
  await startSmoke(page);
  const token = await page.evaluate(() => localStorage.getItem('provodnik.token'));
  const logout = await request.post('/api/auth/logout', { headers: { Authorization: `Bearer ${token}` } });
  expect(logout.ok()).toBe(true);
  await page.locator('.option-button').first().click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByLabel('PIN')).toBeVisible();
});

test('после потерянного ответа новый класс запускается с новым ключом', async ({ page, request }) => {
  await login(page, request);
  await page.goto('/scenarios');
  const card = page.locator('#smoking_vestibule');
  let first = true;
  await page.route('**/api/sessions', async (route) => {
    if (!first) return route.continue();
    first = false;
    const created = await route.fetch();
    expect(created.ok()).toBe(true);
    await route.abort('failed');
  });
  await card.getByRole('combobox').selectOption('standard');
  await card.getByRole('button', { name: 'Начать' }).click();
  await expect(page.locator('.error')).toContainText('Сервер недоступен');
  await card.getByRole('combobox').selectOption('business');
  await card.getByRole('button', { name: 'Начать' }).click();
  await expect(page).toHaveURL(/\/play\/\d+$/);
  await expect(page.locator('.context-bar strong')).toHaveText('Бизнес');
});

test('прогресс уровня имеет имя и значение в допустимых пределах', async ({ page, request }) => {
  await login(page, request);
  for (const path of ['/', '/profile']) {
    await page.goto(path);
    const bar = page.getByRole('progressbar', { name: 'Прогресс уровня' });
    await expect(bar).toBeVisible();
    const value = Number(await bar.getAttribute('aria-valuenow'));
    expect(value).toBeGreaterThanOrEqual(0);
    expect(value).toBeLessThanOrEqual(100);
  }
});
