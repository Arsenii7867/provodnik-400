import { barHeight } from '../lib/charts.js';
import { formatDay, plural } from '../lib/labels.js';

const BAR_WIDTH = 36;
const GAP = 16;
const HEIGHT = 120;
const LEFT = 8;
const CAPTIONS = 34;

// Столбцы по неделям: высота это XP за неделю, подпись под столбцом это понедельник недели
// и число прохождений; неделя с инцидентом выделена цветом.
export default function WeeklyBars({ weeks }) {
  const max = weeks.reduce((best, week) => Math.max(best, week.xp), 0);
  const width = LEFT * 2 + weeks.length * (BAR_WIDTH + GAP) - GAP;
  return (
    <svg
      className="weekly"
      viewBox={`0 0 ${width} ${HEIGHT + CAPTIONS}`}
      role="img"
      aria-label="Очки опыта по неделям"
    >
      <line className="weekly-axis" x1="0" y1={HEIGHT + 0.5} x2={width} y2={HEIGHT + 0.5} />
      {weeks.map((week, index) => {
        const height = barHeight(week.xp, max, HEIGHT - 18);
        const x = LEFT + index * (BAR_WIDTH + GAP);
        const middle = x + BAR_WIDTH / 2;
        return (
          <g key={week.week_start} className={week.incidents ? 'week week-incident' : 'week'}>
            <title>
              {`Неделя с ${formatDay(week.week_start)}: ${plural(week.runs, 'прохождение', 'прохождения', 'прохождений')}, ${plural(week.incidents, 'инцидент', 'инцидента', 'инцидентов')}, ${week.xp} XP`}
            </title>
            <rect className="week-bar" x={x} y={HEIGHT - height} width={BAR_WIDTH} height={height} rx="3" />
            {week.xp > 0 && (
              <text className="week-value" x={middle} y={HEIGHT - height - 4} textAnchor="middle">
                {week.xp}
              </text>
            )}
            <text className="week-label" x={middle} y={HEIGHT + 14} textAnchor="middle">
              {formatDay(week.week_start)}
            </text>
            <text className="week-runs" x={middle} y={HEIGHT + 28} textAnchor="middle">
              {week.runs > 0 ? week.runs : ''}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
