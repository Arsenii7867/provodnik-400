import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

// Проверяем ширину документа, а не таблиц внутри намеренных overflow-x:auto контейнеров.
// Ожидания по данным стоят перед этой проверкой: пустой экран загрузки её не заменяет.
async function fitsViewport(page, screen) {
  const viewport = page.viewportSize();
  expect(await page.evaluate(() => document.documentElement.clientWidth), screen).toBe(viewport.width);
  await expect.poll(
    () => page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - document.documentElement.clientWidth),
    { message: `${screen}: документ не должен прокручиваться по горизонтали` },
  ).toBeLessThanOrEqual(1);
  await expect(page.locator('.error'), screen).toHaveCount(0);
  const navigation = page.locator('.topnav a');
  await expect(navigation).toHaveCount(5);
  for (const link of await navigation.all()) {
    const box = await link.boundingBox();
    expect(box, `${screen}: ссылка навигации видима`).not.toBeNull();
    expect(box.x, screen).toBeGreaterThanOrEqual(-1);
    expect(box.x + box.width, screen).toBeLessThanOrEqual(viewport.width + 1);
    expect(box.height, `${screen}: высота области нажатия`).toBeGreaterThanOrEqual(24);
  }
}

async function tapControl(page, control) {
  await expect(control).toBeVisible();
  await expect(control).toBeEnabled();
  await control.scrollIntoViewIfNeeded();
  const box = await control.boundingBox();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(-1);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize().width + 1);
  expect(box.width).toBeGreaterThanOrEqual(24);
  expect(box.height).toBeGreaterThanOrEqual(24);
  // Настоящий touch проверяет, что цель не перекрыта и получает событие без force.
  await control.tap();
}

test('мобильный путь: экраны помещаются по ширине, навигация и действия доступны касанием', async ({ page, request, isMobile }) => {
  test.skip(!isMobile, 'Проверка мобильной компоновки запускается в mobile-chromium и mobile-webkit');
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const created = await request.post('/api/integration/employees', {
    headers: { 'X-API-Key': process.env.INTEGRATION_API_KEY || 'demo-integration-key' },
    data: {
      employee_code: `MOB-${randomUUID().slice(0, 16)}`,
      display_name: 'Мобильный проводник',
      brigade: 'М-01',
    },
  });
  expect(created.status()).toBe(201);
  const employee = await created.json();
  await page.goto('/login');
  await page.getByLabel('Код сотрудника').fill(employee.employee_code);
  await page.getByLabel('PIN').fill(employee.pin);
  await tapControl(page, page.getByRole('button', { name: 'Войти', exact: true }));
  await expect(page.getByRole('heading', { name: 'Мой прогресс', exact: true })).toBeVisible();
  const token = await page.evaluate(() => localStorage.getItem('provodnik.token'));
  async function readApi(path) {
    const response = await request.get(path, { headers: { Authorization: `Bearer ${token}` } });
    expect(response.status(), path).toBe(200);
    return response.json();
  }
  async function dashboardReady() {
    const [notifications, challenges] = await Promise.all([readApi('/api/notifications'), readApi('/api/challenges')]);
    await expect(page.getByRole('link', { name: 'Аналитика компетенций', exact: true })).toBeVisible();
    await expect(page.locator('.notification')).toHaveCount(notifications.length);
    await expect(page.locator('.challenge')).toHaveCount(challenges.length);
    await fitsViewport(page, 'Главная');
  }
  async function navigate(name, path) {
    await tapControl(page, page.locator('.topnav').getByRole('link', { name, exact: true }));
    await expect(page).toHaveURL(new RegExp(`${path}$`));
  }

  await dashboardReady();
  await navigate('Сценарии', '/scenarios');
  await expect(page.locator('.scenario-card')).toHaveCount(8);
  await expect(page.locator('.filters select').first().locator('option').nth(1)).toBeAttached();
  await fitsViewport(page, 'Каталог');
  await tapControl(page, page.locator('#smoking_vestibule').getByRole('button', { name: 'Начать', exact: true }));
  await expect(page).toHaveURL(/\/play\/\d+$/);
  await expect(page.locator('.option-button').first()).toBeVisible();

  for (let moves = 0; moves < 20 && (await page.locator('.ending').count()) === 0; moves += 1) {
    await fitsViewport(page, `Прохождение, ход ${moves + 1}`);
    const step = await page.locator('.step-no').textContent();
    await tapControl(page, page.locator('.option-button').first());
    await expect(page.locator('.step-no')).not.toHaveText(step);
  }
  await expect(page.locator('.ending')).toContainText('Образцово');
  await tapControl(page, page.getByRole('link', { name: 'Перейти к разбору', exact: true }));
  await expect(page.locator('.debrief-step')).toHaveCount(4);
  await expect(page.getByRole('heading', { name: /Очки опыта: \d+ XP/ })).toBeVisible();
  await fitsViewport(page, 'Разбор');

  await navigate('Профиль', '/profile');
  await expect(page.locator('.achievement-earned').first()).toBeVisible();
  await expect(page.locator('.runs-table tbody tr')).toHaveCount(1);
  await fitsViewport(page, 'Профиль');

  await navigate('Лидерборд', '/leaderboard');
  await expect(page.locator('.scope-title')).toContainText('Бригада');
  await expect(page.locator('.board-me')).toContainText(employee.employee_code);
  await fitsViewport(page, 'Лидерборд бригады');
  await tapControl(page, page.getByRole('button', { name: 'Компания', exact: true }));
  await expect(page.locator('.scope-title')).toHaveText('Компания');
  await expect(page.locator('.board-me')).toContainText(employee.employee_code);
  await fitsViewport(page, 'Лидерборд компании');

  await navigate('Аналитика', '/analytics');
  await expect(page.locator('svg.radar')).toBeVisible();
  await expect(page.locator('.analytics-summary')).toBeVisible();
  await fitsViewport(page, 'Аналитика');

  // Достижения после прохождения добавляют непрочитанные уведомления и кнопку «Прочитать все».
  await navigate(/^Главная/, '/');
  await dashboardReady();
  await expect(page.locator('.notification-unread').first()).toBeVisible();
  await tapControl(page, page.getByRole('button', { name: 'Прочитать все', exact: true }));
  await expect(page.locator('.notification-unread')).toHaveCount(0);
  await fitsViewport(page, 'Главная после прочтения');
  await tapControl(page, page.getByRole('button', { name: 'Выйти', exact: true }));
  await expect(page).toHaveURL(/\/login$/);
  expect(pageErrors).toEqual([]);
});
