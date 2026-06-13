# ikeda-agent-skills

GitHub Copilot / コーディングエージェント向けに個人で厳選したエージェントスキル集です。

## 収録スキル

- `grill-me` — エージェントが焦点を絞った質問を一つずつ行い、計画や設計を厳しく検証します。
- `grill-with-docs` — プロジェクト内の用語や意思決定と照らして計画を厳しく検証し、必要に応じて `CONTEXT.md` や ADR を更新します。
- `summarize-changes` — コード変更、影響、検証結果、残存リスクを要約します。オリジナルスキルです。
- `audit-command-permissions` — Codex と Claude Code のログを監査し、許可、確認、拒否に関する保守的なコマンドルールを提案します。オリジナルスキルです。
- `apply-command-permissions` — 選択した Codex と Claude Code の権限ルールについて、ドライラン、検証、適用、バックアップ、ロールバックを行います。オリジナルスキルです。

## ディレクトリ構成

```text
skills/
  grill-me/
    SKILL.md
    VENDOR.md
  grill-with-docs/
    SKILL.md
    CONTEXT-FORMAT.md
    ADR-FORMAT.md
    VENDOR.md
  summarize-changes/
    SKILL.md
    agents/
      openai.yaml
  audit-command-permissions/
    SKILL.md
    scripts/
      audit_command_permissions.py
      permission_audit/
      tests/
  apply-command-permissions/
    SKILL.md
    scripts/
      apply_command_permissions.py
      permission_apply/
      tests/
LICENSES/
  mattpocock-skills-LICENSE
vendor/
  mattpocock-skills.lock.json
```

## 帰属表示

初期スキルは Matt Pocock の `mattpocock/skills` リポジトリから取り込んだものです。

元のリポジトリ:
https://github.com/mattpocock/skills

原作者:
Matt Pocock

ライセンス:
MIT

アップストリームのライセンス本文は `LICENSES/mattpocock-skills-LICENSE` に保持しています。

ローカルでの変更内容は、各 vendored スキルの `VENDOR.md` に記録しています。

## 方針

- アップストリームのスキルを記録なしに書き換えません。
- vendored スキルへのローカル変更は `VENDOR.md` に記録する必要があります。
- スクリプトを含むスキルは、使用前にレビューする必要があります。
- vendored スキルは、可能な限りアップストリームのコミットで固定します。

## スキルの保守

`skills/` 配下の各ディレクトリには、次のファイルが必要です。

- 空でない `name` と `description` フィールドを YAML フロントマターに持つ `SKILL.md`。

vendored スキルには、取得元とローカル変更を説明する `VENDOR.md` も必要です。オリジナルスキルには `VENDOR.md` は不要です。

追加のドキュメントやリソースはスキルディレクトリ内に配置してください。スキルディレクトリは小さく、目的を絞った状態に保ちます。

### スキルの追加

1. `skills/<skill-name>/SKILL.md` を作成します。
2. 上記の **収録スキル** 一覧にスキルを追加します。
3. vendored スキルの場合:
   - `skills/<skill-name>/VENDOR.md` を追加します。
   - アップストリームの帰属表示とライセンスを保持します。
   - アップストリームのライセンスファイルを `LICENSES/` 配下に追加するか、既存のものを再利用します。
   - `vendor/` 配下の適切なロックファイルにエントリを追加します。
   - `importedRef` をアップストリームの完全なコミット SHA に固定し、`retrievedAt` を記録します。
   - スキルに `SKILL.md` 以外のファイルが含まれる場合、取り込んだアップストリームの全ファイルをロックエントリに列挙します。
4. vendored スキルに実行可能スクリプトを追加する前にレビューします。
5. 下記の検証コマンドを実行します。

オリジナルスキルには、ロックエントリや `VENDOR.md` を追加しません。`summarize-changes` ディレクトリが最小構成の例です。

### vendored スキルの更新

1. 新しいアップストリームの完全なコミット SHA を特定します。
2. 各 vendored ファイルを、そのコミット時点のファイルと比較します。
3. 意図的なローカル調整を失わないように、アップストリームの変更を反映します。
4. スキルの `VENDOR.md` に新しいコミット、取得日、ローカル変更の正確な要約を記載します。
5. `vendor/` 配下の対応するロックエントリを更新します。
6. 既存のアップストリームのライセンスファイルは変更せず保持します。
7. 下記の検証コマンドを実行し、最終的な差分をレビューします。

### ローカル変更

アップストリームから更新せずに vendored スキルを変更する場合:

1. 目的を絞り、可能な限り小さな変更にします。
2. スキルの `VENDOR.md` とロックエントリの `localChanges` フィールドを更新し、変更内容を正確に記述します。
3. レビューなしで実行可能スクリプトを追加しません。
4. 下記の検証コマンドを実行します。

### スキルの削除

1. `skills/` 配下から対象ディレクトリを削除します。
2. **収録スキル** 一覧から削除します。
3. `vendor/` 配下の関連するロックファイルからエントリを削除します。
4. 残っているどのスキルにも適用されなくなった場合に限り、`NOTICE.md` から帰属表示を削除します。
5. 残っているどのスキルも使用していない場合に限り、アップストリームのライセンスファイルを削除します。
6. 下記の検証コマンドを実行します。

### 検証

検証には `jq` が必要です。追加、更新、削除のたびに次のコマンドを実行します。

```sh
bash scripts/validate-skills.sh
```

バリデーターは、スキルが少なくとも一つ存在すること、必要なファイルが揃っていること、`SKILL.md` に必須のフロントマターがあることを確認します。

## プロジェクトへの推奨導入方法

必要なスキルディレクトリを、対象リポジトリの `.github/skills/` ディレクトリにコピーします。

```sh
mkdir -p .github/skills
cp -R skills/grill-me .github/skills/grill-me
cp -R skills/grill-with-docs .github/skills/grill-with-docs
cp -R skills/summarize-changes .github/skills/summarize-changes
```

または、このリポジトリを中央管理元として保持し、任意の同期スクリプトを使用します。
