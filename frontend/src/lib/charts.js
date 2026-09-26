// Геометрия графиков без React: радар компетенций, столбцы недель и слои графа сценария.
// Значения приходят из API, здесь только координаты и переносы подписей.

function round(value) {
  return Math.round(value * 10) / 10;
}

function clampShare(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 0;
  }
  return Math.min(1, Math.max(0, value));
}

export function polarPoint(cx, cy, radius, index, count) {
  // первая ось смотрит вверх, дальше по часовой стрелке
  const angle = -Math.PI / 2 + (2 * Math.PI * index) / count;
  return { x: round(cx + radius * Math.cos(angle)), y: round(cy + radius * Math.sin(angle)) };
}

export function polygonPoints(points) {
  return points.map((point) => `${point.x},${point.y}`).join(' ');
}

export function radarPoints(values, cx, cy, radius) {
  // компетенция без оценки (null) рисуется в центре, а не пропускается: осей всегда столько же
  return values.map((value, index) => polarPoint(cx, cy, radius * clampShare(value), index, values.length));
}

export function barHeight(value, max, height) {
  if (!max || !value || value < 0) {
    return 0;
  }
  return Math.round((value / max) * height);
}

export function wrapLabel(text, maxChars, maxLines) {
  const lines = [];
  let current = '';
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= maxChars || !current) {
      current = candidate;
    } else {
      lines.push(current);
      current = word;
    }
  }
  if (current) {
    lines.push(current);
  }
  if (lines.length <= maxLines) {
    return lines;
  }
  const kept = lines.slice(0, maxLines);
  const last = kept[maxLines - 1];
  kept[maxLines - 1] = `${last.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
  return kept;
}
