import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  barHeight,
  polarPoint,
  polygonPoints,
  radarPoints,
  wrapLabel,
} from '../src/lib/charts.js';

test('первая ось радара смотрит вверх, остальные идут по часовой стрелке', () => {
  const top = polarPoint(100, 100, 50, 0, 4);
  assert.deepEqual(top, { x: 100, y: 50 });
  const right = polarPoint(100, 100, 50, 1, 4);
  assert.deepEqual(right, { x: 150, y: 100 });
});

test('компетенция без оценки ложится в центр, а число точек равно числу осей', () => {
  const points = radarPoints([1, null, 0.5], 100, 100, 50);
  assert.equal(points.length, 3);
  assert.deepEqual(points[1], { x: 100, y: 100 });
  assert.deepEqual(points[0], { x: 100, y: 50 });
  assert.equal(polygonPoints(points).split(' ').length, 3);
});

test('высота столбца пропорциональна максимуму, пустая неделя даёт ноль', () => {
  assert.equal(barHeight(50, 100, 120), 60);
  assert.equal(barHeight(0, 100, 120), 0);
  assert.equal(barHeight(10, 0, 120), 0);
});

test('подпись переносится по словам и обрезается многоточием', () => {
  assert.deepEqual(wrapLabel('Первая помощь и здоровье', 14, 2), ['Первая помощь', 'и здоровье']);
  assert.deepEqual(wrapLabel('Инклюзивность', 14, 2), ['Инклюзивность']);
  const cut = wrapLabel('Очень длинная подпись из многих слов подряд', 12, 2);
  assert.equal(cut.length, 2);
  assert.ok(cut[1].endsWith('…'));
});
