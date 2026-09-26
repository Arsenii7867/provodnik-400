import { expect, test } from '@playwright/test';

const API_KEY = process.env.INTEGRATION_API_KEY || 'demo-integration-key';
const SCENARIO = 'smoking_vestibule';
const MAX_MOVES = 20;

// Полный цикл нового сотрудника: HR-система создаёт его через интеграцию, он входит,
// проходит «Дым в тамбуре» с одним истечением таймера, читает покадровый разбор, а потом
// XP в шапке, уведомление, лидерборд, радар и карта сценария показывают то же, что сервер.
async function createEmployee(request) {
  const code = `VSM-E2E-${Date.now().toString().slice(-8)}`;
  const response = await request.post('/api/integration/employees', {
    headers: { 'X-API-Key': API_KEY },
    data: { employee_code: code, display_name: 'Проверочный проводник', brigade: 'М-01' },
  });
  expect(response.status()).toBe(201);
  const created = await response.json();
  return { code, pin: created.pin };
}

async function login(page, code, pin) {
  await page.goto('/login');
  await page.getByLabel('Код сотрудника').fill(code);
  await page.getByLabel('PIN').fill(pin);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Мой прогресс');
}

async function headerXp(page) {
  const text = await page.locator('.topbar-user').textContent();
  const match = text.match(/(\d+) XP/);
  expect(match).not.toBeNull();
  return Number(match[1]);
}

async function makeMove(page, choose) {
  const step = await page.locator('.step-no').textContent();
  const next = page.getByRole('button', { name: 'Далее' });
  if (await next.count()) {
    await next.click();
  } else {
    await choose();
  }
  await Promise.race([
    page.locator('.step-no', { hasNotText: step }).waitFor(),
    page.locator('.ending').waitFor(),
  ]);
}

test('новый сотрудник проходит сценарий с истечением таймера и видит замкнутый цикл', async ({ page, request }) => {
  test.setTimeout(180_000);
  const { code, pin } = await createEmployee(request);
  await login(page, code, pin);
  const xpBefore = await headerXp(page);
  const notificationsBefore = await page.locator('.notification').count();

  await page.goto('/scenarios');
  const card = page.locator('.scenario-card', { has: page.locator(`a[href="/scenarios/${SCENARIO}/map"]`) });
  await expect(card).toHaveCount(1);
  await card.getByRole('button', { name: 'Начать' }).click();
  await expect(page).toHaveURL(/\/play\/\d+$/);

  // первый ход: реплика с шагом «Признать», после неё узел с таймером
  await makeMove(page, () =>
    page.locator('.option-button', { has: page.locator('.option-role', { hasText: 'Признать' }) }).first().click(),
  );
  await expect(page.locator('.timer-ring')).toBeVisible();
  const timerStep = await page.locator('.step-no').textContent();
  await expect(page.locator('.notice-expired')).toBeVisible({ timeout: 125_000 });
  await expect(page.locator('.step-no')).not.toHaveText(timerStep);

  for (let moves = 0; moves < MAX_MOVES && (await page.locator('.ending').count()) === 0; moves += 1) {
    await makeMove(page, () => page.locator('.option-button').first().click());
  }
  await expect(page.locator('.ending')).toContainText('Исход');
  await page.getByRole('link', { name: 'Перейти к разбору' }).click();
  await expect(page).toHaveURL(/\/debrief\/\d+$/);

  // покадровый разбор: шаг истечения с «как лучше», стрелки по обеим шкалам с числами из API,
  // цитаты норм
  const token = await page.evaluate(() => localStorage.getItem('provodnik.token'));
  const auth = { Authorization: `Bearer ${token}` };
  const runId = page.url().match(/\/debrief\/(\d+)$/)[1];
  const debrief = await (await request.get(`/api/runs/${runId}/debrief`, { headers: auth })).json();
  const steps = page.locator('.debrief-step');
  await expect(steps.first()).toBeVisible();
  expect(await steps.count()).toBe(debrief.steps.length);
  expect(debrief.steps.length).toBeGreaterThanOrEqual(3);
  const firstArrows = steps.first().locator('.effect-arrow');
  await expect(firstArrows.first().locator('.effect-before')).toHaveText(String(debrief.steps[0].loyalty_before));
  await expect(firstArrows.first().locator('.effect-after')).toHaveText(String(debrief.steps[0].loyalty_after));
  await expect(firstArrows.nth(1).locator('.effect-before')).toHaveText(String(debrief.steps[0].safety_before));
  await expect(firstArrows.nth(1).locator('.effect-after')).toHaveText(String(debrief.steps[0].safety_after));
  const expired = page.locator('.debrief-step.step-expired');
  await expect(expired).toHaveCount(1);
  await expect(expired).toContainText('Таймер истёк');
  await expect(expired).toContainText('Как лучше');
  await expect(steps.first().locator('.effect-arrow')).toHaveCount(2);
  await expect(steps.first().locator('.ref').first()).toBeVisible();
  await steps.first().locator('.ref summary').first().click();
  await expect(steps.first().locator('.ref-body').first()).toBeVisible();
  await expect(page.locator('.debrief-new')).toContainText('Первый рейс');
  const heading = await page.getByRole('heading', { name: /Очки опыта: \d+ XP/ }).textContent();
  const xpRun = Number(heading.match(/(\d+) XP/)[1]);
  expect(xpRun).toBeGreaterThan(0);

  // профиль в шапке вырос ровно на XP разбора
  await expect(page.locator('.topbar-user')).toContainText(`${xpBefore + xpRun} XP`);

  // уведомление о достижении и его прочтение
  await page.goto('/');
  await expect(page.locator('.notification')).toHaveCount(notificationsBefore + 1);
  const fresh = page.locator('.notification-unread', { hasText: 'Первый рейс' });
  await expect(fresh).toHaveCount(1);
  await expect(page.locator('.topnav .unread-badge')).toBeVisible();
  await fresh.getByRole('button', { name: 'Прочитать' }).click();
  await expect(page.locator('.notification-unread', { hasText: 'Первый рейс' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Прочитать все' }).click();
  await expect(page.locator('.topnav .unread-badge')).toHaveCount(0);

  // профиль: достижение получено, остальные заблокированы с текстом правила, прохождение в истории
  await page.goto('/profile');
  await expect(page.locator('.achievement-earned')).toContainText('Первый рейс');
  await expect(page.locator('.achievement-locked .achievement-rule').first()).toContainText('Правило');
  await expect(page.locator('.runs-table tbody tr')).toHaveCount(1);

  // лидерборд: в бригаде своя строка в таблице, в компании один результат не входит в двадцатку,
  // и строка закрепляется внизу
  await page.goto('/leaderboard');
  await expect(page.locator('.scope-title')).toContainText('Бригада');
  await expect(page.locator('.board-me')).toContainText(code);
  await page.getByRole('button', { name: 'Компания' }).click();
  await expect(page.locator('.scope-title')).toHaveText('Компания');
  await expect(page.locator('.board-pinned')).toContainText(code);
  await expect(page.locator('.board-gap')).toBeVisible();

  // аналитика: радар с осью на каждую компетенцию из ответа
  await page.goto('/analytics');
  await expect(page.locator('svg.radar')).toBeVisible();
  const axes = await page.locator('.radar-axis').count();
  expect(axes).toBe(await page.locator('.radar-legend li').count());
  expect(axes).toBeGreaterThan(0);

  // карта сценария открылась после прохождения: узлов, таймеров и покрашенных концовок столько
  // же, сколько в ответе API
  const graph = await request.get(`/api/scenarios/${SCENARIO}/graph`, { headers: auth });
  expect(graph.status()).toBe(200);
  const nodes = (await graph.json()).nodes;
  await page.goto(`/scenarios/${SCENARIO}/map`);
  await expect(page.locator('svg.graph')).toBeVisible();
  await expect(page.locator('.graph-node')).toHaveCount(nodes.length);
  await expect(page.locator('.graph-timer')).toHaveCount(nodes.filter((node) => node.timer_seconds).length);
  const endings = nodes.filter((node) => node.type === 'ending');
  expect(endings.length).toBeGreaterThan(1);
  await expect(page.locator('[class*="graph-outcome-"]')).toHaveCount(endings.length);
});

test('наставник видит бригаду первым экраном, а в рейтинге не участвует', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('button', { name: /VSM-2001/ }).click();
  await page.getByLabel('PIN').fill(process.env.DEMO_PIN || '1234');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Бригада и уведомления');
  await expect(page.getByRole('heading', { name: 'Моя бригада' })).toBeVisible();

  await page.goto('/analytics');
  await expect(page.getByRole('button', { name: 'Бригада' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.team-table').first()).toBeVisible();
  await expect(page.locator('svg.radar')).toBeVisible();

  await page.goto('/leaderboard');
  await expect(page.getByText('Наставник в рейтинге не участвует')).toBeVisible();
  await expect(page.locator('.board-me')).toHaveCount(0);

  await page.goto(`/scenarios/${SCENARIO}/map`);
  await expect(page.locator('svg.graph')).toBeVisible();
});
