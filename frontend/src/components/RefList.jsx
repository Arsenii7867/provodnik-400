import { REF_KINDS } from '../lib/labels.js';

// Ссылки разбора: карточка ситуации показывает реакцию и рекомендованную реплику отдельно,
// чтобы дословная фраза карточки не читалась как пересказ; норма стандарта показывает документ,
// пункт и цитату, а восстановленный номер пункта всегда идёт вместе с текстом.
function RefCard({ item }) {
  return (
    <details className={`ref ref-${item.kind}`}>
      <summary>
        <span className="ref-kind">{REF_KINDS[item.kind] || item.kind}</span>
        <span className="ref-title">{item.title}</span>
        <span className="muted">
          {item.document}, {item.clause}
        </span>
      </summary>
      {item.kind === 'situation' ? (
        <div className="ref-body">
          <p>
            <span className="ref-label">Реакция по карточке</span>
            {item.quote}
          </p>
          {item.phrase && (
            <p>
              <span className="ref-label">Рекомендованная реплика карточки</span>
              {item.phrase}
            </p>
          )}
        </div>
      ) : (
        <div className="ref-body">
          <blockquote>{item.quote}</blockquote>
          {item.reconstructed && (
            <p className="muted">
              Номер пункта восстановлен по оглавлению стандарта, поэтому он всегда показан вместе с цитатой.
            </p>
          )}
        </div>
      )}
    </details>
  );
}

export default function RefList({ refs }) {
  if (!refs || refs.length === 0) {
    return null;
  }
  return (
    <div className="refs">
      {refs.map((item) => (
        <RefCard key={item.key} item={item} />
      ))}
    </div>
  );
}
