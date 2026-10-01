"""Versioned, offline rubric matching for PROMPT LAB. Python 3.10+, stdlib only.

No models, network, database or application UI. This is a rule-based requirement
check, not a general language-understanding system. See README.md for limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re
import unicodedata

ENGINE_VERSION = '1.0.0'


def normalize(text: str) -> str:
    return unicodedata.normalize('NFKC', text).lower().replace('ё', 'е')


@dataclass(frozen=True)
class Token:
    word: str
    start: int
    end: int


@dataclass(frozen=True)
class Clause:
    text: str
    start: int
    tokens: tuple[Token, ...]


def clauses(text: str) -> list[Clause]:
    out = []
    # Commas and colons preserve shared lists. Adversative conjunctions split scopes.
    scan = re.sub(r'(?m)^(\s*\d+)\.', lambda m: m.group()[:-1]+' ', text)
    for match in re.finditer(r'[^.!?;\n]+', scan):
        for part in re.finditer(r'(?:^|\b(?:но(?!\s+и\b)|однако)\b)(.*?)(?=\b(?:но(?!\s+и\b)|однако)\b|$)', match.group()):
            raw = text[match.start()+part.start(1):match.start()+part.end(1)]
            tokens = tuple(Token(normalize(t.group()), t.start(), t.end())
                           for t in re.finditer(r'[\w]+', raw, re.UNICODE))
            if tokens:
                out.append(Clause(raw, match.start() + part.start(1), tokens))
    return out


def word_matches(word: str, rule: str) -> bool:
    rule = normalize(rule)
    return word.startswith(rule[:-1]) if rule.endswith('*') else word == rule


def find_aliases(words: list[str], aliases: list[str]):
    """Literal token phrases, optionally with suffix '*'. No arbitrary regex."""
    seen = set()
    for alias in aliases:
        parts = normalize(alias).split()
        for i in range(len(words) - len(parts) + 1):
            if all(word_matches(words[i+j], p) for j, p in enumerate(parts)):
                pair = (i, i+len(parts))
                if pair not in seen:
                    seen.add(pair)
                    yield pair


COLLECT = ['запрос*','запраш*','выясн*','спрос*','уточн*','получ*','собер*','собира*','собрать',
           'узна*','ввод*','ввест*','введ*','заполн*','впис*','впиш*','вводить']
DISPLAY = ['покаж*','показ*','вывед*','вывод*','отобраз*','отображ*','видн*','вывести']
CREATE = ['созда*','создай','сдела*','сформир*','формир*','сформиров*']
CARD = ['карточк*','плитк*','информационн* блок*','информационн* панел*','блок результат*']
APP = ['приложен*','программ*','систем*','сервис*','интерфейс*']
COLLECTIVE = ['все ответ*','все собранн* ответ*','все полученн* ответ*',
              'собранн* данн*','введенн* данн*','полученн* данн*','все данн*',
              'все четыр* значен*','все четыр* пол*','ответ* пользовател*']


def actions(words):
    result = []
    for i, word in enumerate(words):
        # Do not treat nouns/adjectives such as 'получатель'/'получения'
        # as verbs. Otherwise a list of field labels could receive points.
        if word.startswith(('получател','полученн','введенн','заполненн')) or word.endswith(('ение','ения','ению','ении','ением','ений','ениями','ениях')):
            continue
        kind = next((k for k, rules in [('collect', COLLECT), ('display', DISPLAY),
                                      ('create', CREATE)]
                     if any(word_matches(word, r) for r in rules)), None)
        if kind:
            result.append((i, kind))
    return result


def negative(words, start, end):
    for i in range(max(0, start), min(end, len(words))):
        w = words[i]
        if w == 'не' and i+1 < len(words) and words[i+1] in ('только','забудь','забывай'):
            continue
        if w in ('не','без','нельзя','запрещено','запрещается'):
            return True
    return False


def nearby_action(words, a, first, last):
    """Use the last preceding action, or a close postposed action."""
    before = [(i, kind) for i, kind in a if i <= first and first-i <= 28]
    if before:
        return before[-1]
    after = [(i, kind) for i, kind in a if i >= last and i-last <= 5]
    return after[0] if after else None


def fragment(clause, first, last):
    tokens = clause.tokens
    start, end = tokens[first].start, tokens[last-1].end
    return {'text': clause.text[start:end], 'start': clause.start+start, 'end': clause.start+end}


def field_matches(cs, field):
    positive, rejected = [], []
    inherited = None
    previous_end = -1
    for c in cs:
        words = [t.word for t in c.tokens]
        a = actions(words)
        # A collection heading may introduce a bullet list on the following lines.
        # Do not carry across ordinary sentences or unrelated prose.
        if c.start - previous_end > 3:
            inherited = None
        for first, last in find_aliases(words, field['aliases']):
            act = nearby_action(words, a, first, last)
            if act is None and inherited and re.match(r'^\s*[-•\d.)]+', c.text):
                is_negative = inherited == 'negative' or negative(words, 0, last)
                evidence = fragment(c, first, last)
                (rejected if is_negative else positive).append(evidence)
            elif act and act[1] == 'collect':
                idx = act[0]
                is_negative = negative(words, idx-4, idx+1) or negative(words, first-2, first)
                # "адрес собирать не нужно" is also an explicit negative.
                if idx >= last:
                    is_negative |= negative(words, idx+1, min(len(words), idx+4))
                evidence = fragment(c, min(idx,first), max(idx+1,last))
                (rejected if is_negative else positive).append(evidence)
        if c.text.rstrip().endswith(':') and a and a[-1][1] == 'collect':
            inherited = 'negative' if negative(words, a[-1][0]-4, a[-1][0]+1) else 'positive'
        elif not re.match(r'^\s*[-•\d.)]+', c.text):
            inherited = None
        previous_end = c.start + len(c.text)
    return positive[:2], rejected[:2]


def result_matches(cs):
    card_pos, show_pos, card_neg, show_neg, content_pos = [], [], [], [], []
    last_card_end = -1000
    for c in cs:
        words = [t.word for t in c.tokens]
        a = actions(words)
        nouns = list(find_aliases(words, CARD))
        affirmed_card_here = False
        for first, last in nouns:
            act = nearby_action(words, a, first, last)
            if act and act[1] in ('create','display'):
                idx = act[0]
                neg = negative(words, idx-4, idx+1) or negative(words, first-2, first)
                ev = fragment(c, min(idx,first), max(idx+1,last))
                (card_neg if neg else card_pos).append(ev)
                if act[1] == 'display':
                    (show_neg if neg else show_pos).append(ev)
                if not neg:
                    affirmed_card_here = True
                    last_card_end = c.start+c.tokens[last-1].end
            # "В карточке видны ..." is a postposed output action.
            elif not negative(words, first-2, first):
                after = [(i,k) for i,k in a if i >= last and i-last <= 6 and k=='display']
                if after:
                    idx=after[0][0]
                    neg=negative(words, idx-3, idx+1)
                    ev=fragment(c, first, idx+1)
                    (card_neg if neg else card_pos).append(ev)
                    (show_neg if neg else show_pos).append(ev)
                    if not neg:
                        affirmed_card_here=True; last_card_end=c.start+c.tokens[last-1].end
        # Pronouns can refer only to a recently mentioned positive card.
        for idx, kind in a:
            if kind == 'display' and c.start+c.tokens[idx].start-last_card_end <= 220:
                if any(w in ('ее','его','их','результат') for w in words[idx+1:idx+5]):
                    ev=fragment(c, idx, min(len(words),idx+5))
                    (show_neg if negative(words,idx-4,idx+1) else show_pos).append(ev)
        if nouns or (card_pos and c.start-last_card_end <= 220):
            for first,last in find_aliases(words,COLLECTIVE):
                if not negative(words, first-4, first):
                    content_pos.append(fragment(c,first,last))
        # Keep lookback limited even with long prose.
    return card_pos[:2], show_pos[:2], card_neg[:2], show_neg[:2], content_pos[:2]


class TaskPack:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Path(__file__).with_name('tasks.json')
        raw = self.path.read_bytes()
        self.fingerprint = hashlib.sha256(raw).hexdigest()
        self.data = json.loads(raw.decode('utf-8-sig'))
        self._validate()
        self.tasks = {t['id']:t for t in self.data['tasks']}

    def _validate(self):
        p=self.data
        if p.get('schema_version') != 1 or not isinstance(p.get('tasks'),list) or not p['tasks']:
            raise ValueError('Неизвестная схема или пустой набор заданий')
        if p.get('scoring') != {'fields_total':50,'result':20,'sequence':15,'specificity':15}:
            raise ValueError('Эта версия алгоритма поддерживает шкалу 50+20+15+15')
        if type(p.get('max_prompt_chars')) is not int or not 1 <= p['max_prompt_chars'] <= 20000:
            raise ValueError('Некорректный лимит длины')
        ids=set()
        for t in p['tasks']:
            if not isinstance(t.get('id'),str) or t['id'] in ids:
                raise ValueError('Некорректный или повторяющийся ID задания')
            ids.add(t['id'])
            for key in ('title','statement','context','output_label'):
                if not isinstance(t.get(key),str) or not t[key].strip():
                    raise ValueError(f'Отсутствует {key}: {t["id"]}')
            fs=t.get('fields',[])
            if len(fs)!=4 or [f.get('points') for f in fs]!=[10,10,15,15]:
                raise ValueError('Нужно четыре поля с весами 10,10,15,15')
            if len({f.get('id') for f in fs})!=4:
                raise ValueError('Повторяющиеся поля')
            for aliases in [t.get('goal_aliases'), *(f.get('aliases') for f in fs)]:
                if not isinstance(aliases,list) or not aliases:
                    raise ValueError('Отсутствуют словари соответствий')
                for alias in aliases:
                    if not isinstance(alias,str) or not re.fullmatch(r'[\w* ]+',alias) or any('*' in token[:-1] or token=='*' for token in alias.split()):
                        raise ValueError('Допустимы только слова и префиксы со звёздочкой в конце')

    def list_tasks(self):
        """Public task payload: no internal rules or full-score examples."""
        return [self.public_task(tid) for tid in self.tasks]

    def public_task(self, task_id):
        t=self.tasks[task_id]
        public = {k:t[k] for k in ('id','title','statement','requirements','recommended_minutes','difficulty')}
        public['rubric'] = [{'id':f['id'],'title':f['label'],'max_points':f['points']} for f in t['fields']] + [
            {'id':'result','title':'Формирование и показ карточки','max_points':20},
            {'id':'sequence','title':'Порядок работы','max_points':15},
            {'id':'specificity','title':'Назначение и содержимое результата','max_points':15}]
        return public

    def evaluate(self, task_id: str, prompt: str) -> dict:
        if task_id not in self.tasks:
            raise KeyError(f'Неизвестное задание: {task_id}')
        if not isinstance(prompt,str):
            raise TypeError('Промпт должен быть строкой')
        if len(prompt)>self.data['max_prompt_chars']:
            raise ValueError(f'Максимум {self.data["max_prompt_chars"]} символов')
        t=self.tasks[task_id]; cs=clauses(prompt)
        entries=[]; flags=[]; recommendations=[]
        def add(cid,title,points,maximum,status,explanation,evidence=()):
            entries.append({'id':cid,'title':title,'points':points,'max_points':maximum,
                            'status':status,'explanation':explanation,'evidence':list(evidence)})
        copied=normalize(prompt).strip()==normalize(t['statement']).strip()
        valid_fields=0
        collection_evidence=[]
        for f in t['fields']:
            pos,neg=field_matches(cs,f)
            conflict=bool(pos and neg)
            pts=f['points'] if pos and not neg and not copied else 0
            if pts: valid_fields+=1; collection_evidence.extend(pos)
            status='met' if pts else 'contradiction' if conflict else 'negated' if neg else 'missing'
            why=('Есть требование получить эти сведения.' if pts else
                 'Есть и требование сбора, и его отрицание. Нужна проверка организатором.' if conflict else
                 'Сбор этих сведений явно отрицается.' if neg else
                 'Не найдено действие сбора рядом с названием поля. Словарь мог не распознать формулировку.')
            add(f['id'],f['label'],pts,f['points'],status,why,pos+neg)
            if conflict: flags.append('contradiction:'+f['id'])
            if not pts: recommendations.append('Явно опиши действие: запросить '+f['label'].lower()+'.')
        card,show,ncard,nshow,contents=result_matches(cs)
        card_ok=bool(card and not ncard and not copied)
        show_ok=bool(show and not nshow and not ncard and not copied)
        rpoints=10*card_ok+10*show_ok
        if (card and ncard) or (show and nshow): flags.append('contradiction:result')
        add('result','Формирование и показ карточки',rpoints,20,
            'met' if rpoints==20 else 'partial' if rpoints else 'missing',
            '10 баллов за создание карточки/плитки; 10 за её показ сотруднику.',card+show+ncard+nshow)
        if not card_ok: recommendations.append('Укажи, что приложение формирует карточку или плитку.')
        if not show_ok: recommendations.append('Укажи, что карточка отображается сотруднику.')
        sequence_ev=[]
        if collection_evidence and show_ok:
            collect_start=min(e['start'] for e in collection_evidence)
            output_end=max(e['end'] for e in show)
            if collect_start<output_end:
                n=normalize(prompt)
                # Explicit ordering only, rather than judging paragraphs or word count.
                for m in re.finditer(r'\b(сначала|затем|потом|после|далее)\b',n):
                    if m.group() in ('затем','потом','далее') and collect_start<m.start()<output_end:
                        sequence_ev.append({'text':prompt[m.start():m.end()],'start':m.start(),'end':m.end()})
                    elif m.group()=='после' and collect_start<=m.start()<output_end and re.search(r'(получ|сбор|ввод|заполн|ответ)',n[m.end():m.end()+70]):
                        sequence_ev.append({'text':prompt[m.start():m.end()],'start':m.start(),'end':m.end()})
        spoints=0 if copied else (5 if valid_fields else 0)+(5 if show_ok else 0)+(5 if sequence_ev else 0)
        add('sequence','Порядок работы',spoints,15,'met' if spoints==15 else 'partial' if spoints else 'missing',
            '5 за сбор сведений; 5 за показ результата; 5 за явный переход от сбора к показу.',sequence_ev)
        if not sequence_ev: recommendations.append('Обозначь порядок: сначала собрать сведения, затем показать карточку.')
        goal_ev=[]
        for c in cs:
            words=[x.word for x in c.tokens]
            if list(find_aliases(words,APP)) and any(k=='create' and not negative(words,i-4,i+1) for i,k in actions(words)):
                for first,last in find_aliases(words,t['goal_aliases']):
                    if not negative(words,first-3,first): goal_ev.append(fragment(c,first,last))
        # Explicit fields in the output sentence are an alternative to "all collected answers".
        explicit_content=False
        for c in cs:
            words=[x.word for x in c.tokens]
            if list(find_aliases(words,CARD)) and not negative(words,0,len(words)):
                if all(list(find_aliases(words,f['aliases'])) for f in t['fields']):
                    explicit_content=True
        content_ok=(bool(contents) or explicit_content) and card_ok and show_ok
        qpoints=0 if copied else (5 if goal_ev else 0)+(10 if content_ok else 0)
        add('specificity','Назначение и содержимое результата',qpoints,15,
            'met' if qpoints==15 else 'partial' if qpoints else 'missing',
            '5 за создание приложения для указанной службы; 10 за явное включение всех собранных ответов в карточку.',goal_ev[:1]+contents[:1])
        if not goal_ev: recommendations.append('Укажи, для какой службы или организации нужно создать приложение.')
        if not content_ok: recommendations.append('Уточни: в карточке должны быть видны все собранные ответы.')
        if copied: flags.append('copied_assignment'); recommendations.insert(0,'Составь собственную инструкцию вместо копирования условия целиком.')
        total=sum(e['points'] for e in entries)
        return {'task_id':task_id,'task_title':t['title'],'score':total,'max_score':100,
                'criteria':entries,'recommendations':recommendations,'flags':flags,
                'requires_review':bool(flags),'evaluation_kind':'rule_based_requirements',
                'engine_version':ENGINE_VERSION,'pack_version':self.data['pack_version'],
                'pack_sha256':self.fingerprint,
                'notice':'Оценка выполнения требований по правилам. Не является полной смысловой оценкой промпта.'}


def evaluate(task_id: str, prompt: str, tasks_path: str | Path | None = None) -> dict:
    """Convenience function; reuse TaskPack for repeated evaluations."""
    return TaskPack(tasks_path).evaluate(task_id,prompt)
