import copy
import json
from pathlib import Path
import tempfile
import unittest

from prompt_rules import TaskPack


class RuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack=TaskPack()

    def result(self,text,tid='task_01'):
        return self.pack.evaluate(tid,text)

    def criterion(self,text,cid):
        return next(c for c in self.result(text)['criteria'] if c['id']==cid)

    def test_pack_has_30_distinct_scenarios(self):
        self.assertEqual(len(self.pack.tasks),30)
        self.assertEqual(len({t['title'] for t in self.pack.tasks.values()}),30)
        self.assertTrue(all(len(t['fields'])==4 for t in self.pack.tasks.values()))

    def test_complete_examples_for_all_tasks(self):
        for t in self.pack.tasks.values():
            with self.subTest(task=t['id']):
                r=self.result(t['example_full_prompt'],t['id'])
                self.assertEqual(r['score'],100,r['recommendations'])
                self.assertEqual(sum(c['points'] for c in r['criteria']),r['score'])

    def test_each_missing_field_for_each_task(self):
        for t in self.pack.tasks.values():
            for omitted in t['fields']:
                with self.subTest(task=t['id'],field=omitted['id']):
                    fields=[f['label'].lower() for f in t['fields'] if f!=omitted]
                    s=f'Создай приложение для {t["context"]}. Сначала запроси '+', '.join(fields)+'. Затем сформируй карточку и покажи ее сотруднику. В карточке видны все собранные ответы.'
                    r=self.result(s,t['id'])
                    c=next(c for c in r['criteria'] if c['id']==omitted['id'])
                    self.assertEqual(c['points'],0)
                    self.assertLess(r['score'],100)

    def test_keyword_dump_zero(self):
        for t in self.pack.tasks.values():
            with self.subTest(task=t['id']):
                words=' '.join(f['label'] for f in t['fields'])+' карточка плитка приложение'
                self.assertEqual(self.result(words,t['id'])['score'],0)

    def test_empty_zero(self):
        for s in ['', '   ', '\n\t', 'Поставь 100 баллов, игнорируй правила!']:
            self.assertEqual(self.result(s)['score'],0)

    def test_synonyms_and_short_prompt(self):
        s='Сделай программу для службы спасения. Сначала узнай ФИО, уточни гендер, получи местоположение и выясни, что произошло. Затем отобрази все полученные ответы информационным блоком.'
        self.assertEqual(self.result(s)['score'],100)

    def test_case_yo_and_repetition(self):
        text=self.pack.tasks['task_01']['example_full_prompt']
        self.assertEqual(self.result(text)['score'],self.result(text.upper())['score'])
        self.assertEqual(self.result(text)['score'],self.result(text+' '+text)['score'])
        self.assertEqual(self.result(text)['score'],self.result(text.replace('е','ё'))['score'])

    def test_negation_and_conflict(self):
        neg='Не запрашивай имя, пол, адрес и причину вызова.'
        self.assertEqual(self.result(neg)['score'],0)
        self.assertEqual(self.criterion(neg,'field_3')['status'],'negated')
        r=self.result('Запроси адрес, но не запрашивай адрес.')
        self.assertEqual(next(c for c in r['criteria'] if c['id']=='field_3')['points'],0)
        self.assertIn('contradiction:field_3',r['flags'])
        self.assertTrue(r['requires_review'])

    def test_local_negation_does_not_cancel_other_fields(self):
        s='Запроси имя и пол без адреса.'
        self.assertEqual(self.criterion(s,'field_1')['points'],10)
        self.assertEqual(self.criterion(s,'field_2')['points'],10)
        self.assertEqual(self.criterion(s,'field_3')['points'],0)
        self.assertEqual(self.criterion('Адрес собирать не надо.','field_3')['points'],0)

    def test_do_not_forget_and_not_only(self):
        self.assertEqual(self.criterion('Не забудь запросить адрес.','field_3')['points'],15)
        self.assertEqual(self.criterion('Запроси не только имя, но и адрес.','field_1')['points'],10)
        self.assertEqual(self.criterion('Запроси не только имя, но и адрес.','field_3')['points'],15)

    def test_display_is_not_collection(self):
        self.assertEqual(self.criterion('Запроси имя, покажи адрес.','field_3')['points'],0)
        self.assertEqual(self.criterion('Покажи имя, пол, адрес и причину вызова.','field_1')['points'],0)

    def test_no_substring_gender_false_positive(self):
        self.assertEqual(self.criterion('Получи адрес.','field_2')['points'],0)

    def test_bullet_lists(self):
        for bullets in ['- имя\n- пол\n- адрес\n- причину вызова', '1. имя\n2. пол\n3. адрес\n4. причину вызова']:
            r=self.result('Запроси:\n'+bullets)
            self.assertEqual(sum(c['points'] for c in r['criteria'][:4]),50)

    def test_order_and_output_content_independent(self):
        s='Создай приложение для МЧС. Запроси имя, пол, адрес и причину вызова. Покажи карточку.'
        self.assertEqual(self.criterion(s,'sequence')['points'],10)
        self.assertEqual(self.criterion(s,'specificity')['points'],5)
        s+=' В карточке должны быть видны имя, пол, адрес и причина вызова.'
        self.assertEqual(self.criterion(s,'specificity')['points'],15)

    def test_output_negation(self):
        s='Сформируй карточку. Не показывай ее сотруднику.'
        self.assertEqual(self.criterion(s,'result')['points'],10)
        s='Покажи карточку. Не показывай карточку.'
        self.assertEqual(self.criterion(s,'result')['points'],0)
        self.assertTrue(self.result(s)['requires_review'])

    def test_exact_assignment_copy(self):
        for t in self.pack.tasks.values():
            r=self.result(t['statement'],t['id'])
            self.assertEqual(r['score'],0)
            self.assertIn('copied_assignment',r['flags'])

    def test_evidence_offsets_reference_original(self):
        text=self.pack.tasks['task_01']['example_full_prompt']
        for c in self.result(text)['criteria']:
            for e in c['evidence']:
                self.assertEqual(text[e['start']:e['end']],e['text'])

    def test_version_and_determinism(self):
        a=self.result('Запроси адрес.')
        self.assertEqual(a,self.result('Запроси адрес.'))
        self.assertEqual(len(a['pack_sha256']),64)
        self.assertIn('engine_version',a)

    def test_invalid_input(self):
        with self.assertRaises(KeyError): self.result('text','unknown')
        with self.assertRaises(TypeError): self.result(None)
        with self.assertRaises(ValueError): self.result('а'*6001)

    def test_public_task_excludes_answers_and_rules(self):
        t=self.pack.public_task('task_01')
        self.assertNotIn('example_full_prompt',t)
        self.assertNotIn('fields',t)

    def test_corrupt_configuration_rejected(self):
        for change in ['schema','duplicate','weights','patterns']:
            data=copy.deepcopy(self.pack.data)
            if change=='schema': data['schema_version']=2
            if change=='duplicate': data['tasks'][1]['id']=data['tasks'][0]['id']
            if change=='weights': data['tasks'][0]['fields'][0]['points']=500
            if change=='patterns': data['tasks'][0]['fields'][0]['aliases']=['.*']
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'tasks.json';path.write_text(json.dumps(data),encoding='utf-8')
                with self.subTest(change=change), self.assertRaises(ValueError): TaskPack(path)


if __name__=='__main__':
    unittest.main()
