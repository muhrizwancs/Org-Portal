"""Test stand-in for bson (the real one ships with pymongo)."""
import itertools
import os

_counter = itertools.count(int.from_bytes(os.urandom(3), "big"))


class ObjectId:
    def __init__(self, value=None):
        from bson.errors import InvalidId
        if value is None:
            self._h = f"{next(_counter):08x}" + os.urandom(8).hex()
        elif isinstance(value, ObjectId):
            self._h = value._h
        elif isinstance(value, str) and len(value) == 24 and all(c in "0123456789abcdefABCDEF" for c in value):
            self._h = value.lower()
        else:
            raise InvalidId(f"{value!r} is not a valid ObjectId")

    def __str__(self): return self._h
    def __repr__(self): return f"ObjectId('{self._h}')"
    def __eq__(self, o): return isinstance(o, ObjectId) and o._h == self._h
    def __hash__(self): return hash(self._h)
    def __lt__(self, o): return self._h < o._h
