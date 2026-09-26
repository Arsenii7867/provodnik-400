import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  clockOffset,
  formatSeconds,
  parseServerTime,
  remainingMs,
  remainingSeconds,
  ringOffset,
  scaleDelta,
  timerShare,
} from '../src/lib/timer.js';

const serverNow = '2026-09-26T10:00:00+00:00';
const deadline = '2026-09-26T10:00:20+00:00';

test('смещение часов: сервер впереди клиента на пять секунд', () => {
  const clientNow = Date.parse('2026-09-26T09:59:55Z');
  assert.equal(clockOffset(serverNow, clientNow), 5000);
});

test('остаток считается по часам сервера, а не браузера', () => {
  const clientNow = Date.parse('2026-09-26T09:59:55Z');
  const offset = clockOffset(serverNow, clientNow);
  assert.equal(remainingSeconds(deadline, clientNow, offset), 20);
  assert.equal(remainingSeconds(deadline, clientNow + 7500, offset), 13);
});

test('после дедлайна остаток равен нулю, а не отрицательному числу', () => {
  const clientNow = Date.parse('2026-09-26T10:00:30Z');
  assert.equal(remainingMs(deadline, clientNow, 0), 0);
  assert.equal(remainingSeconds(deadline, clientNow, 0), 0);
});

test('узел без таймера даёт null вместо нуля', () => {
  assert.equal(remainingSeconds(null, Date.now(), 0), null);
});

test('микросекунды сервера не ломают разбор времени', () => {
  const precise = parseServerTime('2026-09-26T10:00:00.123456+00:00');
  assert.equal(precise, Date.parse('2026-09-26T10:00:00.123Z'));
});

test('формат остатка минуты:секунды', () => {
  assert.equal(formatSeconds(0), '0:00');
  assert.equal(formatSeconds(9), '0:09');
  assert.equal(formatSeconds(75), '1:15');
  assert.equal(formatSeconds(-3), '0:00');
});

test('доля кольца таймера ограничена диапазоном 0..1', () => {
  assert.equal(timerShare(10, 20), 0.5);
  assert.equal(timerShare(30, 20), 1);
  assert.equal(timerShare(-1, 20), 0);
  assert.equal(timerShare(5, 0), 0);
});

test('смещение штриха кольца: полный таймер без пропуска, истёкший скрыт целиком', () => {
  assert.equal(ringOffset(20, 20, 300), 0);
  assert.equal(ringOffset(5, 20, 300), 225);
  assert.equal(ringOffset(0, 20, 300), 300);
});

test('часы браузера отстают от сервера: остаток всё равно тает по серверному времени', () => {
  const clientNow = Date.parse('2026-09-26T09:59:00Z');
  const offset = clockOffset(serverNow, clientNow);
  assert.equal(offset, 60000);
  assert.equal(remainingSeconds(deadline, clientNow, offset), 20);
  assert.equal(remainingSeconds(deadline, clientNow + 20000, offset), 0);
});

test('дельта шкалы после хода и отсутствие хода', () => {
  assert.equal(scaleDelta(60, 70), 10);
  assert.equal(scaleDelta(70, 55), -15);
  assert.equal(scaleDelta(null, 70), null);
  assert.equal(scaleDelta(60, undefined), null);
});
