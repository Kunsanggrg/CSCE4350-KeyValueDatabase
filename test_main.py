
import os
import tempfile
import unittest

from main import KVStore


class TestKVStore(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "data.db")
        self.db = KVStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_set_get(self):
        self.db.execute(["SET", "name", "Alex"])
        self.assertEqual(self.db.execute(["GET", "name"]), "Alex")

    def test_overwrite(self):
        self.db.execute(["SET", "name", "Alex"])
        self.db.execute(["SET", "name", "Sam"])
        self.assertEqual(self.db.execute(["GET", "name"]), "Sam")

    def test_delete(self):
        self.db.execute(["SET", "item", "value"])
        self.db.execute(["DEL", "item"])
        self.assertEqual(self.db.execute(["EXISTS", "item"]), "0")

    def test_persistence(self):
        self.db.execute(["SET", "saved", "yes"])
        restored = KVStore(self.db_path)
        self.assertEqual(restored.execute(["GET", "saved"]), "yes")

    def test_multiple_keys(self):
        self.db.execute(["MSET", "a", "1", "b", "2"])
        self.assertEqual(self.db.execute(["MGET", "a", "b"]), "1\n2")

    def test_hash(self):
        self.db.execute(["HSET", "user", "name", "Alex"])
        self.assertEqual(
            self.db.execute(["HGET", "user", "name"]), "Alex"
        )

    def test_list(self):
        self.db.execute(["RPUSH", "items", "one"])
        self.db.execute(["RPUSH", "items", "two"])
        self.assertEqual(
            self.db.execute(["LPOP", "items"]), "one"
        )

    def test_counter(self):
        self.db.execute(["SET", "count", "5"])
        self.assertEqual(self.db.execute(["INCR", "count"]), "6")

    def test_transaction(self):
        self.db.execute(["BEGIN"])
        self.db.execute(["SET", "temp", "value"])
        self.db.execute(["ABORT"])
        self.assertEqual(self.db.execute(["GET", "temp"]), "nil")

    def test_flush(self):
        self.db.execute(["SET", "key", "value"])
        self.db.execute(["FLUSHDB"])
        self.assertEqual(self.db.execute(["GET", "key"]), "nil")


if __name__ == "__main__":
    unittest.main()
