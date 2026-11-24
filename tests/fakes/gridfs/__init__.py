"""Test stand-in for gridfs.GridFS."""
import io

from bson import ObjectId


class GridFS:
    def __init__(self, db):
        self._files = {}

    def put(self, data, filename=None, content_type=None, **kw):
        fid = ObjectId()
        self._files[fid] = bytes(data)
        return fid

    def get(self, fid):
        if fid not in self._files:
            raise KeyError("no such file")
        return io.BytesIO(self._files[fid])

    def delete(self, fid):
        self._files.pop(fid, None)
