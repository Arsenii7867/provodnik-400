// Русские подписи к кодам, которые сервер отдаёт как есть: исходы, шаги ролевой модели,
// роли сотрудников, виды уведомлений, вердикты разбора, статусы владения, адресаты эскалации.
// Числа и правила здесь не живут, только слова.

import { parseServerTime } from './timer.js';

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

export const VERDICT_TITLES = {
  best: 'Лучший ход',
  ok: 'По стандарту, но с ценой',
  bad: 'Ошибка',
  expired: 'Таймер истёк',
};

export const COMPETENCY_STATUSES = {
  ok: 'уверенно',
  weak: 'проседает',
  gap: 'пробел',
  few_data: 'мало данных',
};

export const STATUS_EXPLANATIONS = {
  ok: 'владение выше порога по последним прохождениям',
  weak: 'владение ниже порога в двух и более сценариях, где компетенция оценивалась',
  gap: 'ни в одном пройденном сценарии компетенция не оценивалась',
  few_data: 'компетенция оценена пока в одном сценарии, вывод делать рано',
};

export const SCOPES = [
  { code: 'brigade', title: 'Бригада' },
  { code: 'depot', title: 'Депо' },
  { code: 'company', title: 'Компания' },
];

export const CHALLENGE_STATUSES = {
  active: 'идёт',
  completed: 'выполнен',
  expired: 'окно закрыто',
};

export const ESCALATION_TARGETS = {
  chief: 'начальник поезда',
  ptb: 'сотрудники транспортной безопасности (ПТБ)',
  engineer: 'бортинженер',
  police: 'полиция на транспорте (ЛОВД)',
  medics_station: 'медики на станции',
  pa_announcement: 'громкая связь',
  driver: 'машинист',
  station: 'службы вокзала',
};

export const REF_KINDS = {
  situation: 'Карточка ситуации',
  standard: 'Норма стандарта',
  model: 'Ролевая модель',
};

export function outcomeTitle(code) {
  return OUTCOME_TITLES[code] || code || 'Без исхода';
}

export function roleStepTitle(code) {
  const step = ROLE_STEPS.find((item) => item.code === code);
  return step ? step.title : code;
}

export function verdictTitle(code) {
  return VERDICT_TITLES[code] || 'Событие сценария';
}

export function statusTitle(code) {
  return COMPETENCY_STATUSES[code] || code;
}

export function formatDateTime(iso) {
  if (!iso) {
    return '';
  }
  return new Date(parseServerTime(iso)).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatDate(iso) {
  if (!iso) {
    return '';
  }
  // год добавляется отдельно: формат с year даёт «г.» с точкой, которая ломает конец фразы
  const moment = new Date(parseServerTime(iso));
  return `${moment.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })} ${moment.getFullYear()}`;
}

export function formatDay(dateOnly) {
  // недели аналитики приходят датой без времени: собираем её по частям, чтобы часовой пояс
  // не сдвинул понедельник на воскресенье
  const [year, month, day] = String(dateOnly).split('-').map(Number);
  return new Date(year, month - 1, day).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
}

export function percent(share) {
  if (share === null || share === undefined) {
    return '';
  }
  return `${Math.round(share * 100)} %`;
}

export function seconds(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return `${Number(value).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} с`;
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
