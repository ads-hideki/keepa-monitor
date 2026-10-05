# keepa-monitor

Keepa API で Amazon.co.jp の自社商品と競合を毎日取得し、変化を画面で確認するための仕組みです。

- 自社商品は手で登録しません。既存の在庫データから毎日取り込み、新しい商品は自動で監視対象に入ります。
- 競合は、同じカテゴリの売れ筋とキーワード検索から候補を作り、画面で選びます。候補にない商品は ASIN で追加できます。
- 取得は GitHub Actions、保存は Firestore、画面は Firebase Hosting で動きます。

**このリポジトリは公開です。** 鍵と、事業の内容が分かるデータ（商品名、ASIN、競合の一覧、連携先の名前）は、
コードにもログにも入れません。詳しくは「公開リポジトリとしての約束」を見てください。

## 構成

| 場所 | 内容 |
|---|---|
| `collector/` | 取得スクリプト（Python）。Keepa から読み、Firestore に書く |
| `tests/` | テスト。Keepa と Firestore の代用品を使うので、鍵なしで動く |
| `.github/workflows/collect.yml` | 取得の予約実行 |
| `.github/workflows/keepalive.yml` | 予約実行が自動停止しないようにする月 1 回のコミット |
| `.github/workflows/test.yml` | push のたびにテストを実行 |
| `firestore.rules` | Firestore のアクセス制御 |
| `docs/design.md` | 設計（データの持ち方、ジョブ、トークンの使い方） |
| `web/` | 画面（React + Vite）。Firestore の `views/*` を読んで表示し、設定だけを書き込む |
| `tools/make_mock.py` | 画面用の模擬データを作る。取得スクリプトを架空の商品で動かした結果を保存する |
| `.github/workflows/deploy.yml` | 画面の公開 |
| `tools/apps_script_trigger.gs` | 決まった時刻に取得を起動する外部のタイマー（Google Apps Script 用） |

## ジョブ

`python -m collector <ジョブ名>` で実行します。

| ジョブ | いつ | 内容 |
|---|---|---|
| `auto` | 予約実行 | いまの時刻と取得済みの内容を見て、`daily` か `prices` の必要なほうだけを実行する。取得済みなら何もしない |
| `daily` | 毎日 02:00 以降に 1 回（日本時間） | 自社商品の取り込み、自社カタログ、競合、カテゴリ順位、販売実績、通知。足りない競合候補も作る。月曜は新商品リサーチも実行 |
| `prices` | 毎日 10:00 / 14:00 / 19:00 以降に各 1 回 | 競合の価格・クーポン・セール・在庫だけを取り直す |
| `candidates` | 手動 | 競合候補をまとめて作る（初回や、キーワードを直したあと） |
| `research` | 手動 | 新商品リサーチだけを実行 |

GitHub の予約実行は時刻が保証されません。実際に動かしたところ、19 回の起動のうち動いたのは 6 回で、どれも 3〜5 時間半遅れました。
そのため、起動は外部のタイマー（Google Apps Script。`tools/apps_script_trigger.gs`）から行い、GitHub の予約は予備として残しています。
どちらから起動されても、`auto` が「まだ取得していない回」だけを実行します。
済んだかどうかは画面用データの更新時刻で判断するので、二重に起動しても 2 回目は何もせずに終わり、手動で実行した分も数に入ります。
日付をまたいで届いた起動は、前日の回として扱います。朝の取得が同じ日に 3 回失敗したら、それ以上は試しません。

### 外部のタイマー（Google Apps Script）

1. GitHub で Fine-grained personal access token を作る。対象はこのリポジトリだけ、権限は Actions の Read and write だけにする。
2. script.google.com で新しいプロジェクトを作り、`tools/apps_script_trigger.gs` の内容を貼る。
3. プロジェクトの設定 → スクリプト プロパティに `GITHUB_TOKEN` を追加する。
4. `setupTriggers` を 1 回実行する（タイマーが登録される）。`runCollect` を手動で実行すると、すぐに起動を試せる。

鍵の期限が切れると起動に失敗し、Google から失敗の通知メールが届きます。その間も GitHub の予約（予備）で取得は続きます。

トークンが足りないときは、エラーにせず回復を待って続けます。1 回の実行は最長 5 時間で打ち切り、
残った競合候補の作成は次回に回します。

## 準備

### 1. Firebase

1. 新しいプロジェクトを作る（既存のダッシュボードとは別のプロジェクトにする）。
2. Firestore を有効にする。
3. Authentication で「メール / パスワード」を有効にする。
   「設定 → ユーザー アクション」で **作成（登録）を無効** にする。
4. Authentication でユーザーを追加する。メールアドレスは `ログインID@ログイン用ドメイン` の形にする。
5. Firestore に `allowed_users` コレクションを作り、ドキュメント ID を各ユーザーの UID にして 1 件ずつ追加する（中身は空でよい）。
6. `firebase deploy --only firestore:rules` でルールを反映する。
7. 「プロジェクトの設定 → サービス アカウント」で秘密鍵（JSON）を作る。

### 2. GitHub

リポジトリの Settings → Secrets and variables → Actions に、次の Secret を登録します。

| Secret | 内容 |
|---|---|
| `KEEPA_API_KEY` | Keepa の API アクセスキー |
| `FIREBASE_SERVICE_ACCOUNT` | 手順 1-7 で作った JSON の中身をそのまま |
| `DASHBOARD_PROJECT_ID` | 在庫データを読む既存プロジェクトの ID |
| `DASHBOARD_ACCOUNTS` | 取り込むアカウントのキー（カンマ区切り） |

Settings → Actions → General で次も設定します。

- Fork pull request workflows は無効のままにする。

### 3. 初回の実行

Actions タブ → collect → Run workflow で `daily` を選んで実行します。
初回は全商品の競合候補を作るので、トークンの回復を待ちながら数時間かかります。途中で打ち切られても、次回の実行で続きから作ります。

### 4. 画面

`web/.env.example` を `web/.env.local` にコピーし、Firebase コンソールの「プロジェクトの設定 → マイアプリ」に表示される値を入れます。

```
cd web
npm install
npm run dev        # 手元で確認
npm run build      # web/dist に出力
cd ..
firebase deploy --only hosting,firestore:rules
```

`VITE_MOCK=1` を付けてビルドまたは起動すると、Firebase を使わず `web/public/mock/db.json` の模擬データで表示します。
模擬データは `python tools/make_mock.py` で作り直せます（中身はすべて架空の商品です）。

画面でできること:

- 概要（通知、監視対象の件数、トークン消費）
- 競合の価格・販促、カテゴリ順位、自社カタログ、競合在庫、新商品リサーチ、販売実績と一時的な値下げ
- 競合の設定（候補から選ぶ、ASIN または商品 URL で追加、キーワードを直して候補を作り直す、ブランドの除外）

設定の変更は、次回の取得からほかのタブに反映されます。

## 公開リポジトリとしての約束

- 鍵は GitHub の Secrets にだけ置く。`.gitignore` で鍵のファイルと `data/`、CSV を除外している。
- ログに出すのは件数とトークン数だけ。商品名、ASIN、Keepa の URL（キーを含む）は出さない。
  予期しないエラーも、種類と発生箇所だけを表示する。
- 連携先のプロジェクト ID とアカウント名は Secret で渡し、コードには書かない。
- テストのデータはすべて架空。実際の取得結果をテストやドキュメントに貼らない。
- Firestore は、ログインしていて名簿（`allowed_users`）に載っている人しか読めない。

## テスト

```
pip install -r requirements-dev.txt
python -m pytest -q
```
