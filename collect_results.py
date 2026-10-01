"""Run in the application folder after the competition. Python 3.11–3.13."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys
import uuid
import re

from ranking_excel import write_xlsx
from settings import load_settings, results_dir, event_day


def validate_record(r, day):
    if r['schema_version'] != 1 or r['event_day'] != day:
        raise ValueError('Версия или день попытки не совпадает.')
    if str(uuid.UUID(r['attempt_id'])) != r['attempt_id']:
        raise ValueError('Некорректный номер попытки.')
    for name in ('first', 'last'):
        value = r['participant'][name]
        if not isinstance(value, str) or not 1 <= len(value) <= 50 or not re.fullmatch(r'[А-Яа-яЁё]+(?:[- ][А-Яа-яЁё]+)*', value):
            raise ValueError('Некорректное имя участника.')
    e = r['evaluation']
    score, maximum, duration = e['score'], e['max_score'], r['duration_ms']
    if type(score) is not int or type(maximum) is not int or not 0 <= score <= maximum:
        raise ValueError('Некорректные баллы.')
    if type(duration) is not int or type(r['time_limit_seconds']) is not int or not 0 <= duration <= r['time_limit_seconds'] * 1000:
        raise ValueError('Некорректное время.')
    requirements = sum(c['points'] for c in e['criteria'])
    base_maximum = sum(c['max_points'] for c in e['criteria'])
    rule = e.get('scoring_rule', 'scaled_v1')
    if rule in ('scaled_plus_full_minutes_v1', 'scaled_plus_remaining_minutes_v1'):
        bonus = (duration if rule == 'scaled_plus_full_minutes_v1' else max(0, r['time_limit_seconds'] * 1000 - duration)) // 60000
        if e.get('minute_bonus') != bonus or e.get('requirements_score') != requirements or e.get('requirements_max_score') != base_maximum or score != requirements + bonus or maximum != base_maximum + r['time_limit_seconds'] // 60:
            raise ValueError('Итог или бонус за минуты не совпадает с формулой.')
    elif rule == 'scaled_v1':
        if score != requirements or maximum != base_maximum:
            raise ValueError('Итог старой шкалы не совпадает с критериями.')
    else:
        raise ValueError('Неизвестная формула баллов.')
    if len(e['criteria']) != 7 or base_maximum not in (100, 500, 1000):
        raise ValueError('Сумма критериев не совпадает с итогом.')
    for c in e['criteria']:
        if type(c['points']) is not int or type(c['max_points']) is not int or not 0 <= c['points'] <= c['max_points']:
            raise ValueError('Некорректный критерий.')
    if r['task_id'] != e['task_id']:
        raise ValueError('Задание не совпадает.')
    # Required report fields must be present before writing the workbook.
    for key in ('completed_at', 'computer', 'auto_submitted'):
        if key not in r:
            raise ValueError('Отсутствует ' + key)
    for key in ('task_title', 'requires_review', 'engine_version', 'pack_sha256'):
        if key not in e:
            raise ValueError('Отсутствует ' + key)


def read_results(folder, day):
    records = {}; errors = []; duplicates = 0; conflicted = set()
    for p in sorted(Path(folder).glob('*.json')):
        try:
            r = json.loads(p.read_text(encoding='utf-8-sig'))
            validate_record(r, day)
            uid = r['attempt_id']
            if uid in records:
                if records[uid] == r:
                    duplicates += 1
                else:
                    conflicted.add(uid)
                    errors.append([p.name, 'Два разных результата с одним номером попытки. Оба исключены.'])
            else:
                records[uid] = r
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append([p.name, str(exc)])
    for uid in conflicted:
        records.pop(uid, None)
    result = sorted(records.values(), key=lambda r: (-r['evaluation']['score'], r['duration_ms'],
                                                    r['participant']['last'], r['participant']['first'], r['attempt_id']))
    if len({r['evaluation'].get('scoring_rule', 'scaled_v1') for r in result}) > 1 or len({r['evaluation']['max_score'] for r in result}) > 1 or len({r['time_limit_seconds'] for r in result}) > 1 or len({r['evaluation']['pack_sha256'] for r in result}) > 1 or len({r['evaluation']['engine_version'] for r in result}) > 1:
        raise ValueError('В этот день смешаны разные шкалы, лимиты или версии заданий. Согласуйте условия перед определением мест.')
    last_key = None; rank = 0
    for i, r in enumerate(result, 1):
        key = (r['evaluation']['score'], r['duration_ms'])
        if key != last_key:
            rank = i
        r['rank'] = rank; last_key = key
    return result, errors, duplicates


def duration(ms):
    return f'{ms // 60000:02}:{ms // 1000 % 60:02}.{ms % 1000:03}'


def collect(root, day):
    config = load_settings(root)
    folder = results_dir(root, config) / day
    rows, errors, duplicates = read_results(folder, day)
    if not rows:
        raise ValueError(f'Нет корректных результатов за {day}. Папка: {folder}. Ошибочных файлов: {len(errors)}.')
    main = [['Место', 'Имя', 'Фамилия', 'Баллы', 'Максимум', 'Время', 'Задание', 'Нужна проверка', 'Автоотправка', 'Завершено', 'Компьютер', 'Номер попытки', 'За требования', 'Бонус за минуты (см. формулу)']]
    detail = [['Номер попытки', 'Имя', 'Фамилия', 'Критерий', 'Баллы', 'Максимум']]
    for r in rows:
        e = r['evaluation']; p = r['participant']
        main.append([r['rank'], p['first'], p['last'], e['score'], e['max_score'], duration(r['duration_ms']),
                     e['task_title'], 'Да' if e['requires_review'] else 'Нет', 'Да' if r['auto_submitted'] else 'Нет',
                     r['completed_at'], r['computer'], r['attempt_id'], e.get('requirements_score', e['score']), e.get('minute_bonus', 0)])
        for c in e['criteria']:
            detail.append([r['attempt_id'], p['first'], p['last'], c['title'], c['points'], c['max_points']])
    info = [['Параметр', 'Значение'], ['День конкурса', day], ['Попыток', len(rows)], ['Дубликатов пропущено', duplicates],
            ['Ошибочных файлов', len(errors)], ['Порядок мест', 'Баллы по убыванию, затем длительность в миллисекундах по возрастанию. Полное равенство — общее место (1, 2, 2, 4).'],
            ['Важно', 'Одна строка — одна попытка. Повторные попытки одного человека не объединяются по имени. Строки «Нужна проверка» проверьте до выдачи призов.'],
            ['Время', 'От выдачи задания до отправки. Передача файла по сети во время не входит. Даты: Самара, UTC+4.'],
            ['Формула записей', rows[0]['evaluation'].get('scoring_rule', 'scaled_v1')],
            ['Новая формула', 'Баллы за требования × множитель + оставшиеся полные минуты. При лимите 10 минут: 5:00 прохождения дают +5, 5:01 дают +4; по истечении времени +0. Максимум 1010.'],
            ['Старые формулы', 'scaled_plus_full_minutes_v1 — бонус за потраченные минуты; scaled_v1 — без бонуса. Разные формулы в одном конкурсе не смешиваются.']]
    sheets = [('Места', main, [9, 21, 26, 12, 12, 18, 46, 18, 18, 34, 24, 40, 18, 20]),
              ('Критерии', detail, [40, 21, 26, 52, 12, 12]), ('О конкурсе', info, [28, 95])]
    if errors:
        sheets.append(('Ошибки', [['Файл', 'Причина']] + errors, [45, 95]))
    target = folder / ('Итоги_' + day + '.xlsx')
    write_xlsx(target, sheets)
    return target, len(rows), errors, duplicates


def main():
    parser = argparse.ArgumentParser(description='Собрать результаты «МИР • Промпт» в Excel')
    parser.add_argument('--day', help='Дата конкурса YYYY-MM-DD')
    parser.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    config = load_settings(root); day = args.day or event_day(config)
    if args.interactive and not args.day:
        folders = results_dir(root, config)
        available = sorted(p.name for p in folders.glob('????-??-??') if p.is_dir())
        print('Дни с результатами: ' + (', '.join(available) or 'пока нет'))
        day = input(f'Дата конкурса [{day}], Enter — выбрать её: ').strip() or day
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError('Дата должна быть YYYY-MM-DD.')
    target, count, errors, duplicates = collect(root, day)
    print(f'Готово: {count} попыток. Дубликатов пропущено: {duplicates}.')
    print(f'Excel: {target}')
    if errors:
        print(f'ВНИМАНИЕ: исключено файлов: {len(errors)}. Проверьте лист «Ошибки» до объявления победителей.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print('ОШИБКА: ' + str(exc), file=sys.stderr)
        print('Если Excel открыт, закройте его и повторите сборку. Проверьте дату и доступ к папке.', file=sys.stderr)
        raise SystemExit(1)
