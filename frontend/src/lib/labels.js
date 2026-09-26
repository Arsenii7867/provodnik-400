// Русские подписи к кодам, которые сервер отдаёт как есть: исходы, шаги ролевой модели,
// роли сотрудников, виды уведомлений. Числа и правила здесь не живут, только слова.

export const OUTCOME_TITLES = {
  exemplary: 'Образцово',
  acceptable: 'Приемлемо',
  incident: 'Инцидент',
};

export const ROLE_STEPS = [
  { code: 'acknowledge', title: 'Признать' },
  { code: 'rule', title: 'Правило' },
  { code: 'solution', title: 'Решение' },
  { code: 'assure', title: 'Заверить' },
];

export const ROLE_TITLES = {
  conductor: 'Проводник',
  mentor: 'Наставник',
};

export const NOTIFICATION_KINDS = {
  achievement: 'Достижение',
  level_up: 'Новый уровень',
  challenge: 'Челлендж',
  points_expiring: 'Сгорающие баллы',
  new_scenario: 'Новый сценарий',
};

export function outcomeTitle(code) {
  return OUTCOME_TITLES[code] || code || 'Без исхода';
}

export function roleStepTitle(code) {
  const step = ROLE_STEPS.find((item) => item.code === code);
  return step ? step.title : code;
}

export function formatDateTime(iso) {
  if (!iso) {
    return '';
  }
  return new Date(iso).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function signed(value) {
  if (value > 0) {
    return `+${value}`;
  }
  return String(value);
}

export function plural(count, one, few, many) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return `${count} ${one}`;
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} ${few}`;
  }
  return `${count} ${many}`;
}
