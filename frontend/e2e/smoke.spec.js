import { expect, test } from '@playwright/test';

test('без входа открывается экран входа с названием тренажёра', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login$/);
  await expect(page).toHaveTitle('Проводник 400');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Проводник 400');
  await expect(page.getByText('Данные синтетические')).toBeVisible();
  // строка о сервере появляется только после успешного ответа /api/health через api.js
  await expect(page.locator('.server-status')).toContainText('Сервер');
});

test('неверный PIN показывает сообщение сервера, а не белый экран', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Код сотрудника').fill('VSM-1001');
  await page.getByLabel('PIN').fill('0000');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.locator('.login-form .error')).toContainText('Неверный код сотрудника или PIN');
  await expect(page).toHaveURL(/\/login$/);
});
