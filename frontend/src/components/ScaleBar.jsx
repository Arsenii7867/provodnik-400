import { signed } from '../lib/labels.js';

// Шкала 0..100 с дельтой последнего хода: значение и дельту присылает сервер,
// здесь только полоса и подпись.
export default function ScaleBar({ label, value, delta, kind }) {
  return (
    <div className={`scale-bar scale-${kind}`}>
      <div className="scale-head">
        <span className="scale-label">{label}</span>
        <span className="scale-value">{value}</span>
        {delta !== null && delta !== undefined && (
          <span className={`scale-delta ${delta > 0 ? 'delta-up' : delta < 0 ? 'delta-down' : 'delta-zero'}`}>
            {signed(delta)}
          </span>
        )}
      </div>
      <div className="scale-track">
        <div className="scale-fill" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}
