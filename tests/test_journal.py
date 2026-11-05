from mixly.journal import Busy, Journal
from tests.helpers import TempCase


class JournalTests(TempCase):
    def test_keeps_records_between_instances(self):
        Journal(self.base).put({"id": "a", "state": "moved"})
        self.assertEqual(Journal(self.base).get("a")["state"], "moved")

    def test_put_replaces_a_record(self):
        journal = Journal(self.base)
        journal.put({"id": "a", "state": "copying"})
        journal.put({"id": "a", "state": "moved"})
        self.assertEqual(len(journal.records()), 1)
        self.assertEqual(journal.get("a")["state"], "moved")

    def test_remove(self):
        journal = Journal(self.base)
        journal.put({"id": "a"})
        journal.remove("a")
        self.assertEqual(journal.records(), [])

    def test_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            Journal(self.base).get("nope")

    def test_lock_blocks_a_second_holder(self):
        journal = Journal(self.base)
        with journal.lock():
            with self.assertRaises(Busy):
                with Journal(self.base).lock():
                    pass
        with journal.lock():
            pass
    def test_corrupted_or_empty_journal_returns_empty_list(self):
        journal = Journal(self.base)
        self.write("journal.json", "")
        self.assertEqual(journal.records(), [])
        self.write("journal.json", "{corrupt json")
        self.assertEqual(journal.records(), [])
        self.write("journal.json", "{}")
        self.assertEqual(journal.records(), [])
