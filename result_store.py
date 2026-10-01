"""One atomic JSON file per attempt; local outbox allows network retries."""
from pathlib import Path
import json
import os
import tempfile
import uuid
import hashlib


def atomic_json(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / ('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class ResultStore:
    def __init__(self, root, outbox=None):
        self.root = Path(root)
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share'))
        self.outbox = Path(outbox) if outbox else base / 'MirPrompt' / 'pending'

    def preflight(self, day):
        folder = self.root / day
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='.write-check-', dir=folder):
            pass

    def claim_participant(self, day, participant, attempt_id):
        def identity(p):
            return (p['first'] + '\n' + p['last']).casefold().replace('ё', 'е')
        key = identity(participant)
        folder = self.root / day
        # Honour completed attempts written by older application versions too.
        for path in folder.glob('*.json'):
            try:
                record = json.loads(path.read_text(encoding='utf-8-sig'))
                if identity(record['participant']) == key:
                    raise ValueError('Участник с такими именем и фамилией уже проходил конкурс сегодня.')
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        registry = folder / '.participants'
        registry.mkdir(exist_ok=True)
        claim = registry / hashlib.sha256(key.encode('utf-8')).hexdigest()
        try:
            claim.mkdir()  # Atomic reservation across all computers on the share.
        except FileExistsError:
            raise ValueError('Участник с такими именем и фамилией уже зарегистрирован сегодня. Обратись к организатору.') from None
        try:
            atomic_json(claim / 'participant.json', {'participant': participant, 'attempt_id': attempt_id})
        except Exception:
            try:
                claim.rmdir()
            except OSError:
                pass
            raise

    def destination(self, record):
        # Validate path parts even when recovering an outbox file.
        from datetime import date
        day = record['event_day']
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('Некорректная дата попытки.')
        attempt = str(uuid.UUID(record['attempt_id']))
        if attempt != record['attempt_id']:
            raise ValueError('Некорректный номер попытки.')
        return self.root / day / (attempt + '.json')

    def save(self, record):
        target = self.destination(record)
        backup = self.outbox / (record['attempt_id'] + '.json')
        local_ok = False
        try:
            atomic_json(backup, {'destination_root': str(self.root.resolve()), 'record': record})
            local_ok = True
        except OSError:
            pass
        try:
            atomic_json(target, record)
        except OSError:
            return {'saved': False, 'local_backup': local_ok,
                    'message': ('Сетевой диск недоступен. Локальная копия сохранена; повтори сохранение.' if local_ok else
                                'Результат пока только в памяти. Не закрывай приложение; повтори сохранение или позови организатора.')}
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        return {'saved': True, 'local_backup': local_ok, 'message': 'Результат сохранён в папке конкурса.'}

    def recover(self):
        saved = pending = 0
        for p in self.outbox.glob('*.json'):
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                if data['destination_root'] != str(self.root.resolve()):
                    continue
                status = self.save(data['record'])
                saved += int(status['saved'])
                pending += int(not status['saved'])
            except (OSError, ValueError, KeyError, TypeError):
                pending += 1
        return {'recovered': saved, 'pending': pending}
