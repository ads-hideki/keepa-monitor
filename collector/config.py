# -*- coding: utf-8 -*-
"""設定。秘密の値と、事業の内容が分かる値（アカウント名、連携先）は環境変数で受け取り、コードには書かない。"""
import json
import os


def env(name, default=None):
    v = os.environ.get(name)
    return default if v is None or v.strip() == '' else v.strip()


class Config:
    def __init__(self):
        self.keepa_key = env('KEEPA_API_KEY')
        self.dashboard_project = env('DASHBOARD_PROJECT_ID')
        self.dashboard_api_key = env('DASHBOARD_API_KEY')
        self.accounts = [a.strip() for a in env('DASHBOARD_ACCOUNTS', '').split(',') if a.strip()]
        self.max_categories = int(env('MAX_CATEGORIES', '40'))
        self.category_top = int(env('CATEGORY_TOP', '40'))
        self.max_runtime_s = int(env('MAX_RUNTIME_MINUTES', '300')) * 60
        # 1回の実行で競合候補を作る商品数（0 は制限なし）
        self.candidates_per_run = int(env('CANDIDATES_PER_RUN', '0'))

    def service_account(self):
        raw = env('FIREBASE_SERVICE_ACCOUNT')
        if raw:
            return json.loads(raw)
        path = env('FIREBASE_SERVICE_ACCOUNT_PATH')
        if path and os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        raise RuntimeError('FIREBASE_SERVICE_ACCOUNT が設定されていません')


# 通知の基準（settings/thresholds で上書きできる）
DEFAULT_THRESHOLDS = {
    'ratingDrop': 0.2,        # 7日前より評価がこれ以上下がったら通知
    'rankWorsePct': 50,       # 直近3日の平均順位が、1週間前の3日平均よりこの%以上悪化したら通知
    'pageChangeDays': 7,      # ページ変更の通知を出し続ける日数
    'outOfStockMaxDays': 14,  # 競合の在庫切れを「好機」として出す日数の上限
    'maxOffersForPb': 2,      # 出品者がこの数以下なら PB らしいとみなす
}

# 新商品リサーチの初期条件（settings/research で上書きできる）
DEFAULT_RESEARCH = {
    'priceMin': 1500, 'priceMax': 5000, 'rankMax': 10000, 'reviewsMax': 100, 'soldMin': 300, 'limit': 30,
    # 狙う商品の推定月商（価格 × 月間販売数）の範囲。市場の評価に使う。
    'revMin': 300000, 'revMax': 5000000,
    # リサーチの対象から外す大カテゴリ（名前）。カテゴリでは絞らず、作って売る対象にならないものだけを外す。
    # 1 文字の名前は完全一致、2 文字以上は「含む」で判定する。画面で変えられる。
    'excludeRoots': ['本', '洋書', 'Kindle', 'ミュージック', 'クラシック', 'DVD', 'ゲーム', 'PCソフト', 'Prime Video',
                     'ギフトカード', 'Amazonデバイス', 'Audible', 'アプリ'],
}
