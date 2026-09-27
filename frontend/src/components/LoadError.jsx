// Ручной повтор чтения данных. Ошибки игровых действий сюда не передаются.
export default function LoadError({ resource, label }) {
  if (!resource.error) return null;
  return (
    <div className="load-error">
      <p className="error" role="alert">{resource.error}</p>
      <button
        type="button"
        className="button button-ghost"
        aria-label={`Повторить загрузку: ${label}`}
        disabled={resource.loading}
        onClick={resource.reload}
      >
        {resource.loading ? 'Повторяем…' : 'Повторить'}
      </button>
    </div>
  );
}
