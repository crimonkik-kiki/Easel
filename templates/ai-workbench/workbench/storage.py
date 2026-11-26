"""Durable jobs, event replay and conversations, isolated per copied project."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager


@contextmanager
def instance_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        stream.close()


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.mutex = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS docs (kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,job TEXT,body TEXT)')
        self.db.commit()

    def get(self, kind, identifier):
        with self.mutex:
            row = self.db.execute('SELECT body FROM docs WHERE kind=? AND id=?', (kind, identifier)).fetchone()
            if row is None:
                raise KeyError(identifier)
            return json.loads(row[0])

    def put(self, kind, data):
        with self.mutex:
            self.db.execute('INSERT OR REPLACE INTO docs VALUES(?,?,?)', (kind, data['id'], json.dumps(data, ensure_ascii=False)))
            self.db.commit()
        return data

    def list(self, kind):
        with self.mutex:
            rows = self.db.execute('SELECT body FROM docs WHERE kind=?', (kind,)).fetchall()
        return sorted((json.loads(row[0]) for row in rows), key=lambda d: d.get('created_at', 0), reverse=True)

    def event(self, job, kind, text='', **extra):
        with self.mutex:
            event = {'kind': kind, 'text': text, **extra}
            cursor = self.db.execute('INSERT INTO events(job,body) VALUES(?,?)', (job, json.dumps(event, ensure_ascii=False)))
            self.db.commit()
            return {**event, 'seq': cursor.lastrowid}

    def events(self, job, after):
        with self.mutex:
            rows = self.db.execute('SELECT seq,body FROM events WHERE job=? AND seq>? ORDER BY seq LIMIT 500', (job, after)).fetchall()
        return [{**json.loads(row[1]), 'seq': row[0]} for row in rows]

    def close(self):
        self.db.close()
