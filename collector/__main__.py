# -*- coding: utf-8 -*-
"""使い方: python -m collector <auto|daily|prices|candidates|research|markets>"""
import os
import sys
import traceback
from datetime import datetime

from .config import Config
from .keepa import Keepa, KeepaError
from .parse import JST
from .pipeline import Run
from .store import FirestoreStore

JOBS = ('auto', 'daily', 'prices', 'candidates', 'research', 'markets')


def main(argv):
    if len(argv) != 2 or argv[1] not in JOBS:
        print(__doc__)
        return 2
    # GitHub Actions では出力がまとめて表示されるので、1 行ごとに出す
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    job, cfg, store, keepa = argv[1], Config(), None, None
    try:
        keepa = Keepa(cfg.keepa_key, max_runtime_s=cfg.max_runtime_s)
        store = FirestoreStore(cfg.service_account())
        getattr(Run(store, keepa, cfg), 'job_' + job)()
    except Exception as e:                                    # noqa: BLE001
        # 公開リポジトリのログに商品名や ASIN を出さないため、例外の中身は表示しない。
        # Keepa のエラーだけは、内容が API の状態（キー無効、トークン不足など）に限られるので表示する。
        frame = traceback.extract_tb(e.__traceback__)[-1]
        where = '{}:{}'.format(os.path.basename(frame.filename), frame.lineno)
        detail = str(e) if isinstance(e, KeepaError) else type(e).__name__
        print('エラーで終了しました: {}（{}）'.format(detail, where))
        if store is not None:
            try:
                store.set('state/last_error', {'at': datetime.now(JST).isoformat(), 'job': job, 'error': detail, 'where': where})
            except Exception:                                 # noqa: BLE001
                pass
        return 1
    if keepa.spent:
        print('完了: 消費トークン {} / 残り {}'.format(keepa.spent, keepa.tokens_left))
    else:
        print('完了: Keepa は呼び出していません')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
