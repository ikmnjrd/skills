# Codex での動作

次を設定します。

```text
AGENT_TYPE=codex
INVOCATION=$agmsg
```

Codex が対応する配信モードは `turn` と `off` です。Monitor ツールはないため、
`monitor` と `both` は拒否されます。

初めて参加した後、ユーザーに次の選択を求めます。

```text
受信メッセージの配信モードを選択してください:

  1) turn - アシスタントの各ターン終了時に受信箱を確認します。
  2) off  - 自動配信を行わず、手動の $agmsg だけを使用します。

[1]:
```

回答を待ちます。空入力の場合は `turn` とします。次のコマンドで適用します。

```bash
python3 "$SKILL_DIR/agmsg.py" delivery set <turn|off> codex "$(pwd)"
```

## ロール

`actas <name>` の場合:

1. 次を実行します。未登録の場合は `--team <team>` を付けます（チームが複数
   ある場合は、どのチームか確認します）。

   ```bash
   python3 "$SKILL_DIR/agmsg.py" actas <name> --project "$(pwd)" --type codex
   ```

2. このセッションの送信者として `<name>` を使用します。
3. Codex には Monitor がないため、受信時は引き続き登録済みの全ロールを
   対象にします。

`drop <name>` の場合は、次を実行します。

```bash
python3 "$SKILL_DIR/agmsg.py" drop <name> --project "$(pwd)" --type codex
```

削除したロールが現在の送信者であれば、送信者の設定を解除します。

## 配信

`mode` の場合は、次の出力を表示します。

```bash
python3 "$SKILL_DIR/agmsg.py" delivery status codex "$(pwd)"
```

`mode turn|off` の場合は、指定されたモードを設定します。
