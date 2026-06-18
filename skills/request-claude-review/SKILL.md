---
name: request-claude-review
description: Claude Code CLI の `claude -p` をサンドボックス外で実行し、ユーザーの既存 Claude Code ログインを使って単発レビューを行います。Codex で作業中の差分、直近コミット、コミット範囲、計画、設計、実装方針、PR 相当の変更について、agmsg や常駐セッションを使わず Claude に一度だけレビューさせたい場合、または別モデルの観点でバグ、回帰、テスト不足、設計リスクを確認したい場合に使用します。
---

# Claude への単発レビュー依頼

Claude Code CLI の `claude -p` を使い、単発のレビュー結果を標準出力で受け取ります。
agmsg、`spawn`、常駐 Claude セッション、ターミナル操作は使いません。

## 方針

- `claude -p` はサンドボックス外で実行します。Codex のサンドボックス内では、同じ `HOME` でも Claude Code の OAuth / Keychain 認証を読めず、未ログイン扱いになることがあります。
- ログイン処理は行いません。ユーザーが通常の Claude Code でログイン済みの状態を使います。
- `--bare` は使いません。`--bare` は OAuth / Keychain を読まないため、ユーザーのログイン状態を引き継げません。
- Claude に編集系ツールを許可しません。レビューに必要な読み取りと Git 調査だけを許可します。
- Claude の結果はそのまま採用せず、Codex 側で対象コードや差分と照合します。

## ワークフロー

### 1. CLI と認証を確認する

まず `claude` があるか確認します。

```bash
command -v claude
claude -p --help
```

Codex から実行する場合、認証確認はサンドボックス外で行います。

```bash
claude auth status
```

`loggedIn: false`、`Not logged in`、`Please run /login` が出る場合は、通常の Claude Code 環境でログインが必要だとユーザーに報告して止めます。agmsg や `spawn` へフォールバックしません。

### 2. レビュー対象を決める

ユーザーの指定に合わせて、Claude へ渡す対象を明確にします。

- 作業ツリー: `git status --short`、`git diff --stat`、`git diff --name-only`
- staged diff: `git diff --staged --stat`、`git diff --staged --name-only`
- 直近コミット: `git show --stat --patch HEAD`
- 任意のコミット: `git show --stat --patch <commit>`
- コミット範囲: `git diff --stat <base>..<head>`、`git diff <base>..<head>`
- 設計や計画: ユーザーの説明、関連ファイル、既知の制約

差分が大きい場合は、重要なファイルやリスクの高い範囲を要約してから渡します。

### 3. Claude に渡すプロンプトを作る

Claude には、レビュー対象、観点、制約、出力形式を明示します。Claude は許可された Git / Read / Grep / Glob ツールで追加確認できますが、編集はできません。

```text
あなたはコードレビュー担当です。以下の対象をレビューしてください。

制約:
- ファイルは編集しないでください。
- レビュー結果だけを返してください。
- 指摘は重大度順に並べてください。
- 可能なら file:line を示してください。
- 根拠が弱い推測は「要確認」と明記してください。
- 問題がなければ「重大な指摘なし」と書いてください。

レビュー観点:
- バグ、回帰、境界条件
- テスト不足
- 既存設計との不整合
- セキュリティまたはデータ破壊リスク

対象プロジェクト: <absolute project path>
対象: <working tree / staged diff / HEAD / commit range / plan>
現在の状況: <summary and tests>

レビュー材料:
<diff summary, selected diff, file list, or plan>
```

### 4. `claude -p` をサンドボックス外で実行する

Codex では、ユーザーの既存ログインを使うためにサンドボックス外で実行します。実行前に、ユーザーへ「Claude Code の既存ログインを使って `claude -p` を実行する」ことを示す承認理由を付けます。

標準の実行形:

```bash
claude -p \
  --allowedTools "Bash(git status*)" "Bash(git diff*)" "Bash(git log*)" "Read" "Grep" "Glob" \
  --max-turns 5 \
  --no-session-persistence \
  "<prompt>"
```

長いレビュー材料を渡す場合は、標準入力を使います。

```bash
printf '%s\n' "<prompt>" | claude -p \
  --allowedTools "Bash(git status*)" "Bash(git diff*)" "Bash(git log*)" "Read" "Grep" "Glob" \
  --max-turns 5 \
  --no-session-persistence
```

許可するツールは原則として次に固定します。

```text
Bash(git status*)
Bash(git diff*)
Bash(git log*)
Read
Grep
Glob
```

`Edit`、`Write`、`MultiEdit`、任意の `Bash(*)`、`Bash(git *)`、ネットワーク系ツール、シェル一般実行は許可しません。

### 5. 結果を扱う

Claude の指摘は、対象コードや差分と照合します。
存在しないファイル、古い差分、再現不能な指摘、ユーザーの制約に反する提案は除外または保留します。

ユーザーへの報告では、Claude の指摘と Codex 側で確認した事実を分けます。
修正まで依頼されている場合は、確認できた指摘だけを通常の編集ワークフローで扱います。

`claude -p` が認証、権限、ネットワーク、予算、または CLI エラーで失敗した場合は、コマンドの要点と失敗理由を報告します。失敗時に agmsg や `spawn` へフォールバックしません。
