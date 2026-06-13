# ikeda-agent-skills

GitHub Copilot / コーディングエージェント向けに個人で厳選したエージェントスキル集です。

## 収録スキル

- `grill-me` — エージェントが焦点を絞った質問を一つずつ行い、計画や設計を厳しく検証します。
- `grill-with-docs` — プロジェクト内の用語や意思決定と照らして計画を厳しく検証し、必要に応じて `CONTEXT.md` や ADR を更新します。
- `audit-command-permissions` — Codex と Claude Code のログを監査し、許可、確認、拒否に関する保守的なコマンドルールを提案します。オリジナルスキルです。
- `apply-command-permissions` — 選択した Codex と Claude Code の権限ルールについて、ドライラン、検証、適用、バックアップ、ロールバックを行います。オリジナルスキルです。
- `empirical-prompt-tuning` — 独立した実行者と両面評価を使い、エージェント向け指示を反復的に改善します。
- `extract-glossary` — リポジトリ群から用語集、実装マップ、技術構成、オンボーディング向け Mermaid 図を生成します。

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
  empirical-prompt-tuning/
    SKILL.md
    SKILL-ja.md
    VENDOR.md
  extract-glossary/
    SKILL.md
    VENDOR.md
LICENSES/
  mattpocock-skills-LICENSE
  mizchi-skills-LICENSE-NOTICE
vendor/
  mattpocock-skills.lock.json
  mizchi-skills.lock.json
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

`empirical-prompt-tuning` と `extract-glossary` は mizchi の
`mizchi/skills` リポジトリから取り込んだものです。

元のリポジトリ:
https://github.com/mizchi/skills

原作者:
mizchi (Kotaro Chikuba)

ライセンス:
MIT（個別ライセンスがない skill に対するアップストリーム README の既定）

アップストリームには専用ライセンスファイルがないため、そのライセンス宣言を
`LICENSES/mizchi-skills-LICENSE-NOTICE` に記録しています。

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

オリジナルスキルには、ロックエントリや `VENDOR.md` を追加しません。

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

複数のスキルだけを検証する場合は、対象を位置引数で指定します。スキル名、
`skills/` から始まるディレクトリ、またはその配下のファイルパスを指定できます。
同じスキルを複数回指定しても、一度だけ検証されます。

```sh
bash scripts/validate-skills.sh grill-me skills/grill-with-docs
bash scripts/validate-skills.sh skills/grill-me/SKILL.md skills/grill-with-docs/SKILL.md
```

バリデーターは、スキルが少なくとも一つ存在すること、必要なファイルが揃っていること、`SKILL.md` に必須のフロントマターがあることを確認します。

### Git hook

コミット前に、ステージされている変更に含まれるスキルだけを検証する
`pre-commit` hook を利用できます。次のコマンドで、このリポジトリに対して有効化します。

```sh
git config core.hooksPath .githooks
```

hook は Git index の内容を一時ディレクトリに展開するため、ステージされていない変更は
検証に含まれません。スキルディレクトリ全体の削除は検証対象から除外されます。

## スキルの同期

`scripts/sync-skills.sh` は、ローカルの `skills/` を期待するスキル一覧、
GitHub の `ikmnjrd/skills` をインストール元として、対象環境を同期します。
全スキルを同じ default branch のコミットから `--force` で再インストールし、
インストールがすべて成功した後で、正本に存在しないスキルを削除します。

引数なしでは Codex と Claude Code の user scope を同期します。

```sh
scripts/sync-skills.sh
```

変更内容だけを確認する場合:

```sh
scripts/sync-skills.sh --dry-run
```

対象 agent は `--agent` を繰り返して指定できます。現在対応している値は
`codex` と `claude-code` です。

```sh
scripts/sync-skills.sh --agent codex
scripts/sync-skills.sh --agent codex --agent claude-code
```

project scope は、コマンドを実行した Git リポジトリを同期対象にします。

```sh
/path/to/skills/scripts/sync-skills.sh --scope project
```

同期結果は、インストールまたは削除したスキルごとに一行ずつ標準出力へ
表示されます。

```text
Installed: codex/grill-me
Uninstalled: codex/old-skill
```

GitHub CLI の実行中は stderr にスピナーを表示します。TTY 以外では開始と終了の
メッセージだけを表示するため、標準出力の結果はそのまま処理できます。

インストールが一件でも失敗した場合は余剰スキルを削除せず、終了コード `1`
を返します。

## 手動での導入方法

必要なスキルディレクトリを、対象リポジトリの `.github/skills/` ディレクトリにコピーします。

```sh
mkdir -p .github/skills
cp -R skills/grill-me .github/skills/grill-me
cp -R skills/grill-with-docs .github/skills/grill-with-docs
cp -R skills/empirical-prompt-tuning .github/skills/empirical-prompt-tuning
cp -R skills/extract-glossary .github/skills/extract-glossary
```

または、上記の同期スクリプトを使用します。
