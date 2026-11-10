"""Record ids.

Every record has a public id: 24 lowercase hex characters (4-byte timestamp + 5 random bytes + 3-byte counter).
It is stored in the `public_id` column of each table and is what the API and the frontend use. The integer `id`
column is MySQL's internal primary key and never leaves the database layer.

The format is identical to the old MongoDB ObjectId, so existing data, URLs and the frontend keep working,
but nothing here depends on MongoDB (no `bson` / `pymongo` package).
"""
import os
import re
import threading
import time
from typing import Any

_HEX24 = re.compile(r"^[0-9a-fA-F]{24}$")
_lock = threading.Lock()
_counter = int.from_bytes(os.urandom(3), "big")
_process = os.urandom(5)


class ObjectId:
    __slots__ = ("_hex",)

    def __init__(self, oid: Any = None):
        if oid is None:
            global _counter
            with _lock:
                _counter = (_counter + 1) & 0xFFFFFF
                c = _counter
            self._hex = (int(time.time()).to_bytes(4, "big") + _process + c.to_bytes(3, "big")).hex()
        elif isinstance(oid, ObjectId):
            self._hex = oid._hex
        elif isinstance(oid, str) and _HEX24.match(oid):
            self._hex = oid.lower()
        elif isinstance(oid, (bytes, bytearray)) and len(oid) == 12:
            self._hex = bytes(oid).hex()
        else:
            raise ValueError(f"{oid!r} is not a valid id (expected 24 hex characters)")

    @classmethod
    def is_valid(cls, oid: Any) -> bool:
        try:
            cls(oid)
            return oid is not None
        except (ValueError, TypeError):
            return False

    def __str__(self) -> str:
        return self._hex

    def __repr__(self) -> str:
        return f"ObjectId('{self._hex}')"

    def __hash__(self) -> int:
        return hash(self._hex)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, ObjectId) and other._hex == self._hex

    def __lt__(self, other: Any) -> bool:
        return self._hex < other._hex if isinstance(other, ObjectId) else NotImplemented

    def __le__(self, other: Any) -> bool:
        return self._hex <= other._hex if isinstance(other, ObjectId) else NotImplemented

    def __gt__(self, other: Any) -> bool:
        return self._hex > other._hex if isinstance(other, ObjectId) else NotImplemented

    def __ge__(self, other: Any) -> bool:
        return self._hex >= other._hex if isinstance(other, ObjectId) else NotImplemented


def new_id() -> str:
    return str(ObjectId())
