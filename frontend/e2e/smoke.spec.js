import { expect, test } from '@playwright/test';

test('главная страница открывается и показывает название тренажёра', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle('Проводник 400');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Проводник 400');
  // строка о сервере появляется только после успешного ответа /api/health через api.js
  await expect(page.locator('.server-status')).toContainText('Сервер');
});
