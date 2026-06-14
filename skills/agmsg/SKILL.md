---
name: agmsg
description: 共有ローカル SQLite データベースを介して、Codex と Claude Code のセッション間でメッセージを送受信します。エージェント間の連携、受信箱の確認、チームへの所属、メッセージ履歴、ロールの切り替え、配信モード、別エージェントの起動に使用します。
license: MIT
compatibility: bash と sqlite3 が必要です。Codex と Claude Code に対応しています。
---

# エージェント間メッセージング

すべての操作には同梱のスクリプトを使用します。データベース、チームファイル、
ランタイムファイル、フック設定を直接読み書きしてはいけません。

## 初期セットアップ

`SKILL_DIR` に、このファイルがあるディレクトリを設定します。

`$SKILL_DIR/runtime-path` がない場合は、次を実行します。

```bash
bash "$SKILL_DIR/install.sh"
```

インストーラーは skills リポジトリを特定し、Git 管理対象外の `.agmsg/`
ディレクトリを初期化してランタイムパスを記録し、必要に応じて Codex の
サンドボックスを設定します。初期セットアップに失敗した場合は、エラーを
そのまま報告して処理を停止します。

## 環境

現在のエージェントが Codex と Claude Code のどちらかを判定します。

- Codex: 続行する前に `SKILL.codex.md` を読みます。
- Claude Code: 続行する前に `SKILL.claude-code.md` を読みます。
- 環境を判定できない場合は、推測せずユーザーに確認します。

環境別ファイルには、`AGENT_TYPE`、呼び出し構文、配信モード、環境固有の
`actas` の動作が定義されています。

## ID

次を実行します。

```bash
"$SKILL_DIR/scripts/whoami.sh" "$(pwd)" "$AGENT_TYPE"
```

出力に応じて処理します。

- `agent=... teams=...`: このセッションで使用する ID として記憶します。
- `multiple=true ...`: 一覧のうち、どの ID を使用するか確認します。
- `not_joined=true ...`: 利用可能なチームを表示し、チーム名とエージェント名を
  1 つずつ確認します。次のコマンドで参加します。

  ```bash
  "$SKILL_DIR/scripts/join.sh" <team> <agent> "$AGENT_TYPE" "$(pwd)"
  ```

  その後、環境別ファイルにある初回実行時の配信モード設定に従い、新しい
  受信箱を確認します。
- `suggest=true ...`: 同じ種類の既存名を提示して再利用するか確認し、チームを
  確認してから `join.sh` を実行します。

存在しない `register.sh` コマンドを作ったり使用したりしてはいけません。

## コマンド

引数がない場合は、すぐにすべてのチームの受信箱を確認します。

```bash
"$SKILL_DIR/scripts/inbox.sh" <team> <agent>
```

最初に何をするか確認してはいけません。受信したメッセージに応じて適切に
対応します。返信には次を使用します。

```bash
"$SKILL_DIR/scripts/send.sh" <team> <from-agent> <to-agent> "<message>"
```

その他の操作:

```bash
"$SKILL_DIR/scripts/history.sh" <team> [agent]
"$SKILL_DIR/scripts/team.sh" <team>
"$SKILL_DIR/scripts/config.sh" show
"$SKILL_DIR/scripts/config.sh" set <key> <value>
"$SKILL_DIR/scripts/reset.sh" "$(pwd)" "$AGENT_TYPE" [agent] [session-id]
"$SKILL_DIR/scripts/spawn.sh" <claude-code|codex> <name> --project "$(pwd)" [options]
```

`send` では、スクリプトを実行する前に受信者が所属するチームを特定します。
メッセージは引用符で囲み、1 つのシェル引数として渡します。

`spawn` では、指定された場合に `--team`、`--window`、`--split`、
`--terminal` オプションをそのまま渡します。スクリプトの出力を表示します。
起動対象は別セッションであり、現在のセッションの受信処理を再起動しては
いけません。

## turn モードで返信を待つ

`turn` モードで、他のエージェントからの返信がないとタスクを進められない
状態になった場合は、その時点でユーザーへ処理を返さず、`sleep` と
`inbox.sh` を使って返信を待ちます。

1. 最初に 30 秒 `sleep` してから、返信元エージェントが所属するチームの
   受信箱を確認します。
2. 新しいメッセージがなければ、次は 60 秒、その次は 90 秒というように、
   待機時間を毎回 30 秒ずつ増やして受信箱を再確認します。
3. メッセージを受信したら待機を終了し、内容に応じてタスクを続行します。
4. 待機開始からの合計時間が 2 時間を超えないようにします。次の `sleep` で
   2 時間を超える場合は、残り時間だけ待機して最後に受信箱を確認します。
5. 2 時間待っても返信がない場合は待機を終了し、待っている相手、返信が必要な
   理由、現在停止している作業をユーザーに報告します。

各確認には次を使用します。データベースを直接問い合わせてはいけません。

```bash
sleep <seconds>
"$SKILL_DIR/scripts/inbox.sh" <team> <agent>
```

`actas`、`drop`、配信 `mode`、従来の `hook on|off` の動作については、
環境別ファイルに従います。
