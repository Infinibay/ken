"""Cooperative cancellation across SQLite VM work and Python graph operators."""

import sqlite3
from contextlib import contextmanager


class ReadCursor:
    def __init__(self, connection, cursor):
        self.connection, self.cursor = connection, cursor

    def fetchone(self):
        return self.connection.call(self.cursor.fetchone)

    def fetchall(self):
        return self.connection.call(self.cursor.fetchall)

    def __iter__(self):
        try:
            yield from self.cursor
        except sqlite3.OperationalError as exc:
            self.connection.interrupted(exc)
        finally:
            self.close()

    def close(self):
        self.cursor.close()


class ReadConnection:
    def __init__(self, db):
        self.raw = db
        self.stopped = None

    def call(self, operation, *args):
        try:
            return operation(*args)
        except sqlite3.OperationalError as exc:
            self.interrupted(exc)

    def interrupted(self, error):
        if self.stopped is not None:
            stopped, self.stopped = self.stopped, None
            raise stopped
        raise error

    def execute(self, *args):
        return ReadCursor(self, self.call(self.raw.execute, *args))

    @contextmanager
    def execution(self, check):
        def progress():
            try:
                check()
                return 0
            except Exception as exc:  # noqa: BLE001 -- re-raised outside SQLite's callback boundary
                self.stopped = exc
                return 1

        self.stopped = None
        self.raw.set_progress_handler(progress, 2000)
        try:
            check()
            yield
        finally:
            self.raw.set_progress_handler(None, 0)
            self.stopped = None
