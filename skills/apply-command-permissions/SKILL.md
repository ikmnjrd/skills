---
name: apply-command-permissions
description: 監査候補を確認した後、ユーザーが選択した権限ルールを Codex と Claude Code に安全に適用します。Codex の execpolicy ルール、または Claude Code の allow/ask/deny 権限について、適用、追加、削除、置換、移行、ドライラン、検証、ロールバックを依頼された場合に使用します。候補の明示的な選択、ドライランのレビュー、確認 ID、競合の解決、バックアップ、検証、製品ごとの適用が必要です。
---

# コマンド権限の適用

ユーザーが選択した候補を適用計画に変換し、製品ごとにドライランを行い、明示的な確認を得てから、同梱の CLI を呼び出します。
場当たり的なファイル編集でルールを直接適用してはいけません。

## 境界条件

- 一回の書き込み操作につき、一つの製品だけを適用対象にします。
- 以前の監査レポートから選択内容を推測しません。候補 ID、または同等に明示的な一覧を必須とします。
- 実験的な Codex の非シェル権限は適用しません。
- 観測されていない `ask/prompt` と `deny/forbidden` のルールは、ユーザーが明示した方針である場合に許可します。観測されていない `allow` は却下します。
- 未解決の競合、無効な設定、期限切れのドライラン、テスト失敗、Codex の公式検証不足がある場合は停止します。
- 確認、競合、ロールバックの保護機構を回避するために強制フラグを使用してはいけません。

## ワークフロー

### 1. 選択内容を確定する

`ACP-ALLOW-001` など、選択された候補 ID を特定します。
各ルールについて、次の事項を確定します。

- 製品: `codex` または `claude`。
- 操作: `add`、`remove`、または `replace`。
- 判定と正確なパターン。
- Claude のスコープ: `user`、`project`、または `project-local`。
- 出所: `audit-candidate` または `user-policy`。
- 理由と観測状況。
- 一致するケースと一致しないケース。

Codex のスコープはユーザー単位です。
すべての Codex ルールが全プロジェクトに影響することを警告します。
ユーザーがグローバルな影響を明示的に受け入れない限り、プロジェクト固有の Codex の allow ルールを適用しません。

### 2. 計画を作成する

[plan-schema.md](references/plan-schema.md) を読みます。
計画は `/tmp` 配下にモード `0600` で作成し、チャットのトランスクリプトやシークレットを含めません。

重複関係が曖昧な場合:

1. インストール済み製品のルールと、現在の公式な意味仕様を調査します。
2. `/tmp` 配下に一時テストを生成します。
3. 製品公式の評価器を優先します。
4. 関係を `equivalent`、方向付きの `subset`、`overlap`、`disjoint`、または `unresolved` に分類します。
5. ケース、評価器、テストコードのハッシュ、結果のハッシュを計画に記録します。
6. 未解決の場合は停止します。

### 3. ドライランを行う

次を実行します。

```bash
python3 scripts/apply_command_permissions.py dry-run \
  --plan /tmp/apply-command-permissions-plan.json \
  --product codex
```

ドライランでは、次を報告します。

- 対象製品、スコープ、ファイル。
- 現在のハッシュと提案後のハッシュ。
- 追加、削除、置換、変更なしの操作。
- 競合と関係性の根拠。
- 一致ケースと不一致ケースの結果。
- unified diff と、保持される無関係な設定。
- バックアップ名と `confirmation_id`。

報告された阻害要因をすべて解決してから続行します。

### 4. 確認を得る

ドライランの正確な内容をユーザーに提示し、明確な肯定回答を必須とします。

危険を伴う制限緩和の場合は、削除される保護とその影響を別途明示します。
その正確な記述と SHA-256 ハッシュを `strong_confirmation` に格納します。
次の操作では、単なる「適用して」という指示だけでは不十分です。

- deny/forbidden の削除または弱体化。
- ask/prompt から allow への変更。
- ルールの適用範囲の拡大。
- 一括削除。

### 5. 適用する

確認後、同じ計画とドライランの確認 ID を使用して実行します。

```bash
python3 scripts/apply_command_permissions.py apply \
  --plan /tmp/apply-command-permissions-plan.json \
  --product codex \
  --confirmation-id CONFIRMATION_ID
```

CLI は、現在のハッシュ、テスト、確認の証拠、マージ後の内容を再確認します。
バックアップを作成し、アトミックに書き込み、検証を行い、失敗時には自動的にロールバックします。

もう一方の製品への適用は、別のドライランと適用のサイクルでのみ行います。

### 6. 完了処理

成功した場合:

- 変更したファイル、バックアップ ID、検証結果を報告します。
- 一時的な計画を削除します。
- 永続的な記録が `~/workspace/apply-command-permissions-log/{codex|claude}/` 配下に保存されることを明記します。

失敗した場合は計画を残し、そのパスを報告します。

### ロールバック

最近の操作を一覧表示します。

```bash
python3 scripts/apply_command_permissions.py status --product codex
```

現在のファイルハッシュが、選択した操作の適用後ハッシュと一致する場合に限りロールバックします。

```bash
python3 scripts/apply_command_permissions.py rollback \
  --product codex \
  --operation-id OPERATION_ID
```

その後の変更が存在する場合は、代わりに新しい逆操作の計画を作成します。
新しい変更を古いバックアップで強制的に上書きしてはいけません。
