# Claude Code での動作

次を設定します。

```text
AGENT_TYPE=claude-code
INVOCATION=/agmsg
```

Claude Code は `monitor`、`turn`、`both`、`off` に対応します。

初めて参加した後、ユーザーに次の選択を求めます。

```text
受信メッセージの配信モードを選択してください:

  1) monitor - Monitor ツールを通じてリアルタイムにプッシュします。推奨。
  2) turn    - アシスタントの各ターン終了時に受信箱を確認します。
  3) both    - Monitor を優先し、turn をフォールバックにします。
  4) off     - 自動配信を行わず、手動の /agmsg だけを使用します。

[1]:
```

回答を待ちます。空入力の場合は `monitor` とします。次のコマンドで適用します。

```bash
"$SKILL_DIR/scripts/delivery.sh" set <mode> claude-code "$(pwd)"
```

`delivery.sh` が出力するすべての `AGMSG-DIRECTIVE` に従います。

モードが `monitor` または `both` の場合、コマンドを処理する前に
`agmsg inbox stream` Monitor が実行中であることを確認します。次の指定で
起動します。

```text
command: "$SKILL_DIR/scripts/watch.sh" "$CLAUDE_CODE_SESSION_ID" "$(pwd)" claude-code
description: agmsg inbox stream
persistent: true
```

## ロール

`actas <name>` の場合:

1. `identities.sh "$(pwd)" claude-code` で確認します。
2. 存在しない場合は、現在のチームにそのロールを参加させます。必要であれば
   チームを確認します。
3. 次のコマンドでロールを確保します。

   ```bash
   "$SKILL_DIR/scripts/actas-claim.sh" "$(pwd)" claude-code <name> "$CLAUDE_CODE_SESSION_ID"
   ```

4. `status=held` の場合は中止し、所有しているセッションを報告します。
5. 既存の `agmsg inbox stream` Monitor があれば停止します。タスク ID を
   推測してはいけません。
6. `<name>` を `watch.sh` の第 4 引数に指定し、永続 Monitor を起動します。
7. `<name>` を送信者として使用し、そのロール宛てのメッセージだけを受信します。

`drop <name>` の場合:

1. 次を実行します。

   ```bash
   "$SKILL_DIR/scripts/reset.sh" "$(pwd)" claude-code <name> "$CLAUDE_CODE_SESSION_ID"
   ```

2. 現在の agmsg Monitor があれば停止します。
3. フィルターなしの既定 Monitor を再起動します。
4. 削除したロールが現在の送信者であれば、送信者の設定を解除します。

## 配信

`mode` の場合は、`delivery.sh status` の出力を表示します。`mode <name>` の
場合は、そのモードを設定して出力された指示に従います。`hook on` は `turn`、
`hook off` は `off` として扱います。
