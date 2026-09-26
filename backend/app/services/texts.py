"""Русские формы слов и даты словами для текстов уведомлений и выводов аналитики: фразы
собираются в одном месте, чтобы «3 балла» и «5 баллов» не расходились между сервисами."""

MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def plural(count, one, few, many):
    """Число с существительным в нужной форме: 1 балл, 3 балла, 5 баллов, 11 баллов, 21 балл."""
    tail = count % 100
    if 11 <= tail <= 19:
        form = many
    elif tail % 10 == 1:
        form = one
    elif 2 <= tail % 10 <= 4:
        form = few
    else:
        form = many
    return f"{count} {form}"


def date_words(moment):
    return f"{moment.day} {MONTHS[moment.month - 1]} {moment.year}"


def join_titles(titles):
    """Перечисление названий в кавычках через запятую для фраз аналитики."""
    return ", ".join(f"«{title}»" for title in titles)
