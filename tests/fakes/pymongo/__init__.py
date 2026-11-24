"""Tiny in-memory stand-in for pymongo, covering only what the portal uses.
Like the real driver it stores datetimes as UTC and hands them back WITHOUT a timezone."""
import copy
import datetime as dt

from bson import ObjectId
from pymongo.errors import ConfigurationError, DuplicateKeyError  # noqa: F401


def _naive(v):
    if isinstance(v, dt.datetime) and v.tzinfo is not None:
        return v.astimezone(dt.timezone.utc).replace(tzinfo=None)
    if isinstance(v, dict):
        return {k: _naive(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_naive(x) for x in v]
    return v


def _match(doc, flt):
    for key, cond in (flt or {}).items():
        val = doc.get(key)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                arg = _naive(arg)
                if op == "$in":
                    if val not in arg and not (val is None and None in arg):
                        return False
                elif op == "$nin":
                    if val in arg:
                        return False
                elif op == "$ne":
                    if val == arg:
                        return False
                elif op == "$gte":
                    if val is None or not val >= arg:
                        return False
                elif op == "$lt":
                    if val is None or not val < arg:
                        return False
                elif op == "$exists":
                    if (key in doc) != arg:
                        return False
                else:
                    raise NotImplementedError(op)
        elif val != _naive(cond):
            return False
    return True


class _Result:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        keys = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(keys):
            self._docs.sort(key=lambda x, k=k: (x.get(k) is None, x.get(k)), reverse=(d == -1))
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(copy.deepcopy(self._docs))


class Collection:
    def __init__(self):
        self._docs = []
        self._unique = []

    def create_index(self, keys, unique=False, **kw):
        if unique and isinstance(keys, str):
            self._unique.append(keys)

    def _check_unique(self, doc, ignore=None):
        for f in self._unique:
            for d in self._docs:
                if d is not ignore and d.get(f) == doc.get(f):
                    raise DuplicateKeyError(f"duplicate {f}")

    def insert_one(self, doc):
        doc = _naive(copy.deepcopy(doc))
        self._check_unique(doc)
        doc.setdefault("_id", ObjectId())
        self._docs.append(doc)
        return _Result(inserted_id=doc["_id"])

    def insert_many(self, docs):
        return _Result(inserted_ids=[self.insert_one(d).inserted_id for d in docs])

    def find(self, flt=None):
        return Cursor([d for d in self._docs if _match(d, flt)])

    def find_one(self, flt=None, sort=None):
        cur = self.find(flt)
        if sort:
            cur.sort(sort)
        for d in cur:
            return d
        return None

    def _apply(self, d, update):
        for op, fields in update.items():
            if op == "$set":
                d.update(_naive(copy.deepcopy(fields)))
            else:
                raise NotImplementedError(op)

    def update_one(self, flt, update, upsert=False):
        for d in self._docs:
            if _match(d, flt):
                self._apply(d, update)
                return _Result(matched_count=1)
        if upsert:
            d = {"_id": flt.get("_id", ObjectId())}
            self._apply(d, update)
            self._docs.append(d)
        return _Result(matched_count=0)

    def update_many(self, flt, update):
        n = 0
        for d in self._docs:
            if _match(d, flt):
                self._apply(d, update)
                n += 1
        return _Result(matched_count=n)

    def delete_one(self, flt):
        for d in self._docs:
            if _match(d, flt):
                self._docs.remove(d)
                return _Result(deleted_count=1)
        return _Result(deleted_count=0)

    def delete_many(self, flt):
        keep = [d for d in self._docs if not _match(d, flt)]
        n = len(self._docs) - len(keep)
        self._docs[:] = keep
        return _Result(deleted_count=n)

    def count_documents(self, flt):
        return sum(1 for d in self._docs if _match(d, flt))


class Database:
    def __init__(self):
        self._c = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, Collection())


class MongoClient:
    def __init__(self, *a, **kw):
        self._dbs = {}

    def __getitem__(self, name):
        return self._dbs.setdefault(name, Database())

    def get_default_database(self):
        raise ConfigurationError("no default")
