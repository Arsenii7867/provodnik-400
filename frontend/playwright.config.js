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

// Без BASE_URL конфиг сам поднимает сервер на 8010 с отдельной базой и собранным фронтом
// (нужен npm run build). С BASE_URL проверки идут против уже запущенного сервера.
export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  // проверки входят одним демо-сотрудником, а новый старт прерывает его активное прохождение:
  // параллельные воркеры мешали бы друг другу
  workers: 1,
  use: { baseURL, locale: 'ru-RU', timezoneId: 'Europe/Moscow' },
  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${defaultPort}`,
        cwd: backend,
        url: `http://127.0.0.1:${defaultPort}/api/health`,
        reuseExistingServer: true,
        timeout: 60_000,
        env: {
          APP_ENV: 'test',
          DATABASE_URL: 'sqlite:///./data/e2e.db',
          FRONTEND_DIST: path.resolve(here, 'dist'),
        },
      },
  projects: [{ name: channel || 'chromium', use: { ...devices['Desktop Chrome'], channel } }],
});
