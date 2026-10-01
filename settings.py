"""Editable settings beside the EXE, independent of PyInstaller resources."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

SAMARA = timezone(timedelta(hours=4))
DEFAULTS = {'time_limit_seconds': 600, 'score_multiplier': 10,
            'results_directory': 'results', 'event_day': ''}


def application_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def load_settings(root):
    p = Path(root) / 'config.json'
    values = dict(DEFAULTS)
    if p.is_file():
        custom = json.loads(p.read_text(encoding='utf-8-sig'))
        if not isinstance(custom, dict) or set(custom) - set(DEFAULTS):
            raise ValueError('config.json: неизвестные параметры.')
        values.update(custom)
    if type(values['time_limit_seconds']) is not int or not 60 <= values['time_limit_seconds'] <= 3600:
        raise ValueError('time_limit_seconds: целое число от 60 до 3600.')
    if values['score_multiplier'] not in (1, 5, 10) or type(values['score_multiplier']) is not int:
        raise ValueError('score_multiplier: 1, 5 или 10.')
    if not isinstance(values['results_directory'], str) or not values['results_directory'].strip():
        raise ValueError('results_directory: путь к папке результатов.')
    day = values['event_day']
    if not isinstance(day, str):
        raise ValueError('event_day: пустая строка или дата YYYY-MM-DD.')
    if day and (datetime.strptime(day, '%Y-%m-%d').strftime('%Y-%m-%d') != day):
        raise ValueError('event_day: дата YYYY-MM-DD.')
    return values


def event_day(settings):
    return settings['event_day'] or datetime.now(SAMARA).date().isoformat()


def results_dir(root, settings):
    p = Path(settings['results_directory'])
    return p if p.is_absolute() else Path(root) / p
