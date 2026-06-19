# agmsg の編集方針

このディレクトリは、アップストリームの `ikmnjrd/agmsg` をこのリポジトリ向けの
Agent Skill として構成したものです。帰属、取得元、ライセンス、ローカル変更の
記録は `VENDOR.md` を参照してください。

## 文書の責務

- `SKILL.md` には、Codex と Claude Code に共通する指示だけを記載します。
- `SKILL.codex.md` には、Codex 固有の設定と動作だけを記載します。
- `SKILL.claude-code.md` には、Claude Code 固有の設定と動作だけを記載します。
- 共通の指示を環境別ファイルに重複して記載したり、共通指示への参照文を
  追加したりしません。エージェントは最初に `SKILL.md` を読み、その指示に
  従って該当する環境別ファイルも読みます。

## 編集ルール

- 共通動作の変更は `SKILL.md` だけに反映します。
- 環境固有の変更は、該当する環境別ファイルだけに反映します。
- コマンド名、引数、設定値、出力トークンなど、機械的に解釈される文字列は
  翻訳せず保持します。
- vendored スキルへの変更として、内容に応じて `VENDOR.md` と
  `../../vendor/agmsg.lock.json` の `localChanges` を更新します。
- ファイルを追加または削除した場合は、ロックファイルの `includedFiles` も
  更新します。
- 実装の追加や変更は、リポジトリの方針に従ってレビューします。

## 実装

- 実装は Python（標準ライブラリのみ、Python 3.11 以上）で、統合 CLI
  `agmsg.py` と `agmsg_cli/` パッケージ（`platform`/`config`/`storage`/
  `identity`/`locking`/`delivery`/`codex`/`spawn`/`install`/`commands`）で
  構成します。スキル本体にシェルスクリプトは使用しません。
- Codex monitorベータは、Python標準ライブラリだけでstdio JSON-RPCとUnix
  socket上のWebSocketを処理し、`codex app-server`へ接続します。任意のCodex
  shimもPythonとして生成します。
- Codex Desktopのmonitorは、開いているUIへ反映される`Stop` hook fallbackで
  配信します。外部app-serverが作成したturnはsessionファイルへ追記されても
  Desktop UIへライブ表示されないため、Desktopでは外側launcherを通常使用しません。
- メッセージは SQLite（`messages.db`）、設定とチーム登録は JSON です。
- 単体・統合テストは `tests/` にあり、`python3 -m unittest discover -s tests`
  で実行します。

## アップストリームからの主な改変

- 全実装をシェルから Python へ全面移行し、`agmsg.py` 統合 CLI に集約しています。
- 上流のCodex monitor bridgeベータをPythonへ移植し、`watch-once`、
  app-server bridge、outside-sandbox launcher、対話起動shimを統合CLIの
  内部コマンドとして実装しています。
- `SKILL.md`、`SKILL.codex.md`、`SKILL.claude-code.md` の Markdown 文書全体を、
  コマンドや識別子を除いて日本語化しています。
- `turn` モードで他のエージェントの返信が必要なためタスクが停止した場合に、
  30 秒、60 秒、90 秒と待機時間を増やしながら `sleep` 後に受信箱を確認する
  指示を追加しています。待機は最大 2 時間で終了し、返信がなければユーザーへ
  状況を報告します。
