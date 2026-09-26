import { edgePath, layerLayout, wrapLabel } from '../lib/charts.js';
import { outcomeTitle } from '../lib/labels.js';

const BOX = { width: 172, height: 66, gapX: 60, gapY: 18 };
const PAD = 14;
const TYPE_TITLES = { dialog: 'диалог', event: 'событие', ending: 'концовка' };

function dominantOutcome(node) {
  // концовка красится по исходу, в который ведёт большинство путей через неё
  const entries = Object.entries(node.outcomes || {});
  if (entries.length === 0) {
    return null;
  }
  entries.sort((left, right) => right[1] - left[1]);
  return entries[0][0];
}

function nodeTitle(node) {
  const parts = [`${TYPE_TITLES[node.type] || node.type} ${node.id}`];
  if (node.timer_seconds) {
    parts.push(`таймер ${node.timer_seconds} с`);
  }
  const outcome = dominantOutcome(node);
  if (outcome) {
    parts.push(`исход чаще всего «${outcomeTitle(outcome)}»`);
  }
  return `${parts.join(', ')}: ${node.label}`;
}

function edgeTitle(edge) {
  if (edge.kind === 'expire') {
    return `истечение таймера: ${edge.from} ведёт в ${edge.to}`;
  }
  if (edge.kind === 'next') {
    return `после события ${edge.from} сценарий идёт в ${edge.to}`;
  }
  return `вариант ${edge.option_id}${edge.conditional ? ' (показывается по условию)' : ''}: ${edge.from} ведёт в ${edge.to}`;
}

// Граф сценария из ответа API: слои по глубине слева направо, узлы по типу, бейдж таймера,
// концовки по преобладающему исходу; пунктир это ветка истечения, точки это условный вариант.
export default function GraphSvg({ nodes, edges }) {
  const layout = layerLayout(nodes, BOX);
  const { positions } = layout;
  const drawable = edges.filter((edge) => positions[edge.from] && positions[edge.to]);
  const width = layout.width + PAD * 2;
  // граф не ужимается меньше своей ширины: подписи узлов остаются читаемыми, карточка прокручивается
  return (
    <svg
      className="graph"
      style={{ minWidth: width }}
      viewBox={`0 0 ${width} ${layout.height + PAD * 2}`}
      role="img"
      aria-label="Граф сценария"
    >
      <defs>
        <marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" />
        </marker>
      </defs>
      <g transform={`translate(${PAD} ${PAD})`}>
        {drawable.map((edge) => (
          <path
            key={`${edge.from}-${edge.to}-${edge.option_id || edge.kind}`}
            className={`graph-edge graph-edge-${edge.kind}${edge.conditional ? ' graph-edge-conditional' : ''}`}
            d={edgePath(positions[edge.from], positions[edge.to], BOX)}
            markerEnd="url(#graph-arrow)"
          >
            <title>{edgeTitle(edge)}</title>
          </path>
        ))}
        {nodes.map((node) => {
          const position = positions[node.id];
          const outcome = dominantOutcome(node);
          const classes = ['graph-node', `graph-node-${node.type}`];
          if (outcome) {
            classes.push(`graph-outcome-${outcome}`);
          }
          return (
            <g key={node.id} className={classes.join(' ')} transform={`translate(${position.x} ${position.y})`}>
              <title>{nodeTitle(node)}</title>
              <rect width={BOX.width} height={BOX.height} rx={node.type === 'event' ? 22 : 8} />
              {node.type === 'ending' && (
                <rect className="graph-node-inner" x="3" y="3" width={BOX.width - 6} height={BOX.height - 6} rx="6" />
              )}
              <text className="graph-node-id" x="12" y="20">
                {node.id}
              </text>
              {wrapLabel(node.label, 27, 2).map((line, index) => (
                <text key={index} className="graph-node-label" x="12" y={38 + index * 14}>
                  {line}
                </text>
              ))}
              {node.timer_seconds && (
                <g className="graph-timer" transform={`translate(${BOX.width - 4} 0)`}>
                  <rect x="-44" y="-10" width="52" height="20" rx="10" />
                  <text x="-18" y="4" textAnchor="middle">
                    {node.timer_seconds} с
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
