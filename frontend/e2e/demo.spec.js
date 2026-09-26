import path from 'node:path';

import { expect, test } from '@playwright/test';

const DEMO_CODE = 'VSM-1001';
const DEMO_PIN = process.env.DEMO_PIN || '1234';
const SCENARIO = 'smoking_vestibule';
const MAX_MOVES = 20;
const PAUSE_MS = 1800;

// Запись демонстрации для README: путь из docs/user_flow.md («Сценарий демонстрации по кликам»)
// на свежей базе из сида. Первое прохождение «Дыма в тамбуре» идёт лучшим путём с ответом под
// таймером, второе оставляет таймер истечь, чтобы в записи была ветка истечения; дальше разбор,
// дашборд, профиль, лидерборд, аналитика и карта сценария. Паузы и подпись внизу кадра нужны
// только ради читаемости видео. Проект demo включается переменной DEMO_VIDEO (playwright.config.js):
//   DEMO_VIDEO=1 BASE_URL=http://127.0.0.1:8000 npx playwright test --project demo
// Запись ложится в test-results/demo.webm, GIF для README из неё делает ffmpeg:
//   ffmpeg -i test-results/demo.webm -vf "fps=10,scale=960:-1" -loop 0 ../docs/media/demo.gif

// подпись живёт вне корня React и переживает переходы между экранами; клики сквозь неё проходят
async function caption(page, text) {
  await page.evaluate((value) => {
    let bar = document.getElementById('demo-caption');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'demo-caption';
      bar.style.cssText =
        'position:fixed;left:0;right:0;bottom:0;padding:10px 24px;background:rgba(20,58,117,0.92);' +
        'color:#fff;font-size:17px;font-weight:600;line-height:1.3;z-index:1000;pointer-events:none;';
      document.body.style.paddingBottom = '48px';
      document.body.appendChild(bar);
    }
    bar.textContent = value;
  }, text);
}

async function show(page, locator, ms = PAUSE_MS) {
  await locator.first().evaluate((node) => node.scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(ms);
}

function nav(page, name) {
  return page.locator('.topnav').getByRole('link', { name, exact: true });
}

function optionWithRole(page, title) {
  return page.locator('.option-button', { has: page.locator('.option-role', { hasText: title }) });
}

async function headerXp(page) {
  const text = await page.locator('.topbar-user').textContent();
  return Number(text.match(/(\d+) XP/)[1]);
}

async function debriefXp(page) {
  const heading = await page.getByRole('heading', { name: /Очки опыта: \d+ XP/ }).textContent();
  return Number(heading.match(/(\d+) XP/)[1]);
}

// ход сделан, когда сервер вернул новое состояние: сменился счётчик ходов или показана концовка
async function choose(page, option) {
  const step = await page.locator('.step-no').textContent();
  await option.first().click();
  await Promise.race([
    page.locator('.step-no', { hasNotText: step }).waitFor(),
    page.locator('.ending').waitFor(),
  ]);
}

test('запись демонстрации: вход, два прохождения, разбор, профиль, лидерборд, аналитика, карта', async ({ page }, testInfo) => {
  test.setTimeout(300_000);

  await page.goto('/login');
  await expect(page.locator('.server-status')).toContainText('Сервер');
  await caption(page, 'Вход: демо-профиль проводника, все сотрудники синтетические');
  await page.waitForTimeout(PAUSE_MS);
  await page.getByRole('button', { name: new RegExp(DEMO_CODE) }).click();
  await page.getByLabel('PIN').pressSequentially(DEMO_PIN, { delay: 200 });
  await page.waitForTimeout(600);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Мой прогресс');
  const xpBefore = await headerXp(page);

  await caption(page, 'Дашборд: уровень и полоса XP, последний результат, рекомендации, челленджи');
  await page.waitForTimeout(PAUSE_MS);
  await show(page, page.getByRole('heading', { name: 'Челленджи' }));
  await caption(page, 'Уведомления: новый сценарий, челлендж, сгорающие баллы, достижения, уровень');
  await show(page, page.getByRole('heading', { name: /^Уведомления/ }));

  await nav(page, 'Сценарии').click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Сценарии');
  await caption(page, 'Каталог: фильтры по компетенции, сложности и классу вагона; карточка с таймером');
  await page.waitForTimeout(PAUSE_MS);
  const card = page.locator(`#${SCENARIO}`);
  await show(page, card);
  await card.getByRole('button', { name: 'Начать' }).click();
  await expect(page).toHaveURL(/\/play\/\d+$/);

  // первое прохождение: лучший путь, ответ под таймером
  await expect(page.locator('.scale-bar')).toHaveCount(2);
  await caption(page, 'Прохождение: контекст поезда, две шкалы, реплика пассажира, шаг «Признать»');
  await page.waitForTimeout(PAUSE_MS);
  await choose(page, optionWithRole(page, 'Признать'));
  await expect(page.locator('.timer-ring')).toBeVisible();
  await caption(page, 'Таймер 20 секунд идёт по часам сервера: правило и вызов ПТБ до истечения');
  await page.waitForTimeout(4000);
  await choose(page, page.locator('.option-button', { hasText: 'вызываю ПТБ' }));
  await caption(page, 'Шаг «Решение»: алкоголь только в вагоне-бистро, тамбур проверен на тление');
  await page.waitForTimeout(PAUSE_MS);
  await choose(page, optionWithRole(page, 'Решение'));
  await caption(page, 'Шаг «Заверить»: доклад начальнику поезда с фактами об устройстве');
  await page.waitForTimeout(PAUSE_MS);
  await choose(page, page.locator('.option-button', { hasText: 'электронная сигарета, чёрная' }));
  await expect(page.locator('.ending')).toContainText('Образцово');
  await caption(page, 'Концовка «Тамбур чист»: исход образцово, XP начислены сервером');
  await page.waitForTimeout(PAUSE_MS + 700);
  await page.getByRole('link', { name: 'Перейти к разбору' }).click();

  await expect(page).toHaveURL(/\/debrief\/\d+$/);
  await expect(page.locator('.debrief-outcome')).toContainText('Образцово');
  const xpFirst = await debriefXp(page);
  await caption(page, 'Разбор: исход, финальные шкалы, раскладка XP, цепочка ролевой модели');
  await page.waitForTimeout(PAUSE_MS);
  const rewards = page.locator('.debrief-new');
  await expect(rewards).toContainText('Четыре шага');
  await expect(rewards).toContainText('Новый уровень');
  await caption(page, 'Новое после прохождения: достижения по правилам из YAML и новый уровень');
  await show(page, rewards);
  const firstStep = page.locator('.debrief-step').first();
  await caption(page, 'По шагам: вердикт, стрелки обеих шкал, почему так, цитата нормы по клику');
  await show(page, firstStep);
  await firstStep.locator('.ref summary').first().click();
  await expect(firstStep.locator('.ref-body').first()).toBeVisible();
  await show(page, firstStep.locator('.ref-body').first(), PAUSE_MS + 500);

  // второе прохождение: таймер истекает, сервер ведёт по ветке истечения
  await caption(page, 'Второй заход: в узле с таймером ничего не нажимаем');
  await page.getByRole('button', { name: 'Пройти снова' }).click();
  await expect(page).toHaveURL(/\/play\/\d+$/);
  await page.waitForTimeout(PAUSE_MS);
  await choose(page, optionWithRole(page, 'Признать'));
  await expect(page.locator('.timer-ring')).toBeVisible();
  const timerStep = await page.locator('.step-no').textContent();
  await caption(page, 'Таймер истекает: варианты блокируются, сервер сам применяет ветку истечения');
  await expect(page.locator('.notice-expired')).toBeVisible({ timeout: 40_000 });
  await expect(page.locator('.step-no')).not.toHaveText(timerStep);
  await page.waitForTimeout(PAUSE_MS + 700);
  await caption(page, 'Событие сценария: дым пошёл в салон, сработал датчик задымления');
  for (let moves = 0; moves < MAX_MOVES && (await page.locator('.ending').count()) === 0; moves += 1) {
    await page.waitForTimeout(PAUSE_MS);
    await choose(page, page.locator('.option-button'));
  }
  await expect(page.locator('.ending')).toContainText('Инцидент');
  await caption(page, 'Концовка «Задымление в тамбуре»: инцидент, образцовый исход закрыт');
  await page.waitForTimeout(PAUSE_MS + 700);
  await page.getByRole('link', { name: 'Перейти к разбору' }).click();
  await expect(page).toHaveURL(/\/debrief\/\d+$/);
  const xpSecond = await debriefXp(page);
  const expired = page.locator('.debrief-step.step-expired');
  await expect(expired).toHaveCount(1);
  await expect(expired).toContainText('Как лучше');
  await caption(page, 'В разборе шаг истечения: «Таймер истёк», как лучше и цитата карточки 20');
  await show(page, expired, PAUSE_MS + 1200);

  // замкнутый цикл: шапка, уведомления, профиль, лидерборд, аналитика, карта
  await page.locator('.topnav').getByRole('link', { name: /^Главная/ }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Мой прогресс');
  await expect(page.locator('.topbar-user')).toContainText(`${xpBefore + xpFirst + xpSecond} XP`);
  await caption(page, 'Дашборд после прохождений: XP и уровень в шапке, место в бригаде, уведомления');
  await page.waitForTimeout(PAUSE_MS);
  await expect(page.locator('.notification-unread').first()).toBeAttached();
  await show(page, page.getByRole('heading', { name: /^Уведомления/ }), PAUSE_MS + 500);

  await nav(page, 'Профиль').click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Профиль');
  await caption(page, 'Профиль: уровень, владение компетенциями, достижения с правилами, история');
  await page.waitForTimeout(PAUSE_MS);
  const earned = page.locator('.achievement-earned', { hasText: 'Четыре шага' });
  await expect(earned).toHaveCount(1);
  await show(page, earned, PAUSE_MS + 500);

  await nav(page, 'Лидерборд').click();
  await expect(page.locator('.board-me')).toContainText(DEMO_CODE);
  await caption(page, 'Лидерборд бригады: сумма лучших результатов плюс действующие бонусы челленджей');
  await page.waitForTimeout(PAUSE_MS + 500);
  await page.getByRole('button', { name: 'Компания' }).click();
  await expect(page.locator('.scope-title')).toHaveText('Компания');
  await caption(page, 'Охват «Компания»: своя строка закреплена внизу, если не вошла в двадцатку');
  await page.waitForTimeout(PAUSE_MS + 500);

  await nav(page, 'Аналитика').click();
  await expect(page.locator('svg.radar')).toBeVisible();
  await caption(page, 'Аналитика: радар владения, проседающие компетенции, пробелы, темп и эскалация');
  await page.waitForTimeout(PAUSE_MS + 500);
  await caption(page, 'Рекомендации с причиной: сценарии под проседающую компетенцию');
  await show(page, page.getByRole('heading', { name: 'Рекомендованные сценарии' }), PAUSE_MS + 500);

  await nav(page, 'Сценарии').click();
  await card.getByRole('link', { name: 'Как устроен сценарий' }).click();
  await expect(page.locator('svg.graph')).toBeVisible();
  await caption(page, 'Карта сценария: граф из YAML, таймер и ветка истечения, концовки по исходам');
  await page.waitForTimeout(PAUSE_MS + 1200);
  await caption(page, 'Пути и исходы посчитаны сервером; развилка добавляется правкой YAML без пересборки');
  await show(page, page.getByRole('heading', { name: 'Пути и исходы' }));
  await show(page, page.getByRole('heading', { name: 'Развилка за три минуты' }), PAUSE_MS + 500);

  await page.close();
  await page.video().saveAs(path.join(testInfo.project.outputDir, 'demo.webm'));
});
