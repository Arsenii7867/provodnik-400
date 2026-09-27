import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium, defineConfig, devices } from '@playwright/test';

const here = path.dirname(fileURLToPath(import.meta.url));
const backend = path.resolve(here, '..', 'backend');
const python =
  process.platform === 'win32'
    ? path.join(backend, '.venv', 'Scripts', 'python.exe')
    : path.join(backend, '.venv', 'bin', 'python');
const defaultPort = 8010;
const baseURL = process.env.BASE_URL || `http://127.0.0.1:${defaultPort}`;

// Браузер Playwright берётся из кэша, если он скачан (npx playwright install chromium);
// иначе тесты идут в установленном Chrome. PW_CHANNEL задаёт канал явно (chrome, msedge).
const channel = process.env.PW_CHANNEL || (fs.existsSync(chromium.executablePath()) ? undefined : 'chrome');

// Один профиль на запуск: расширенная матрица задаёт PW_PROJECT явно, обычная проверка
// остаётся в Chromium/Chrome. Мобильные профили эмулируют viewport и touch устройства.
const projectName = process.env.PW_PROJECT || 'chromium';
const browserProfiles = {
  chromium: { ...devices['Desktop Chrome'], browserName: 'chromium', channel },
  firefox: { ...devices['Desktop Firefox'], browserName: 'firefox' },
  webkit: { ...devices['Desktop Safari'], browserName: 'webkit' },
  'mobile-chromium': { ...devices['Pixel 7'], browserName: 'chromium', channel },
  'mobile-webkit': { ...devices['iPhone 13'], browserName: 'webkit' },
};
if (!Object.hasOwn(browserProfiles, projectName)) {
  throw new Error(`Неизвестный PW_PROJECT: ${projectName}. Доступны: ${Object.keys(browserProfiles).join(', ')}`);
}
const browserProject = {
  name: process.env.PW_PROJECT ? projectName : channel || 'chromium',
  testIgnore: /demo\.spec\.js/,
  use: browserProfiles[projectName],
};

// Запись демонстрации для README (e2e/demo.spec.js) идёт отдельным проектом с видео и большим
// окном. Проект появляется только при DEMO_VIDEO=1, чтобы обычный прогон не писал видео и не
// ждал лишние минуты: DEMO_VIDEO=1 npx playwright test --project demo
const demoProject = {
  name: 'demo',
  testMatch: /demo\.spec\.js/,
  use: {
    ...devices['Desktop Chrome'],
    channel,
    viewport: { width: 1280, height: 800 },
    video: { mode: 'on', size: { width: 1280, height: 800 } },
  },
};

// Без BASE_URL конфиг сам поднимает сервер на 8010 с отдельной базой и собранным фронтом
// (нужен npm run build). С BASE_URL проверки идут против уже запущенного сервера.
export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  reporter: process.env.CI ? [['list'], ['json', { outputFile: 'test-results/report.json' }]] : undefined,
  // проверки входят одним демо-сотрудником, а новый старт прерывает его активное прохождение:
  // параллельные воркеры мешали бы друг другу
  workers: 1,
  use: {
    baseURL,
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    screenshot: process.env.CI ? 'only-on-failure' : 'off',
    trace: process.env.CI ? 'retain-on-failure' : 'off',
  },
  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${defaultPort} --no-proxy-headers`,
        cwd: backend,
        url: `http://127.0.0.1:${defaultPort}/api/health`,
        // Локально можно проверять уже запущенный тестовый сервер; CI должен поднять свой.
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
        env: {
          APP_ENV: 'test',
          DATABASE_URL: process.env.E2E_DATABASE_URL || 'sqlite:///./data/e2e.db',
          FRONTEND_DIST: path.resolve(here, 'dist'),
        },
      },
  projects: [
    browserProject,
    ...(process.env.DEMO_VIDEO ? [demoProject] : []),
  ],
});
