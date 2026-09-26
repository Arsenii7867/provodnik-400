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

export function layerLayout(nodes, box) {
  // слой это глубина узла от старта; узел без глубины (недостижимый) ставится в последний слой
  const known = nodes.map((node) => (node.depth === null || node.depth === undefined ? -1 : node.depth));
  const maxDepth = known.reduce((best, depth) => Math.max(best, depth), 0);
  const layers = [];
  nodes.forEach((node, index) => {
    const depth = known[index] < 0 ? maxDepth + 1 : known[index];
    while (layers.length <= depth) {
      layers.push([]);
    }
    layers[depth].push(node.id);
  });
  const rows = layers.reduce((best, layer) => Math.max(best, layer.length), 0);
  const stepX = box.width + box.gapX;
  const stepY = box.height + box.gapY;
  const positions = {};
  layers.forEach((layer, depth) => {
    const offset = ((rows - layer.length) * stepY) / 2;
    layer.forEach((id, row) => {
      positions[id] = { x: depth * stepX, y: round(offset + row * stepY) };
    });
  });
  return {
    positions,
    layers: layers.length,
    width: layers.length ? layers.length * stepX - box.gapX : 0,
    height: rows ? rows * stepY - box.gapY : 0,
  };
}

export function edgePath(from, to, box) {
  // вперёд по слоям: плавная кривая из правого края в левый; в тот же слой или назад:
  // дуга через правую сторону, чтобы стрелка не легла на узел
  const startX = from.x + box.width;
  const startY = from.y + box.height / 2;
  const endY = to.y + box.height / 2;
  if (to.x > from.x) {
    const middle = (startX + to.x) / 2;
    return `M${startX},${startY} C${middle},${startY} ${middle},${endY} ${to.x},${endY}`;
  }
  const bend = startX + box.gapX * 0.6;
  const endX = to.x + box.width;
  return `M${startX},${startY} C${bend},${startY} ${bend},${endY} ${endX},${endY}`;
}
