import { expect, test } from '@playwright/test';

const DEMO_CODE = 'VSM-1001';
const DEMO_PIN = process.env.DEMO_PIN || '1234';

async function login(page) {
  await page.goto('/login');
  await page.getByRole('button', { name: new RegExp(DEMO_CODE) }).click();
  await page.getByLabel('PIN').fill(DEMO_PIN);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Мой прогресс');
}

async function startTimedScenario(page) {
  await page.getByRole('link', { name: 'Сценарии' }).click();
  await expect(page).toHaveURL(/\/scenarios$/);
  const card = page.locator('.scenario-card', { hasText: 'с таймером' }).first();
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: 'Начать' }).click();
  await expect(page).toHaveURL(/\/play\/\d+$/);
}

async function scaleValues(page) {
  const texts = await page.locator('.scale-value').allTextContents();
  return texts.map(Number);
}

// ход считается сделанным, когда сервер вернул новое состояние и счётчик ходов сменился
async function makeMove(page) {
  const step = await page.locator('.step-no').textContent();
  const next = page.getByRole('button', { name: 'Далее' });
  if (await next.count()) {
    await next.click();
  } else {
    await page.locator('.option-button').first().click();
  }
  await Promise.race([
    page.locator('.step-no', { hasNotText: step }).waitFor(),
    page.locator('.ending').waitFor(),
  ]);
}

test('проводник входит, проходит сценарий с таймером и попадает в разбор', async ({ page }) => {
  await login(page);
  await startTimedScenario(page);

  const timer = page.locator('.timer-ring-value');
  await expect(timer).toHaveText(/^\d+:\d\d$/);
  const shown = await timer.textContent();
  await expect(timer).not.toHaveText(shown, { timeout: 3000 });

  await expect(page.locator('.scale-bar')).toHaveCount(2);
  const start = await scaleValues(page);
  expect(start).toHaveLength(2);

  await makeMove(page);
  await expect(page.locator('.scale-delta')).toHaveCount(2);
  const after = await scaleValues(page);
  expect(after).not.toEqual(start);

  for (let moves = 0; moves < 20 && (await page.locator('.ending').count()) === 0; moves += 1) {
    await makeMove(page);
  }
  await expect(page.locator('.ending')).toContainText('Исход');
  await page.getByRole('link', { name: 'Перейти к разбору' }).click();
  await expect(page).toHaveURL(/\/debrief\/\d+$/);
  await expect(page.locator('.debrief-outcome')).toContainText(/Образцово|Приемлемо|Инцидент/);
  await expect(page.locator('.scale-bar')).toHaveCount(2);
  await expect(page.getByRole('heading', { name: /Очки опыта: \d+ XP/ })).toBeVisible();
});

test('истёкший таймер блокирует варианты, сервер ведёт по ветке истечения', async ({ page }) => {
  test.setTimeout(150_000);
  await login(page);
  await startTimedScenario(page);

  for (let moves = 0; moves < 20 && (await page.locator('.timer-ring').count()) === 0; moves += 1) {
    await makeMove(page);
  }
  await expect(page.locator('.timer-ring')).toBeVisible();
  const step = await page.locator('.step-no').textContent();
  const optionsBefore = await page.locator('.option-button').count();
  expect(optionsBefore).toBeGreaterThan(1);

  // таймеры сценариев не длиннее двух минут; ждём, пока клиент сообщит серверу об истечении
  await expect(page.locator('.notice-expired')).toBeVisible({ timeout: 125_000 });
  await expect(page.locator('.step-no')).not.toHaveText(step);
  await expect(page.locator('.last-step-expired')).toContainText('таймер истёк');
  const scales = await scaleValues(page);
  expect(scales.every((value) => value >= 0 && value <= 100)).toBe(true);
});
