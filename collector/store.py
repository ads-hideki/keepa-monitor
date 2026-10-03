# -*- coding: utf-8 -*-
"""保存先（Firestore）。テストではメモリ上の代用品を使う。

読み書きの回数を抑えるため、画面用のデータは少数のドキュメントにまとめて書く。
1 ドキュメントの上限（1MiB）を超えないよう、書く前に大きさを確かめる。
"""
import copy
import json

MAX_DOC_BYTES = 900 * 1024


class StoreError(Exception):
    pass


def _check_shape(path, value, in_list=False):
    """Firestore が保存できない形（配列の入れ子、文字列でないキー）を書く前に見つける。"""
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or not k:
                raise StoreError('{}: キーは空でない文字列にしてください（{!r}）'.format(path, k))
            _check_shape(path, v)
    elif isinstance(value, (list, tuple)):
        if in_list:
            raise StoreError('{}: 配列の中に配列は保存できません'.format(path))
        for v in value:
            _check_shape(path, v, in_list=True)


def _check_size(path, data):
    _check_shape(path, data)
    size = len(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    if size > MAX_DOC_BYTES:
        raise StoreError('{} が大きすぎます（{} KB）。分割が必要です'.format(path, size // 1024))
    return size


class MemoryStore:
    def __init__(self, initial=None):
        self.docs = copy.deepcopy(initial or {})
        self.reads = 0
        self.writes = 0

    def get(self, path):
        self.reads += 1
        return copy.deepcopy(self.docs.get(path))

    def set(self, path, data):
        _check_size(path, data)
        self.writes += 1
        self.docs[path] = copy.deepcopy(data)

    def list(self, collection):
        prefix = collection.rstrip('/') + '/'
        out = {}
        for k, v in self.docs.items():
            if k.startswith(prefix) and '/' not in k[len(prefix):]:
                out[k[len(prefix):]] = copy.deepcopy(v)
        self.reads += max(1, len(out))
        return out


class FirestoreStore:
    def __init__(self, service_account_info):
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(service_account_info))
        self.db = firestore.client()
        self.reads = 0
        self.writes = 0

    def _ref(self, path):
        col, doc = path.split('/', 1)
        return self.db.collection(col).document(doc)

    def get(self, path):
        self.reads += 1
        snap = self._ref(path).get()
        return snap.to_dict() if snap.exists else None

    def set(self, path, data):
        _check_size(path, data)
        self.writes += 1
        self._ref(path).set(data)

    def list(self, collection):
        out = {d.id: d.to_dict() for d in self.db.collection(collection).stream()}
        self.reads += max(1, len(out))
        return out
