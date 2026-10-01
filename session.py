"""In-memory participant lifecycle. No UI dependencies, network or database."""
from __future__ import annotations

import copy
import re
import secrets
import time
import uuid
import socket
from datetime import datetime

from settings import SAMARA

from prompt_rules import TaskPack


def normalize_name(value: str, label: str = 'Имя') -> str:
    if not isinstance(value, str):
        raise ValueError(f'{label}: ожидается текст.')
    value = value.strip()
    if not 1 <= len(value) <= 50:
        raise ValueError(f'{label}: нужно от 1 до 50 символов.')
    if not re.fullmatch(r'[А-Яа-яЁё]+(?:[- ][А-Яа-яЁё]+)*', value):
        raise ValueError(f'{label}: используй русские буквы. Между частями допустим пробел или дефис; цифры и латиница не подходят.')
    return ' '.join('-'.join(part.capitalize() for part in word.split('-'))
                    for word in value.split(' '))


class ParticipantSession:
    def __init__(self, pack: TaskPack, chooser=None, *, store=None, limit_seconds=600,
                 multiplier=1, day_provider=None, clock=None):
        self.pack = pack
        self.choose = chooser or secrets.choice
        self.participant = None
        self.task_id = None
        self.result = None
        self.store = store
        self.limit_seconds = limit_seconds
        self.multiplier = multiplier
        self.day_provider = day_provider or (lambda: datetime.now(SAMARA).date().isoformat())
        self.clock = clock or time.monotonic
        self.record = None
        self.storage = None
        self.started_clock = None

    def start(self, first: str, last: str) -> dict:
        if self.participant is not None:
            raise ValueError('Испытание уже начато. Заверши его перед следующим участником.')
        participant = {'first': normalize_name(first, 'Имя'),
                       'last': normalize_name(last, 'Фамилия')}
        day = self.day_provider()
        if self.store:
            try:
                self.store.preflight(day)
            except OSError:
                raise ValueError('Нет доступа к папке результатов. Проверь сетевой диск и разрешение записи с организатором.') from None
        task_id = self.choose(tuple(self.pack.tasks))
        task = self.pack.public_task(task_id)
        attempt_id = str(uuid.uuid4())
        if self.store:
            try:
                self.store.claim_participant(day, participant, attempt_id)
            except OSError:
                raise ValueError('Не удалось проверить регистрацию на сетевом диске. Обратись к организатору.') from None
        self.participant, self.task_id = participant, task_id
        self.day = day
        self.attempt_id = attempt_id
        self.started_at = datetime.now(SAMARA).isoformat(timespec='milliseconds')
        self.started_clock = self.clock()
        return {'participant': dict(participant), 'task': task,
                'limit_seconds': self.limit_seconds, 'remaining_ms': self.limit_seconds * 1000,
                'max_score': 100 * self.multiplier + self.limit_seconds // 60, 'attempt_id': self.attempt_id}

    def status(self):
        elapsed = 0 if self.started_clock is None else max(0, self.clock() - self.started_clock)
        return {'remaining_ms': max(0, int((self.limit_seconds - elapsed) * 1000)),
                'active': self.participant is not None and self.result is None}

    def evaluate(self, prompt: str) -> dict:
        if self.participant is None:
            raise ValueError('Сначала введи имя и фамилию.')
        if self.result is not None:
            # Repeated button presses/callback retries cannot change the fixed result.
            return copy.deepcopy(self.result)
        elapsed_ms = max(0, int((self.clock() - self.started_clock) * 1000))
        expired = elapsed_ms >= self.limit_seconds * 1000
        if not isinstance(prompt, str) or (not prompt.strip() and not expired):
            raise ValueError('Напиши непустой промпт.')
        self.result = self.pack.evaluate(self.task_id, prompt)
        self.result['base_score'] = self.result['score']
        self.result['score'] *= self.multiplier
        self.result['max_score'] *= self.multiplier
        duration_ms = min(elapsed_ms, self.limit_seconds * 1000)
        self.result['scoring_rule'] = 'scaled_plus_remaining_minutes_v1'
        self.result['requirements_score'] = self.result['score']
        self.result['requirements_max_score'] = self.result['max_score']
        self.result['minute_bonus'] = max(0, self.limit_seconds * 1000 - duration_ms) // 60000
        self.result['score'] += self.result['minute_bonus']
        self.result['max_score'] += self.limit_seconds // 60
        for criterion in self.result['criteria']:
            criterion['points'] *= self.multiplier
            criterion['max_points'] *= self.multiplier
            if self.multiplier != 1:
                criterion['explanation'] += f' Числа в пояснении указаны для базовой шкалы 100; на экране они умножены на {self.multiplier}.'
        self.record = {'schema_version': 1, 'attempt_id': self.attempt_id, 'event_day': self.day,
                       'participant': dict(self.participant), 'task_id': self.task_id,
                       'started_at': self.started_at, 'completed_at': datetime.now(SAMARA).isoformat(timespec='milliseconds'),
                       'duration_ms': duration_ms,
                       'time_limit_seconds': self.limit_seconds, 'auto_submitted': expired,
                       'computer': socket.gethostname(), 'prompt': prompt,
                       'evaluation': copy.deepcopy(self.result)}
        self.retry_save()
        return copy.deepcopy(self.result)

    def retry_save(self):
        if self.record is None:
            raise ValueError('Нет результата для сохранения.')
        self.storage = self.store.save(self.record) if self.store else {'saved': True, 'message': 'Проверка без записи.'}
        self.result['storage'] = dict(self.storage)
        self.result['duration_ms'] = self.record['duration_ms']
        self.result['auto_submitted'] = self.record['auto_submitted']
        return dict(self.storage)

    def finish(self) -> dict:
        if self.store and (not self.result or not self.storage or not self.storage['saved']):
            raise ValueError('Сначала сохрани результат в папку конкурса.')
        self.participant = self.task_id = self.result = None
        self.record = self.storage = self.started_clock = None
        return {}
