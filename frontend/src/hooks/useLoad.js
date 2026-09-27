import { useCallback, useEffect, useState } from 'react';

// Загрузка данных экрана: запрос при открытии и при смене ключа (путь, строка фильтров),
// перезапрос по reload. Ошибка хранится текстом из ответа сервера, чтобы экран показал её человеку.
// Функция загрузки создаётся экраном на каждом рендере, поэтому эффект привязан к ключу, а не к ней.
export function useLoad(load, key = '') {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => {
    setLoading(true);
    setVersion((current) => current + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError('');
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [key, version]);

  return { data, error, loading, reload, setData };
}
