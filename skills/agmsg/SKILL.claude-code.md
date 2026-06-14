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
python3 "$SKILL_DIR/agmsg.py" delivery set <mode> claude-code "$(pwd)"
```

`delivery` が出力するすべての `AGMSG-DIRECTIVE` に従います。

モードが `monitor` または `both` の場合、コマンドを処理する前に
`agmsg inbox stream` Monitor が実行中であることを確認します。次の指定で
起動します（`command` は `delivery`／`session-start` が出力する行をそのまま使います）。

```text
command: python3 "$SKILL_DIR/agmsg.py" watch "$CLAUDE_CODE_SESSION_ID" "$(pwd)" claude-code
description: agmsg inbox stream
persistent: true
```

## ロール

`actas <name>` の場合:

1. 次のコマンドでロールを確保します（`$CLAUDE_CODE_SESSION_ID` を使用）。

   ```bash
   CLAUDE_CODE_SESSION_ID="$CLAUDE_CODE_SESSION_ID" \
     python3 "$SKILL_DIR/agmsg.py" actas <name> --project "$(pwd)" --type claude-code
   ```

   そのロールが未登録の場合は `--team <team>` を付けて参加と確保を同時に行います。
2. 出力が `status=held` の場合は中止し、所有しているセッションを報告します。
3. 既存の `agmsg inbox stream` Monitor があれば停止します。タスク ID を
   推測してはいけません。
4. 出力された `AGMSG-DIRECTIVE` に従い、`<name>` で絞り込んだ永続 Monitor を
   起動します（`watch` の第 4 引数が `<name>`）。
5. `<name>` を送信者として使用し、そのロール宛てのメッセージだけを受信します。

`drop <name>` の場合:

1. 次を実行します。

   ```bash
   CLAUDE_CODE_SESSION_ID="$CLAUDE_CODE_SESSION_ID" \
     python3 "$SKILL_DIR/agmsg.py" drop <name> --project "$(pwd)" --type claude-code
   ```

2. 現在の agmsg Monitor があれば停止します。
3. 出力された `AGMSG-DIRECTIVE` に従い、フィルターなしの既定 Monitor を
   再起動します。
4. 削除したロールが現在の送信者であれば、送信者の設定を解除します。

## 配信

`mode` の場合は、次の出力を表示します。

```bash
python3 "$SKILL_DIR/agmsg.py" delivery status claude-code "$(pwd)"
```

`mode <name>` の場合は、そのモードを設定して出力された指示に従います。
