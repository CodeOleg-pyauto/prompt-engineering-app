import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET

from collect_results import collect, read_results
from prompt_rules import TaskPack
from result_store import ResultStore, atomic_json
from session import ParticipantSession
from settings import load_settings, results_dir


class CompetitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ResultStore(self.root / 'results', self.root / 'outbox')
        self.pack = TaskPack()
        self.now = 0

    def tearDown(self):
        self.temp.cleanup()

    def session(self):
        s = ParticipantSession(self.pack, lambda ids: ids[0], store=self.store,
                               multiplier=10, clock=lambda: self.now, day_provider=lambda: '2026-10-01')
        s.start('Иван', 'Иванов' + 'а' * getattr(self,'sequence',0))
        self.sequence = getattr(self,'sequence',0) + 1
        return s

    def test_timer_scaling_and_empty_auto_submission(self):
        s = self.session(); self.now = 12.345
        self.assertEqual(s.status()['remaining_ms'],587655)
        r = s.evaluate(self.pack.tasks['task_01']['example_full_prompt'])
        self.assertEqual(r['score'],1009);self.assertEqual(r['max_score'],1010)
        self.assertEqual(sum(c['points'] for c in r['criteria']),1000)
        self.assertEqual(r['duration_ms'],12345);self.assertTrue(r['storage']['saved'])
        s.finish();self.assertEqual(len(list((self.root/'results'/'2026-10-01').glob('*.json'))),1)
        s = self.session();self.now += 602
        r = s.evaluate('');self.assertTrue(r['auto_submitted']);self.assertEqual(r['duration_ms'],600000);self.assertEqual(r['score'],0)
        self.assertEqual(s.evaluate('Исправленный текст')['score'],0)

    def test_full_minute_bonus_boundaries_and_example(self):
        for elapsed, bonus in [(0,10),(59.999,9),(60,9),(299.999,5),(300,5),(300.001,4),(359.999,4),(600,0),(900,0)]:
            with self.subTest(elapsed=elapsed):
                self.now=0;s=self.session();self.now=elapsed
                original=self.pack.evaluate(s.task_id,'Привет')
                original['score']=46
                for c, points in zip(original['criteria'][:4], [6,10,15,15]): c['points']=points
                with patch.object(self.pack,'evaluate',return_value=original):
                    r=s.evaluate('Привет')
                self.assertEqual(r['minute_bonus'],bonus)
                self.assertEqual(r['score'],460+bonus)

    def test_network_failure_local_backup_retry_and_finish_gate(self):
        s = self.session()
        import result_store
        original = result_store.atomic_json
        def fail_network(path, record):
            if Path(path).is_relative_to(self.root / 'results'):
                raise OSError('Share offline')
            return original(path,record)
        with patch('result_store.atomic_json',side_effect=fail_network):
            r = s.evaluate('Привет')
        self.assertFalse(r['storage']['saved']);self.assertTrue(r['storage']['local_backup'])
        self.assertEqual(len(list((self.root/'outbox').glob('*.json'))),1)
        with self.assertRaises(ValueError):s.finish()
        self.assertTrue(s.retry_save()['saved']);s.finish()
        self.assertEqual(len(list((self.root/'outbox').glob('*.json'))),0)

    def test_pending_recovered_after_restart_into_original_day(self):
        s = self.session()
        import result_store
        original = result_store.atomic_json
        with patch('result_store.atomic_json',side_effect=lambda p,r: (_ for _ in ()).throw(OSError()) if Path(p).is_relative_to(self.root/'results') else original(p,r)):
            s.evaluate('Привет')
        new_store = ResultStore(self.root/'results',self.root/'outbox')
        self.assertEqual(new_store.recover(),{'recovered':1,'pending':0})
        self.assertEqual(new_store.recover(),{'recovered':0,'pending':0})
        self.assertEqual(len(list((self.root/'results'/'2026-10-01').glob('*.json'))),1)

    def test_parallel_100_attempts_no_overwrite(self):
        def play(i):
            s = ParticipantSession(self.pack,lambda ids:ids[i%30],store=self.store,multiplier=10,day_provider=lambda:'2026-10-01')
            s.start('Иван','Иванов' + chr(0x430 + i // 32) + chr(0x430 + i % 32));r=s.evaluate('Привет');self.assertTrue(r['storage']['saved']);s.finish()
        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(play,range(100)))
        folder=self.root/'results'/'2026-10-01'
        self.assertEqual(len(list(folder.glob('*.json'))),100)
        self.assertFalse(list(folder.glob('*.tmp')))
        records,errors,duplicates=read_results(folder,'2026-10-01')
        self.assertEqual(len(records),100);self.assertEqual(errors,[]);self.assertEqual(duplicates,0)

    def test_places_duplicates_dates_and_workbook(self):
        sessions=[]
        for delta,prompt in [(20,'good'),(10,'good'),(10,'good'),(1,'zero')]:
            s=self.session();self.now += delta
            s.evaluate(self.pack.tasks['task_01']['example_full_prompt'] if prompt=='good' else 'Привет')
            sessions.append(s)
        folder=self.root/'results'/'2026-10-01'
        atomic_json(folder/'duplicate.json',sessions[0].record)
        (folder/'broken.json').write_text('{broken')
        atomic_json(self.root/'results'/'2026-10-02'/'other.json',dict(sessions[0].record,event_day='2026-10-02'))
        target,count,errors,dupes=collect(self.root,'2026-10-01')
        self.assertEqual(count,4);self.assertEqual(dupes,1);self.assertEqual(len(errors),1)
        rows,_,_=read_results(folder,'2026-10-01')
        self.assertEqual([r['rank'] for r in rows],[1,1,3,4])
        self.assertEqual([r['duration_ms'] for r in rows],[10000,10000,20000,1000])
        with zipfile.ZipFile(target) as z:
            self.assertIsNone(z.testzip())
            for name in z.namelist():
                if name.endswith('.xml') or name.endswith('.rels'): ET.fromstring(z.read(name))
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            self.assertEqual([int(c.text) for c in sheet.findall('.//s:c[@r="A2"]/s:v',ns)],[1])
            self.assertEqual(len(sheet.findall('s:sheetData/s:row',ns)),5)
        collect(self.root,'2026-10-01')
        self.assertEqual(len(read_results(folder,'2026-10-01')[0]),4)

    def test_conflicting_id_and_mixed_scale_rejected(self):
        s=self.session();s.evaluate('Привет');folder=self.root/'results'/'2026-10-01'
        bad=copy.deepcopy(s.record);bad['computer']='Different';atomic_json(folder/'conflict.json',bad)
        self.assertEqual(len(read_results(folder,'2026-10-01')[0]),0)
        (folder/'conflict.json').unlink()
        t=ParticipantSession(self.pack,lambda ids:ids[0],store=self.store,multiplier=1,day_provider=lambda:'2026-10-01')
        t.start('Анна','Иванова');t.evaluate('Привет')
        with self.assertRaises(ValueError):collect(self.root,'2026-10-01')

    def test_write_preflight_and_settings(self):
        with patch.object(self.store,'preflight',side_effect=OSError()):
            s=ParticipantSession(self.pack,store=self.store)
            with self.assertRaises(ValueError):s.start('Иван','Иванов')
            self.assertIsNone(s.participant)
        self.assertEqual(load_settings(self.root)['time_limit_seconds'],600)
        self.assertEqual(results_dir(self.root,load_settings(self.root)),self.root/'results')
        (self.root/'config.json').write_text(json.dumps({'time_limit_seconds':30}))
        with self.assertRaises(ValueError):load_settings(self.root)

    def test_minute_bonus_in_excel_and_ranking(self):
        for elapsed in [240,300]:
            self.now=0;s=self.session();self.now=elapsed
            s.evaluate(self.pack.tasks[s.task_id]['example_full_prompt'])
        folder=self.root/'results'/'2026-10-01'
        rows,errors,_=read_results(folder,'2026-10-01')
        self.assertEqual(errors,[])
        self.assertEqual([r['evaluation']['score'] for r in rows],[1006,1005])
        target,_,_,_=collect(self.root,'2026-10-01')
        with zipfile.ZipFile(target) as z:
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            for cell,value in [('D2',1006),('M2',1000),('N2',6),('E2',1010)]:
                self.assertEqual(int(sheet.find(f'.//s:c[@r="{cell}"]/s:v',ns).text),value)

    def test_legacy_formula_can_be_read_but_not_mixed(self):
        s=self.session();self.now=300;s.evaluate(self.pack.tasks[s.task_id]['example_full_prompt'])
        legacy=copy.deepcopy(s.record);legacy['attempt_id']='00000000-0000-4000-8000-000000000001'
        e=legacy['evaluation'];e['score']=e['requirements_score'];e['max_score']=e['requirements_max_score']
        for key in ['scoring_rule','minute_bonus','requirements_score','requirements_max_score']:e.pop(key)
        folder=self.root/'results'/'2026-10-01';atomic_json(folder/'legacy.json',legacy)
        with self.assertRaises(ValueError):read_results(folder,'2026-10-01')
        (folder/(s.attempt_id+'.json')).unlink()
        self.assertEqual(len(read_results(folder,'2026-10-01')[0]),1)

    def test_repeat_blocked_on_another_instance_and_existing_records(self):
        s=ParticipantSession(self.pack,store=self.store,day_provider=lambda:'2026-10-01')
        s.start('Пётр','Иванов');s.evaluate('Привет');s.finish()
        other=ParticipantSession(self.pack,store=self.store,day_provider=lambda:'2026-10-01')
        with self.assertRaises(ValueError):other.start(' ПЕТР ','ИВАНОВ')
        self.assertIsNone(other.participant)
        # Existing records still block repeats even if the reservation was removed.
        import shutil
        shutil.rmtree(self.root/'results'/'2026-10-01'/'.participants')
        with self.assertRaises(ValueError):other.start('Пётр','Иванов')
        next_day=ParticipantSession(self.pack,store=self.store,day_provider=lambda:'2026-10-02')
        next_day.start('Пётр','Иванов')

    def test_parallel_same_participant_only_one_can_start(self):
        import threading
        barrier=threading.Barrier(10)
        def register(i):
            session=ParticipantSession(self.pack,store=self.store,day_provider=lambda:'2026-10-01')
            barrier.wait()
            try:session.start('Иван','Иванов');return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=10) as pool:
            admitted=list(pool.map(register,range(10)))
        self.assertEqual(sum(admitted),1)


if __name__=='__main__':unittest.main()
