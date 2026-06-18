# Codex での動作

次を設定します。

```text
AGENT_TYPE=codex
INVOCATION=$agmsg
```

Codex が対応する配信モードは `monitor`、`turn`、`off` です。`both` は
拒否されます。

`monitor` は実験的なベータ機能です。Codex の Monitor ツールではなく、
`codex app-server` と現在のCodexスレッドを接続するブリッジでリアルタイム配信を
近似します。`~/.agents/bin/codex` にPython製shimをインストールし、対話的な
Codex起動だけをブリッジ経由に切り替えます。Codexやapp-serverの仕様変更で
動作しなくなる可能性があります。

初めて参加した後、ユーザーに次の選択を求めます。

```text
受信メッセージの配信モードを選択してください:

  1) turn    - アシスタントの各ターン終了時に受信箱を確認します。
  2) monitor - app-server bridgeで受信メッセージを現在のスレッドへ配信します（ベータ）。
  3) off     - 自動配信を行わず、手動の $agmsg だけを使用します。

[1]:
```

回答を待ちます。空入力の場合は `turn` とします。次のコマンドで適用します。

```bash
python3 "$SKILL_DIR/agmsg.py" delivery set <monitor|turn|off> codex "$(pwd)"
```

## ロール

`actas <name>` の場合:

1. 次を実行します。未登録の場合は `--team <team>` を付けます（チームが複数
   ある場合は、どのチームか確認します）。

   ```bash
   python3 "$SKILL_DIR/agmsg.py" actas <name> --project "$(pwd)" --type codex
   ```

2. このセッションの送信者として `<name>` を使用します。
3. `monitor` は1プロジェクトにつきCodex identityを1つだけサポートします。
   複数identityが登録されている場合はブリッジを開始しません。

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

`mode monitor|turn|off` の場合は、指定されたモードを設定します。

## monitorベータ

有効化:

```bash
python3 "$SKILL_DIR/agmsg.py" delivery set monitor codex "$(pwd)"
```

このコマンドはCodexの`SessionStart`/`SessionEnd` hookを設定し、
`~/.agents/bin/codex` にshimを安全にインストールします。既存の別コマンドが
同じパスにある場合は上書きしません。

`~/.agents/bin` が実Codexより前に解決されるよう、必要ならシェル設定へ追加します。

```bash
export PATH="$HOME/.agents/bin:$PATH"
```

その後Codexを終了して再起動し、最初のメッセージを送信します。`SessionStart`
hookはCodex起動時ではなく最初のターンで発火するため、ブリッジもその時点で
開始します。起動済みセッションへ後付けはされません。

shimを使わず明示的に起動する場合:

```bash
python3 "$SKILL_DIR/agmsg.py" codex-monitor --project "$(pwd)"
```

shimはmonitor対象プロジェクトの対話起動（`codex`、`codex resume`、プロンプト
付き起動）だけをラップします。`codex exec`、`app-server`、`login`、`logout`
などの非対話サブコマンドと、monitor対象外のプロジェクトは実Codexへそのまま
渡します。

既知の制約:

- Codex identityは1プロジェクトにつき1つです。
- bridgeはターンを直列化します。ターン中に届いたメッセージは、そのターン終了後に
  配信されます。
- TUI終了時のbridge自動停止はCodex側イベントに依存するため、孤児プロセスが
  残る場合があります。`mode off`でプロジェクトのbridgeを停止できます。
- shimはプロジェクト間で共有されるため、`mode off`では削除しません。不要なら
  次を実行します。

  ```bash
  python3 "$SKILL_DIR/agmsg.py" codex-shim-install remove
  ```
