import { expect, test } from '@playwright/test';

async function login(page, request, displayName = 'Проверка восстановления') {
  const response = await request.post('/api/integration/employees', {
    headers: { 'X-API-Key': process.env.INTEGRATION_API_KEY || 'demo-integration-key' },
    data: { employee_code: `REC-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`, display_name: displayName, brigade: 'М-01' },
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

test('повтор из разбора сохраняет выбранный класс вагона', async ({ page, request }) => {
  await login(page, request);
  const token = await page.evaluate(() => localStorage.getItem('provodnik.token'));
  const headers = { Authorization: `Bearer ${token}` };
  const started = await request.post('/api/sessions', {
    headers,
    data: { scenario_id: 'smoking_vestibule', service_class: 'business' },
  });
  expect(started.status()).toBe(201);
  let run = await started.json();
  expect(run.context.service_class).toBe('business');
  for (let moves = 0; run.status === 'active' && moves < 20; moves += 1) {
    const choice = await request.post(`/api/sessions/${run.run_id}/choose`, {
      headers,
      data: { option_id: run.node.type === 'event' ? 'continue' : run.node.options[0].id, step_no: run.step_no },
    });
    expect(choice.status()).toBe(200);
    run = await choice.json();
  }
  expect(run.status).toBe('finished');
  await page.goto(`/debrief/${run.run_id}`);
  await page.getByRole('button', { name: 'Пройти снова', exact: true }).click();
  await expect(page).toHaveURL(/\/play\/\d+$/);
  await expect(page.locator('.context-bar strong')).toHaveText('Бизнес');
  const repeatedId = Number(page.url().match(/\/play\/(\d+)$/)[1]);
  expect(repeatedId).not.toBe(run.run_id);
  const repeated = await request.get(`/api/sessions/${repeatedId}`, { headers });
  expect(repeated.status()).toBe(200);
  expect((await repeated.json()).context.service_class).toBe('business');
});

test('смена аккаунта в другой вкладке очищает прежний профиль и историю', async ({ page, request }) => {
  await login(page, request, 'Первый сотрудник');
  await startSmoke(page);
  await page.goto('/profile');
  await expect(page.locator('.topbar-user strong')).toHaveText('Первый сотрудник');
  await expect(page.getByRole('heading', { name: 'Первый сотрудник', exact: true })).toBeVisible();
  await expect(page.locator('.runs-table tbody tr')).toHaveCount(1);

  const otherTab = await page.context().newPage();
  try {
    await login(otherTab, request, 'Второй сотрудник');
    await expect(page).toHaveURL(/\/profile$/);
    await expect(page.locator('.topbar-user strong')).toHaveText('Второй сотрудник');
    await expect(page.getByRole('heading', { name: 'Второй сотрудник', exact: true })).toBeVisible();
    await expect(page.getByText('Прохождений пока нет.', { exact: true })).toBeVisible();
    await expect(page.locator('.runs-table')).toHaveCount(0);
    await expect(page.getByText('Первый сотрудник', { exact: true })).toHaveCount(0);
  } finally {
    await otherTab.close();
  }
});

for (const failure of [false, true]) {
  test(`запоздалый выход не сбрасывает новый аккаунт${failure ? ' при сбое сети' : ''}`, async ({ page, request }) => {
    await login(page, request, 'Первый сотрудник');
    const oldToken = await page.evaluate(() => localStorage.getItem('provodnik.token'));
    await page.evaluate(() => {
      const originalFetch = window.fetch.bind(window);
      let settled;
      window.__logoutSettled = new Promise((resolve) => { settled = resolve; });
      // Метка следует за чтением тела/ошибкой fetch, а не только за сетевым событием браузера.
      const done = () => setTimeout(settled, 0);
      window.fetch = async (...args) => {
        if (args[0] !== '/api/auth/logout') return originalFetch(...args);
        try {
          const response = await originalFetch(...args);
          const originalText = response.text.bind(response);
          response.text = () => originalText().finally(done);
          return response;
        } catch (error) {
          done();
          throw error;
        }
      };
    });
    let releaseLogout;
    let logoutWaiting = false;
    const holdLogout = new Promise((resolve) => { releaseLogout = resolve; });
    await page.route('**/api/auth/logout', async (route) => {
      expect(route.request().headers().authorization).toBe(`Bearer ${oldToken}`);
      const response = await route.fetch();
      expect(response.ok()).toBe(true);
      logoutWaiting = true;
      await holdLogout;
      if (failure) return route.abort('failed');
      return route.fulfill({ response });
    });
    const otherTab = await page.context().newPage();
    try {
      await page.getByRole('button', { name: 'Выйти', exact: true }).click();
      await expect.poll(() => logoutWaiting).toBe(true);
      await login(otherTab, request, 'Второй сотрудник');
      await expect(page.locator('.topbar-user strong')).toHaveText('Второй сотрудник');
      const newToken = await otherTab.evaluate(() => localStorage.getItem('provodnik.token'));
      expect(newToken).not.toBe(oldToken);
      releaseLogout();
      await page.evaluate(() => window.__logoutSettled);
      expect(await page.evaluate(() => localStorage.getItem('provodnik.token'))).toBe(newToken);
      // Следующий переход запрашивает профиль и проверяет, что новая сессия осталась рабочей.
      await page.getByRole('link', { name: 'Профиль', exact: true }).click();
      await expect(page).toHaveURL(/\/profile$/);
      await expect(page.getByRole('heading', { name: 'Второй сотрудник', exact: true })).toBeVisible();
      await expect(otherTab.locator('.topbar-user strong')).toHaveText('Второй сотрудник');
    } finally {
      releaseLogout();
      await otherTab.close();
    }
  });
}

for (const failure of ['сети', 'формата ответа']) {
  test(`таймер повторяет истечение после временного сбоя ${failure}`, async ({ page, request }) => {
    test.setTimeout(45_000);
    await login(page, request);
    await startSmoke(page);
    let attempts = 0;
    await page.route('**/api/sessions/*/expire', async (route) => {
      attempts += 1;
      if (attempts !== 1) return route.continue();
      if (failure === 'сети') return route.abort('failed');
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"broken":' });
    });
    await page.locator('.option-button').first().click();
    await expect(page.locator('.timer-ring')).toBeVisible();
    await expect(page.locator('.notice-expired')).toBeVisible({ timeout: 30_000 });
    expect(attempts).toBe(2);
    await expect(page.locator('.error')).toHaveCount(0);
  });
}

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

test('зависший ответ принятого выбора ограничен тайм-аутом, обновление восстанавливает ход без повтора', async ({ page, request }) => {
  await login(page, request);
  await startSmoke(page);
  const runUrl = page.url();
  const runId = Number(runUrl.match(/\/play\/(\d+)$/)[1]);
  const token = await page.evaluate(() => localStorage.getItem('provodnik.token'));
  const headers = { Authorization: `Bearer ${token}` };
  let accepted;
  let attempts = 0;
  let release;
  const hold = new Promise((resolve) => { release = resolve; });
  await page.route('**/api/sessions/*/choose', async (route) => {
    attempts += 1;
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    accepted = await response.json();
    await hold;
    await route.fulfill({ response });
  });
  try {
    await page.locator('.option-button').first().click();
    await expect.poll(() => accepted?.step_no).toBe(1);
    await expect(page.locator('.option-button').first()).toBeDisabled();
    await expect(page.locator('.error')).toContainText('Сервер не ответил вовремя', { timeout: 15_000 });
    expect(attempts).toBe(1);
    release();
    await page.reload();
    await expect(page).toHaveURL(runUrl);
    await expect(page.locator('.step-no')).toHaveText(`Ход ${accepted.step_no + 1}`);
    await expect(page.locator('.error')).toHaveCount(0);
    const restored = await request.get(`/api/sessions/${runId}`, { headers });
    expect(restored.ok()).toBe(true);
    const state = await restored.json();
    expect(state.step_no).toBe(accepted.step_no);
    expect(state.node.id).toBe(accepted.node.id);
    expect(state.loyalty).toBe(accepted.loyalty);
    expect(state.safety).toBe(accepted.safety);
    expect(attempts).toBe(1);
  } finally {
    release();
  }
});
