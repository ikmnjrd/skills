---
name: audit-command-permissions
description: ローカルの Codex と Claude Code のログを監査し、観測されたシェルコマンドを自動承認候補、禁止候補、または引き続き承認を必要とするコマンドに分類します。エージェントによる権限確認の繰り返しを減らしたい場合、決して実行すべきでないコマンドを特定したい場合、過去のコマンド使用状況や操作対象を確認したい場合、またはローカルログから保守的な権限ルール案を生成したい場合に使用します。
---

# コマンド権限の監査

同梱の読み取り専用 CLI を使用して、機密情報をマスキングした監査データを抽出します。
権限設定を変更せずにそのデータを評価し、分類候補を提示します。

## 安全上の境界

- ログ、トランスクリプト、生成された監査データは機密情報として扱います。
- 元ログの内容を変更、削除、移動、アップロード、実行しません。
- シークレット、認証情報、環境変数の完全な値、機密性の高いパスを出力しません。
  CLI によるマスキングを維持します。
- 権限ルールを適用しません。権限の適用は、明示的な依頼を必要とする別の操作です。
- 不確実なものは必ず `require-approval` とし、`auto-approve` にはしません。
- 過去の承認は観測事実としてのみ扱い、安全性の根拠とはみなしません。

## ワークフロー

### 1. 対象範囲を決める

次の事項を決定します。

- 調査する製品: Codex、Claude Code、またはその両方。
- 対象期間とプロジェクトフィルター。
- ユーザーが分類のみを求めているのか、ルール案のスニペットも求めているのか。

指定がない場合は、直近 90 日間について、全プロジェクトを対象に両方の製品を調査します。
実験的な非シェル操作もデフォルトで含めますが、安定版のシェル操作の結果とは分けて扱う必要があります。

### 2. 監査データを生成する

このスキルのディレクトリから、同梱の CLI を実行します。

```bash
python3 scripts/audit_command_permissions.py audit --format json
```

便利なオプション:

```bash
python3 scripts/audit_command_permissions.py audit --since 2026-01-01
python3 scripts/audit_command_permissions.py audit --project my-project
python3 scripts/audit_command_permissions.py audit --all-time
python3 scripts/audit_command_permissions.py audit --shell-only
python3 scripts/audit_command_permissions.py audit --format markdown
```

保存する必要がある場合に限り、`--output PATH` または `--output-dir DIR` を使用します。
作成されるファイルのモードは `0600` です。JSON が正規の監査データであり、Markdown は人が読みやすい形式への投影です。

CLI の代わりに `cat`、未加工の JSONL 出力、場当たり的な広範囲検索を使用しません。
製品のスキーマが未対応の場合は、未加工のログを公開するのではなく、制約を報告してその製品のアダプターを更新します。

### 3. 事実を解釈する

CLI が記録するのは事実と機械的に抽出した特徴であり、安全性の分類ではありません。

- マスキング済みの操作、対象、プロジェクト、タイムスタンプ、匿名化されたソース参照。
- 安定版シェルまたは実験的な非シェルというサポートレベル。
- `denied`、`executed-without-observed-decision`、`requested-only` などの観測結果。
- `network_write`、`filesystem_write`、`recursive_delete`、`privilege_boundary`、`outside_project_path`、`dynamic_expansion` などの特徴。
- 解析と抽出の制約。

`executed-without-observed-decision` を承認済みと解釈してはいけません。
`approved` が明示的に観測された場合も、過去のユーザー行動としてのみ扱います。
安全性が確立されたことにはなりません。

### 4. 分類する

[classification-policy.md](references/classification-policy.md) を読み、次の分類を正確に出力します。

- `auto-approve`: 範囲が狭く、反復可能で、影響が小さく、今後の確認を省略するのに適したシェルコマンド。
- `forbid`: 確認なしでブロックすべきシェルコマンドまたはコマンド形式。
- `require-approval`: 人による確認が必要なコマンド。不確実なものや状況に依存するものをすべて含みます。

実験的な非シェル操作は別のセクションに分けます。
参考分類を付けることはできますが、Codex や Claude Code の権限ルールには変換しません。

過去の承認が示すのは、その状況で以前許容されたという事実であり、安全性ではありません。
頻繁に承認された操作でも、`require-approval` のままにする場合や `forbid` にする場合があります。

### 5. 候補の適用範囲を検証する

提案する各シェルパターンについて、次を行います。

- 一致すべき観測例を示します。
- 一致してはならない類似例を少なくとも二つ示します。
- 複合コマンド、末尾の引数、パス、URL、フラグ、ラッパーを確認します。
- 汎用シェル、インタープリター、パッケージランナー、リモートクライアント、または権限境界を許可するプレフィックスは却下します。
- 一つの広いルールより、複数の狭いルールを優先します。
- 既存ルールと比較し、競合や不必要に広い重複がないか確認します。

製品のルール言語で意図した境界を確実に表現できない場合は、`require-approval` に引き下げます。

### 6. 証拠を再調査する

ユーザーが過去の具体的な事例について質問した場合は、元ログを再走査します。

```bash
python3 scripts/audit_command_permissions.py inspect --command rm
python3 scripts/audit_command_permissions.py inspect --tool apply_patch
python3 scripts/audit_command_permissions.py inspect --feature outside_project_path
python3 scripts/audit_command_permissions.py inspect --target build
```

CLI は、個人用ルートや機密パスをマスキングしたまま、可能な場合はプロジェクト相対の対象を表示します。
ログが削除または移動されている場合は、その事象を再構成できないことを明記します。

### 7. 報告する

冒頭に次を記載します。

- 調査したソースと期間。
- イベント数と正規化されたコマンド形式の数。
- 分類ごとの安定版シェル候補数。
- 別セクションに分けた実験的操作の数。
- 不足している証拠またはスキーマ上の制約。

シェルの各分類について、次の表を提示します。

| 候補 ID | 候補パターン | 観測数 | 結果の根拠 | リスク・影響 | 確信度 | 理由 |
|---|---|---:|---|---|---|---|

レポート内で一貫した ID を割り当てます。

- `ACP-ALLOW-NNN`
- `ACP-FORBID-NNN`
- `ACP-PROMPT-NNN`

ユーザーが後で `apply-command-permissions` を呼び出す際は、これらの ID を使用します。
ID はレポート項目を識別するためだけのものであり、製品設定には書き込みません。

`forbid` には、より安全な代替手段がある場合はそれを含めます。
`require-approval` には、ユーザーが確認すべき具体的な事実を記載します。

頻出するものの、適用範囲が広すぎるか状況依存である操作については、`却下した自動承認案` を追加します。

依頼された場合は、[rule-formats.md](references/rule-formats.md) を読み、インストール済みの製品または最新の公式ドキュメントに照らして構文を検証し、スニペットに `DRAFT - NOT APPLIED` と表示します。

## 品質基準

- すべての候補について、観測されたマスキング済みの例を引用します。
- 承認、実行成功、頻度、実行ファイル名から安全性を推測しません。
- 制約のないシェルテキスト、コード、出力先パス、リモート対象、パッケージのライフサイクルスクリプトを自動承認しません。
- 未加工の抜粋は最小限にし、マスキングを維持します。
