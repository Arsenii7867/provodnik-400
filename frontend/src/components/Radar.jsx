import { polarPoint, polygonPoints, radarPoints, wrapLabel } from '../lib/charts.js';

// подписи осей длинные, поэтому поле шире окружности: слева и справа остаётся место под две строки
const WIDTH = 440;
const HEIGHT = 340;
const CENTER_X = WIDTH / 2;
const CENTER_Y = HEIGHT / 2;
const RADIUS = 100;
const LABEL_RADIUS = RADIUS + 28;
const RINGS = [0.25, 0.5, 0.75, 1];

function anchorFor(x) {
  if (x < CENTER_X - 4) {
    return 'end';
  }
  if (x > CENTER_X + 4) {
    return 'start';
  }
  return 'middle';
}

// Радар по компетенциям: осей столько, сколько компетенций прислал сервер; значение это
// владение от 0 до 1, без оценки точка стоит в центре и подписана статусом.
export default function Radar({ items }) {
  const count = items.length;
  const points = radarPoints(
    items.map((item) => item.value),
    CENTER_X,
    CENTER_Y,
    RADIUS,
  );
  return (
    <svg className="radar" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Радар компетенций">
      {RINGS.map((share) => (
        <polygon
          key={share}
          className="radar-ring"
          points={polygonPoints(items.map((_, index) => polarPoint(CENTER_X, CENTER_Y, RADIUS * share, index, count)))}
        />
      ))}
      {items.map((item, index) => {
        const end = polarPoint(CENTER_X, CENTER_Y, RADIUS, index, count);
        const label = polarPoint(CENTER_X, CENTER_Y, LABEL_RADIUS, index, count);
        const lines = wrapLabel(item.title, 14, 2);
        return (
          <g key={item.code} className={`radar-axis radar-${item.status}`}>
            <line x1={CENTER_X} y1={CENTER_Y} x2={end.x} y2={end.y} />
            <text x={label.x} y={label.y - (lines.length - 1) * 6} textAnchor={anchorFor(label.x)}>
              {lines.map((line, lineIndex) => (
                <tspan key={line} x={label.x} dy={lineIndex === 0 ? 0 : 13}>
                  {line}
                </tspan>
              ))}
            </text>
          </g>
        );
      })}
      <polygon className="radar-area" points={polygonPoints(points)} />
      {points.map((point, index) => (
        <circle
          key={items[index].code}
          className={`radar-point radar-${items[index].status}`}
          cx={point.x}
          cy={point.y}
          r="4"
        />
      ))}
    </svg>
  );
}
