/**
 * MARKET RADAR 起動タイマー
 *
 * 決まった時刻に、GitHub Actions の取得（collect）を起動します。
 * GitHub の予約実行は数時間遅れたり飛んだりするため、こちらを主な起動手段にしています。
 * 起動されるのは auto ジョブで、その時点で「まだ取得していない回」だけを実行します。
 * 同じ回を二重に起動しても、2 回目は何もせずに終わります。
 *
 * 準備:
 *   1. プロジェクトの設定 → スクリプト プロパティに GITHUB_TOKEN を追加する
 *      （GitHub の Fine-grained token。対象はこのリポジトリだけ、権限は Actions の Read and write だけ）
 *   2. setupTriggers を 1 回実行する（タイマーが登録される）
 */
const REPO = 'ads-hideki/keepa-monitor';
const WORKFLOW = 'collect.yml';

// 起動する時刻（日本時間）。指定した分の前後 15 分以内に動きます。
// 各回の時刻（2 時、10 時、14 時、19 時）を過ぎてから動くよう :15 にし、念のため :45 にもう 1 回起動します。
const TIMES = [[2, 15], [2, 45], [10, 15], [10, 45], [14, 15], [14, 45], [19, 15], [19, 45]];

/** GitHub に取得の実行を指示する。タイマーから呼ばれる。手動で実行してもよい。 */
function runCollect() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('スクリプト プロパティ GITHUB_TOKEN が設定されていません');
  const url = 'https://api.github.com/repos/' + REPO + '/actions/workflows/' + WORKFLOW + '/dispatches';
  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    payload: JSON.stringify({ ref: 'main', inputs: { job: 'auto' } }),
    muteHttpExceptions: true,
  });
  const code = res.getResponseCode();
  if (code !== 204) {
    // 失敗すると、Google から失敗の通知メールが届きます。鍵の期限切れ（401）が主な原因です。
    throw new Error('GitHub への実行指示に失敗しました（' + code + '）: ' + res.getContentText().slice(0, 200));
  }
  console.log('GitHub に実行を指示しました');
}

/** タイマーを登録し直す。時刻（TIMES）を変えたときは、これをもう一度実行する。 */
function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  TIMES.forEach(function (hm) {
    ScriptApp.newTrigger('runCollect').timeBased().inTimezone('Asia/Tokyo')
      .everyDays(1).atHour(hm[0]).nearMinute(hm[1]).create();
  });
  console.log('タイマーを ' + TIMES.length + ' 件登録しました');
}
