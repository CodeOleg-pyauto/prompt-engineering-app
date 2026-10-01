import unittest

from prompt_rules import TaskPack
from session import ParticipantSession, normalize_name


class NameTests(unittest.TestCase):
    def test_case_and_separators(self):
        for raw, expected in [(' иВаН ', 'Иван'), ('ЁЛКИН', 'Ёлкин'),
                              ('анна-мАРИЯ', 'Анна-Мария'), ('де СА', 'Де Са')]:
            self.assertEqual(normalize_name(raw), expected)

    def test_wrong_language_and_punctuation(self):
        for raw in ['', '  ', 'Ivan', 'Ивaн', 'Иван1', 'Иван!', '-Иван',
                    'Анна--Мария', 'Иван\nИван', 'Иван  Иван', 'Іван', 'а' * 51, None]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_name(raw)


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = TaskPack()

    def test_assignment_stays_fixed_and_first_score_is_locked(self):
        calls = []
        def choice(ids):
            calls.append(ids)
            return ids[-1]
        session = ParticipantSession(self.pack, choice, clock=lambda:0)
        data = session.start('иВАН', 'ИВАНОВ')
        self.assertEqual(data['participant']['first'], 'Иван')
        self.assertEqual(data['task']['id'], 'task_30')
        self.assertEqual(set(calls[0]), set(self.pack.tasks))
        self.assertNotIn('example_full_prompt', data['task'])
        with self.assertRaises(ValueError): session.start('Пётр', 'Петров')
        r = session.evaluate(self.pack.tasks['task_30']['example_full_prompt'])
        self.assertEqual(r['score'], 110)
        r['score'] = 1
        self.assertEqual(session.evaluate('Пустое требование')['score'], 110)
        self.assertEqual(len(calls), 1)

    def test_reset_removes_identity_result_and_task(self):
        sequence = iter(['task_01', 'task_02'])
        session = ParticipantSession(self.pack, lambda ids: next(sequence), clock=lambda:0)
        session.start('Иван', 'Иванов'); session.evaluate('Привет')
        session.finish()
        self.assertIsNone(session.participant)
        self.assertIsNone(session.task_id)
        self.assertIsNone(session.result)
        data = session.start('Анна', 'Петрова')
        self.assertEqual(data['task']['id'], 'task_02')
        self.assertEqual(data['participant']['first'], 'Анна')
        self.assertEqual(session.evaluate(self.pack.tasks['task_02']['example_full_prompt'])['score'], 110)

    def test_invalid_inputs_do_not_start_or_lock_attempt(self):
        session = ParticipantSession(self.pack, clock=lambda:0)
        with self.assertRaises(ValueError): session.evaluate('Текст')
        with self.assertRaises(ValueError): session.start('Ivan', 'Иванов')
        self.assertIsNone(session.participant)
        session.start('Иван', 'Иванов')
        for text in ['', ' ', None, 'а' * 6001]:
            with self.subTest(text_type=type(text).__name__), self.assertRaises(ValueError):
                session.evaluate(text)
            self.assertIsNone(session.result)
        self.assertEqual(session.evaluate('Привет')['score'], 10)

    def test_same_task_can_be_assigned_to_different_participants(self):
        session = ParticipantSession(self.pack, lambda ids: ids[0], clock=lambda:0)
        self.assertEqual(session.start('Иван', 'Иванов')['task']['id'], 'task_01')
        session.finish()
        self.assertEqual(session.start('Анна', 'Петрова')['task']['id'], 'task_01')

    def test_every_task_can_flow_through_session(self):
        for task_id, task in self.pack.tasks.items():
            with self.subTest(task=task_id):
                session = ParticipantSession(self.pack, lambda ids: task_id, clock=lambda:0)
                self.assertEqual(session.start('Анна', 'Иванова')['task']['id'], task_id)
                self.assertEqual(session.evaluate(task['example_full_prompt'])['score'], 110)
                session.finish()


if __name__ == '__main__':
    unittest.main()
