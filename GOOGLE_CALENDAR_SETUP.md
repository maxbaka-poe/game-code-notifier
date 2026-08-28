# Googleカレンダー版イベントカレンダー設定

原神・崩壊：スターレイル・ゼンレスゾーンゼロ・アークナイツ：エンドフィールドのイベントを、GitHub Actionsで取得して購読用カレンダーとして公開します。

エンドフィールドとHoYoverseは混ぜず、次のカレンダーを作成します。

- `hoyoverse.ics`：HoYoverse 3作品まとめ
- `endfield.ics`：アークナイツ：エンドフィールド
- `genshin.ics`：原神
- `starrail.ics`：崩壊：スターレイル
- `zenless.ics`：ゼンレスゾーンゼロ

4作品全部を混ぜた `all.ics` は作成しません。

イベント、期間限定コンテンツ、祈願・跳躍・変調など、開始日時と終了日時が取得できた予定が入ります。

## 1. GitHubへ必要ファイルを追加

既存のコード通知リポジトリに、次のファイルを追加してください。

```text
generate_calendars.py
.github/workflows/publish-event-calendars.yml
.github/heartbeat.txt
```

更新版ZIPを丸ごとアップロードする場合は、既存ファイルを上書きして構いません。Discord WebhookのURLはGitHub Secretに入っているため、ファイルを上書きしても消えません。

## 2. Actionsの書き込み権限を確認

1. GitHubリポジトリの `Settings` を開く。
2. `Actions` → `General` を開く。
3. 下部の `Workflow permissions` で `Read and write permissions` を選ぶ。
4. `Save` を押す。

月1回のハートビートをコミットするために必要です。

## 3. GitHub Pagesを有効化

1. `Settings` → `Pages` を開く。
2. `Build and deployment` の `Source` で `GitHub Actions` を選ぶ。
3. それ以外のテーマやブランチ設定は不要です。

## 4. 初回実行

1. リポジトリ上部の `Actions` を開く。
2. 左側から `Publish game event calendars` を選ぶ。
3. `Run workflow` → `Run workflow` を押す。
4. 緑色のチェックが付くまで待つ。
5. 実行結果の `deploy` を開き、`Deploy GitHub Pages` に表示されるURLを開く。

公開URLは通常、次の形式です。

```text
https://GitHubユーザー名.github.io/リポジトリ名/
```

例としてユーザー名が `sample-user`、リポジトリ名が `game-code-notifier` の場合：

```text
https://sample-user.github.io/game-code-notifier/
```

## 5. Googleカレンダーで購読

GoogleカレンダーのWeb版を使用します。

1. Googleカレンダーを開く。
2. 左側の `他のカレンダー` の横にある `＋` を押す。
3. `URLで追加` を選ぶ。
4. 購読したいICSの完全なURLを貼る。
5. `カレンダーを追加` を押す。

HoYoverse 3作品まとめ：

```text
https://GitHubユーザー名.github.io/リポジトリ名/hoyoverse.ics
```

エンドフィールド：

```text
https://GitHubユーザー名.github.io/リポジトリ名/endfield.ics
```

HoYoverse内でもゲーム別に色を変えたい場合は、`hoyoverse.ics` の代わりに次の3本をそれぞれ追加してください。エンドフィールドは上記の `endfield.ics` を使用します。

```text
https://GitHubユーザー名.github.io/リポジトリ名/genshin.ics
https://GitHubユーザー名.github.io/リポジトリ名/starrail.ics
https://GitHubユーザー名.github.io/リポジトリ名/zenless.ics
```

追加後、Googleカレンダー左側のカレンダー名にあるメニューから色を変更できます。

重要：ICSファイルをダウンロードして「インポート」するのではなく、必ず `URLで追加` を使ってください。インポートではその後の変更が自動反映されません。

## 6. 通知を設定

購読したカレンダーのメニューから `設定` を開き、終日イベントまたは予定の通知を設定します。

おすすめ例：

- 3日前
- 1日前
- 3時間前

外部ICSカレンダーの再取得タイミングはGoogle側が決めるため、GitHub側の更新直後には反映されないことがあります。イベント予定用途を想定しており、即時通知用途にはDiscordコードチェッカーを使ってください。

## 自動実行内容

- 6時間ごと：イベント取得、ICS生成、GitHub Pages更新
- 毎月1日 12:41ごろ（日本時間）：ハートビートファイルを更新してコミット
- 手動実行：Actionsの `Publish game event calendars` からいつでも可能

GitHub Actionsは混雑により開始が遅れる場合があります。

## 公開範囲とキー

カレンダーとGitHub Pagesには、公開されているゲームイベント情報だけが入ります。Googleアカウントのキーや認証情報は使用しません。

Discord Webhook URLは引き続きGitHub Actionsの `DISCORD_WEBHOOK_URL` Secretだけに保存してください。ICSやソースコードには書かないでください。

## 情報源

- 原神・スタレ・ゼンゼロ：HoYoverse Calendar API（日本語）
- エンドフィールド：Game8のイベントスケジュール一覧

情報源のページ構造変更や一時停止を検出した場合、古い・空のカレンダーを公開せずActionsを失敗させます。Actionsの赤い失敗表示からエラー内容を確認できます。
