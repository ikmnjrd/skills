# Scripts

このディレクトリには、スキルの検証、削除、同期、E2E テスト用コマンドがあります。

## validate-skills.sh

スキルと vendor lock ファイルを検証します。実行には `jq` が必要です。

すべてのスキルを検証:

```sh
bash scripts/validate-skills.sh
```

対象を限定:

```sh
bash scripts/validate-skills.sh grill-me skills/grill-with-docs
bash scripts/validate-skills.sh skills/grill-me/SKILL.md
```

対象にはスキル名、`skills/` から始まるディレクトリ、またはその配下のファイルを
指定できます。同じスキルを複数回指定しても一度だけ検証されます。

バリデーターは、スキルの存在、必要なファイル、`SKILL.md` の必須フロントマター、
vendor lock ファイルの JSON を確認します。

### Git hook

ステージされている変更に含まれるスキルをコミット前に検証できます。

```sh
git config core.hooksPath .githooks
```

hook は Git index の内容を一時ディレクトリに展開します。ステージされていない
変更は検証に含まれず、スキルディレクトリ全体の削除は検証対象外です。

## remove-skill.sh

スキルディレクトリ、README の **収録スキル** 一覧、関連する vendor lock
エントリをまとめて削除し、残ったスキルを検証します。

```sh
scripts/remove-skill.sh grill-me
```

変更内容だけを確認:

```sh
scripts/remove-skill.sh --dry-run grill-me
```

同じ upstream の vendored スキルがなくなった場合は、`NOTICE.md` の帰属表示と
`LICENSES/` のライセンスファイルをレビューするよう表示します。帰属情報は共有
される場合があるため、このスクリプトでは自動削除しません。

## sync-skills.sh

リポジトリの `skills/` を正本として、Codex と Claude Code のインストール済み
スキルを同期します。GitHub CLI の `gh` が必要です。

Codex と Claude Code の user scope を同期:

```sh
scripts/sync-skills.sh
```

変更内容だけを確認:

```sh
scripts/sync-skills.sh --dry-run
```

対象 agent を限定:

```sh
scripts/sync-skills.sh --agent codex
scripts/sync-skills.sh --agent codex --agent claude-code
```

コマンドを実行した Git リポジトリの project scope を同期:

```sh
/path/to/skills/scripts/sync-skills.sh --scope project
```

全スキルを同じ default branch のコミットから再インストールし、すべて成功した
後で正本に存在しないスキルを削除します。一件でもインストールに失敗した場合は
削除を行わず、終了コード `1` を返します。

`agmsg` の同期後は、各インストール先の `install.sh` を実行して、この
リポジトリ直下の Git 管理対象外 `.agmsg/` を初期化し、各 skill コピーへ
`runtime-path` を記録します。このセットアップに失敗した場合も同期全体を失敗
扱いにし、スキル削除は行いません。

## test-skill.sh

実モデルを使い、Codex と Claude Code の非対話 CLI における明示的なスキル
呼び出しと、親スキルから子スキルへの入れ子呼び出しを検証します。通常の同期や
CI からは実行されません。

両エージェントをテスト:

```sh
scripts/test-skill.sh
```

対象 agent を限定:

```sh
scripts/test-skill.sh --agent codex
scripts/test-skill.sh --agent claude-code
```

Codex では `$skill-name`、Claude Code では `/skill-name` で子スキルを明示的に
呼び出します。成功した場合だけ、親スキルが意図的な誤答を返す子スキルを使用し、
3回レビューして打ち切る入れ子テストを実行します。

テスト fixture は `tests/e2e/fixtures/skills/` にあり、配布対象の `skills/` には
含まれません。実行時だけ `.test-tmp/skill-nesting/<run-id>/` にコピーされ、
ユーザー領域のスキルは変更しません。一時環境は終了時に削除されます。

タイムアウトとモデルは環境変数で上書きできます。

```sh
SKILL_E2E_TIMEOUT=180 \
CODEX_E2E_MODEL=<model> \
CLAUDE_E2E_MODEL=<model> \
scripts/test-skill.sh
```

タイムアウトの既定値は各 CLI 呼び出しにつき120秒です。成功時はログを削除し、
失敗時は構造化出力、標準エラー、抽出した最終回答を
`.test-artifacts/skill-nesting/<run-id>/` に保持します。
