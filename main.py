import json
import math
import os
import shlex
import sys
import time

DATA_FILE = "data.db"
MISSING = "nil"
SUCCESS = "OK"
ERROR = "ERROR"
END = "END"


class KVStore:
    """A command-line database using a list-based index."""

    def __init__(self, path=DATA_FILE):
        self.path = path
        self.items = []
        self.transaction = None
        self.recover()

    def find(self, key):
        """Find a key without using a built-in dictionary."""
        for index, item in enumerate(self.items):
            if item[0] == key:
                return index
        return -1

    def entry(self, key):
        """Return an entry unless it is missing or expired."""
        index = self.find(key)

        if index < 0:
            return None

        item = self.items[index]
        expiry = item[3]

        if expiry is not None and expiry <= time.time():
            self.items.pop(index)
            return None

        return item

    def apply(self, record):
        """Apply a recorded operation to memory."""
        operation = record[0]

        if operation == "PUT":
            key, kind, value, expiry = record[1:5]
            item = [key, kind, value, expiry]
            index = self.find(key)

            if index < 0:
                self.items.append(item)
            else:
                self.items[index] = item

        elif operation == "DEL":
            index = self.find(record[1])
            if index >= 0:
                self.items.pop(index)

        elif operation == "FLUSH":
            self.items.clear()

    def write(self, records):
        """Append operations to disk immediately."""
        if not records:
            return

        with open(self.path, "a", encoding="utf-8") as file:
            file.write(json.dumps(records) + "\n")
            file.flush()
            os.fsync(file.fileno())

    def recover(self):
        """Replay the append-only log after a restart."""
        if not os.path.exists(self.path):
            return

        with open(self.path, "r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue

                try:
                    records = json.loads(line)

                    # Support the original starter program's log.
                    if records and isinstance(records[0], str):
                        if records[0] == "SET" and len(records) == 3:
                            records = [[
                                "PUT", records[1], "string",
                                records[2], None
                            ]]
                        elif records[0] in ("DEL", "DELETE"):
                            records = [["DEL", records[1]]]
                        else:
                            continue

                    for record in records:
                        self.apply(record)

                except (ValueError, TypeError, IndexError):
                    continue

    def change(self, records):
        """Record changes and update the in-memory state."""
        if self.transaction is None:
            self.write(records)
        else:
            self.transaction.extend(records)

        for record in records:
            self.apply(record)

    @staticmethod
    def integer(value):
        """Convert a value into an integer."""
        return int(value)

    def execute(self, args):
        """Execute one database command."""
        if not args:
            return ""

        command = args[0].upper()
        a = args[1:]

        # EXIT
        if command in ("EXIT", "QUIT"):
            return None if not a else ERROR

        # TRANSACTIONS
        if command == "BEGIN":
            if a or self.transaction is not None:
                return ERROR
            self.transaction = []
            return SUCCESS

        if command == "COMMIT":
            if a or self.transaction is None:
                return ERROR

            self.write(self.transaction)
            self.transaction = None
            return SUCCESS

        if command == "ABORT":
            if a or self.transaction is None:
                return ERROR

            self.transaction = None
            self.items.clear()
            self.recover()
            return SUCCESS

        # SET / MSET
        if command in ("SET", "MSET"):
            if len(a) < 2 or len(a) % 2 != 0:
                return ERROR

            if command == "SET" and len(a) != 2:
                return ERROR

            records = []

            for i in range(0, len(a), 2):
                records.append([
                    "PUT", a[i], "string", a[i + 1], None
                ])

            self.change(records)
            return SUCCESS

        # GET
        if command == "GET":
            if len(a) != 1:
                return ERROR

            item = self.entry(a[0])

            if item is None:
                return MISSING

            if item[1] != "string":
                return ERROR

            return str(item[2])

        # MGET
        if command == "MGET":
            if not a:
                return ERROR

            result = []

            for key in a:
                item = self.entry(key)

                if item is None:
                    result.append(MISSING)
                elif item[1] == "string":
                    result.append(str(item[2]))
                else:
                    result.append(ERROR)

            return "\n".join(result)

        # DEL / DELETE
        if command in ("DEL", "DELETE"):
            if len(a) != 1:
                return ERROR

            exists = self.entry(a[0]) is not None

            if exists:
                self.change([["DEL", a[0]]])

            return "1" if exists else "0"

        # EXISTS
        if command == "EXISTS":
            if len(a) != 1:
                return ERROR

            return "1" if self.entry(a[0]) else "0"

        # FLUSHDB
        if command == "FLUSHDB":
            if a:
                return ERROR

            self.change([["FLUSH"]])
            return SUCCESS

        # EXPIRE
        if command == "EXPIRE":
            if len(a) != 2:
                return ERROR

            seconds = self.integer(a[1])
            item = self.entry(a[0])

            if item is None:
                return "0"

            if seconds <= 0:
                self.change([["DEL", a[0]]])
                return "1"

            self.change([[
                "PUT",
                item[0],
                item[1],
                item[2],
                time.time() + seconds
            ]])

            return "1"

        # TTL
        if command == "TTL":
            if len(a) != 1:
                return ERROR

            item = self.entry(a[0])

            if item is None:
                return "-2"

            if item[3] is None:
                return "-1"

            remaining = item[3] - time.time()
            return str(max(0, math.ceil(remaining)))

        # RANGE
        if command == "RANGE":
            if len(a) != 2:
                return ERROR

            start, end = a
            keys = []

            for item in list(self.items):
                key = item[0]

                if self.entry(key) is None:
                    continue

                if start and key < start:
                    continue

                if end and key > end:
                    continue

                keys.append(key)

            keys.sort()
            return "\n".join(keys + [END])

        # HSET
        if command == "HSET":
            if len(a) != 3:
                return ERROR

            key, field, value = a
            item = self.entry(key)

            if item is not None and item[1] != "hash":
                return ERROR

            fields = (
                [pair[:] for pair in item[2]]
                if item else []
            )

            for pair in fields:
                if pair[0] == field:
                    pair[1] = value
                    break
            else:
                fields.append([field, value])

            expiry = item[3] if item else None

            self.change([[
                "PUT", key, "hash", fields, expiry
            ]])

            return SUCCESS

        # HGET / HGETALL
        if command in ("HGET", "HGETALL"):
            expected = 1 if command == "HGETALL" else 2

            if len(a) != expected:
                return ERROR

            item = self.entry(a[0])

            if item is None:
                return MISSING

            if item[1] != "hash":
                return ERROR

            if command == "HGETALL":
                result = []
                for field, value in item[2]:
                    result.extend([field, value])
                return " ".join(result) or MISSING

            for field, value in item[2]:
                if field == a[1]:
                    return value

            return MISSING

        # LPUSH / RPUSH
        if command in ("LPUSH", "RPUSH"):
            if len(a) != 2:
                return ERROR

            key, value = a
            item = self.entry(key)

            if item is not None and item[1] != "list":
                return ERROR

            values = item[2][:] if item else []

            if command == "LPUSH":
                values.insert(0, value)
            else:
                values.append(value)

            expiry = item[3] if item else None

            self.change([[
                "PUT", key, "list", values, expiry
            ]])

            return str(len(values))

        # LPOP
        if command == "LPOP":
            if len(a) != 1:
                return ERROR

            key = a[0]
            item = self.entry(key)

            if item is None:
                return MISSING

            if item[1] != "list":
                return ERROR

            values = item[2][:]

            if not values:
                return MISSING

            removed = values.pop(0)

            self.change([[
                "PUT",
                key,
                "list",
                values,
                item[3]
            ]])

            return removed

        # LRANGE
        if command == "LRANGE":
            if len(a) != 3:
                return ERROR

            item = self.entry(a[0])
            start = self.integer(a[1])
            stop = self.integer(a[2])

            if item is None:
                return END

            if item[1] != "list":
                return ERROR

            values = item[2]
            length = len(values)

            if start < 0:
                start += length

            if stop < 0:
                stop += length

            start = max(start, 0)
            stop = min(stop, length - 1)

            if start > stop:
                return END

            result = values[start:stop + 1]
            return "\n".join(result + [END])

        # INCR / DECR
        if command in ("INCR", "DECR"):
            if len(a) != 1:
                return ERROR

            key = a[0]
            item = self.entry(key)

            if item is not None and item[1] != "string":
                return ERROR

            number = self.integer(item[2]) if item else 0

            if command == "INCR":
                number += 1
            else:
                number -= 1

            expiry = item[3] if item else None

            self.change([[
                "PUT", key, "string", str(number), expiry
            ]])

            return str(number)

        return ERROR


def main():
    """Read commands from stdin and send responses to stdout."""
    database = KVStore()

    for line in sys.stdin:
        try:
            arguments = shlex.split(line.strip())
            answer = database.execute(arguments)

        except (ValueError, TypeError, OSError, IndexError):
            answer = ERROR

        if answer is None:
            break

        if answer != "":
            print(answer, flush=True)


if __name__ == "__main__":
    main()
