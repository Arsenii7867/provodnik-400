import { expect, test } from '@playwright/test';

async function login(page, request) {
  const response = await request.post('/api/integration/employees', {
    headers: { 'X-API-Key': process.env.INTEGRATION_API_KEY || 'demo-integration-key' },
    data: { employee_code: `LOAD-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`, display_name: 'Проверка загрузки', brigade: 'М-01' },
  });
  expect(response.status()).toBe(201);
  const employee = await response.json();
  await page.goto('/login');
  await page.getByLabel('Код сотрудника').fill(employee.employee_code);
  await page.getByLabel('PIN').fill(employee.pin);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Мой прогресс', exact: true })).toBeVisible();
  // This marker disappears on document reload, but survives ordinary SPA navigation.
  await page.evaluate(() => { window.__loadRetryDocument = 'same-document'; });
}

function recordWrites(page) {
  const writes = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/api/')) {
      writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    }
  });
  return writes;
}

async function unchangedDocument(page, writes) {
  expect(await page.evaluate(() => window.__loadRetryDocument)).toBe('same-document');
  expect(writes).toEqual([]);
}

test('каталог повторяет GET с прежним фильтром, блокирует повтор до ответа и восстанавливается после второго сбоя', async ({ page, request }) => {
  await login(page, request);
  await page.getByRole('link', { name: 'Сценарии', exact: true }).click();
  await expect(page.locator('.scenario-card').first()).toBeVisible();
  const writes = recordWrites(page);
  const paths = [];
  let release;
  const hold = new Promise((resolve) => { release = resolve; });
  await page.route('**/api/scenarios?difficulty=2', async (route) => {
    paths.push(new URL(route.request().url()).search);
    if (paths.length === 1) return route.abort('failed');
    if (paths.length === 2) {
      await hold;
      return route.fulfill({ status: 503, json: { error: { code: 'unavailable', message: 'Каталог временно недоступен' } } });
    }
    return route.continue();
  });
  try {
    await page.getByRole('combobox', { name: 'Сложность', exact: true }).selectOption('2');
    const retry = page.getByRole('button', { name: 'Повторить загрузку: каталог', exact: true });
    await expect(retry).toBeVisible();
    expect(paths).toHaveLength(1);
    await retry.click();
    await expect.poll(() => paths.length).toBe(2);
    await expect(retry).toBeDisabled();
    await expect(retry).toHaveText('Повторяем…');
    await expect(page.getByRole('combobox', { name: 'Сложность', exact: true })).toHaveValue('2');
    release();
    await expect(retry).toBeEnabled();
    await expect(retry).toHaveText('Повторить');
    await expect(page.getByText('Каталог временно недоступен', { exact: true })).toBeVisible();
    await retry.click();
    await expect(retry).toHaveCount(0);
    await expect(page.locator('.scenario-card').first()).toBeVisible();
    await expect(page.getByRole('combobox', { name: 'Сложность', exact: true })).toHaveValue('2');
    expect(paths).toEqual(['?difficulty=2', '?difficulty=2', '?difficulty=2']);
    await unchangedDocument(page, writes);
  } finally {
    release();
  }
});

test('ошибка общего профиля восстанавливается повторным GET без перезагрузки документа', async ({ page, request }) => {
  await login(page, request);
  const writes = recordWrites(page);
  let attempts = 0;
  await page.route('**/api/profile', (route) => {
    attempts += 1;
    if (attempts === 1) {
      return route.fulfill({ status: 503, json: { error: { code: 'unavailable', message: 'Профиль временно недоступен' } } });
    }
    return route.continue();
  });
  await page.getByRole('link', { name: 'Профиль', exact: true }).click();
  const retry = page.getByRole('button', { name: 'Повторить загрузку: профиль', exact: true });
  await expect(retry).toBeVisible();
  expect(attempts).toBe(1);
  await retry.click();
  await expect(retry).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Проверка загрузки', exact: true })).toBeVisible();
  await expect(page.locator('.topbar-user strong')).toHaveText('Проверка загрузки');
  expect(attempts).toBe(2);
  await unchangedDocument(page, writes);
});

test('ошибка загрузки прохождения повторяет только GET того же run и сохраняет его ход', async ({ page, request }) => {
  await login(page, request);
  await page.getByRole('link', { name: 'Сценарии', exact: true }).click();
  await page.locator('#smoking_vestibule').getByRole('button', { name: 'Начать' }).click();
  await expect(page.locator('.option-button').first()).toBeVisible();
  const runUrl = page.url();
  const runPath = new URL(runUrl).pathname.replace('/play/', '/api/sessions/');
  const step = await page.locator('.step-no').textContent();
  const choice = await page.locator('.option-button').first().textContent();
  await page.getByRole('link', { name: /^Главная/ }).click();
  await expect(page.getByRole('button', { name: 'Продолжить', exact: true })).toBeVisible();
  const writes = recordWrites(page);
  const paths = [];
  await page.route(`**${runPath}`, (route) => {
    paths.push(new URL(route.request().url()).pathname);
    if (paths.length === 1) return route.abort('failed');
    return route.continue();
  });
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click();
  const retry = page.getByRole('button', { name: 'Повторить загрузку: прохождение', exact: true });
  await expect(retry).toBeVisible();
  await expect(page.locator('.option-button')).toHaveCount(0);
  expect(paths).toEqual([runPath]);
  await retry.click();
  await expect(retry).toHaveCount(0);
  await expect(page).toHaveURL(runUrl);
  await expect(page.locator('.step-no')).toHaveText(step);
  await expect(page.locator('.option-button').first()).toHaveText(choice);
  expect(paths).toEqual([runPath, runPath]);
  await unchangedDocument(page, writes);
});
