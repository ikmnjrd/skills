---
name: nixos-local
description: nixos.local を使ったリモート開発の知識と手順。ローカルの Git worktree を `remote-dev` で nixos.local へ同期し、SSH 先でサーバー起動・テスト・ビルドを実行するワークフローを扱う。Use when the task involves nixos.local, the nixos-remote-dev SSH host, the remote-dev command, syncing a worktree to NixOS, running servers or tests on the remote host, or troubleshooting SSH keys, mDNS resolution, or rsync sync paths for this workflow.
---

# nixos.local 開発

このスキルは、ローカルの Git worktree を `nixos.local` 上の実行コピーへ同期して開発するワークフローを扱う。

役割分担は一点に尽きる。
**編集はローカル、実行は NixOS 側。**

ローカルの worktree が正本である。
ファイルの編集と Git 操作はこのマシン上で行い、NixOS 側の同期先では行わない。
テスト、ビルド、サーバー起動、`docker compose`、`nix develop` は NixOS 側の同期先で実行する。
実行環境(Docker、Nix)は NixOS 側にあるため、これらをローカルで実行しない。
ローカルには nix や direnv を導入しない(マシンリソース節約の方針)。
実行環境の確認や再現もローカルで試みず、SSH 先で行う。

`remote-dev` はユーザーコマンドとして登録済みであり、初期設定は完了している前提で進めてよい。
コマンドが見つからない、または SSH 接続に失敗する場合だけ、[references/remote-dev.md](references/remote-dev.md) のセットアップとトラブルシュートを読む。

## 基本ループ

1. ローカルの worktree でファイルを編集する。
2. worktree 内で `remote-dev` を実行し、NixOS 側へ同期する。
3. 初回同期後とロックファイル変更後だけ、SSH 先で依存をインストールする(後述)。
4. SSH 先の同期先ディレクトリでコマンドを実行する。

`remote-dev` は成功時に同期先パスを表示する。

```text
Synced to nixos-remote-dev:~/workspace/remote-dev/<host>/<repo>/<branch>
ssh nixos-remote-dev
cd ~/workspace/remote-dev/<host>/<repo>/<branch>
```

SSH 先での実行は、表示されたパスを使って 1 コマンドにまとめる。

```sh
remote-dev
ssh nixos-remote-dev 'cd ~/workspace/remote-dev/<host>/<repo>/<branch> && <テストやビルドのコマンド>'
```

同期先パスは自分で組み立てず、`remote-dev` の出力から取る。
`<host>`、`<repo>`、`<branch>` は小文字化と正規化を経るため、手元の名前と一致しない場合がある。

編集のたびにこのループを回す。
同期は rsync の差分転送なので、繰り返し実行してよい。

## SSH 先の実行環境への入り方

SSH 先の素の PATH には、node などプロジェクトのツールチェーンが無いことがある。
プロジェクトが direnv(`.envrc` の `use flake`)で環境を作っている場合、非対話 SSH では direnv が発火しない。
`.envrc` の `use flake` 行から flake 参照を取り、`nix develop <flake参照> --command` でコマンドをラップする。

```sh
# .envrc が `use flake path:./nix` のプロジェクトの場合
ssh nixos-remote-dev 'cd <同期先> && nix develop path:./nix --command yarn workspace <pkg> test'
```

## 依存インストール

`node_modules` は同期されないため、依存は SSH 先でインストールする。
ただし毎回ではない。
同期先に `node_modules` が既にあり、ロックファイルが変わっていなければ、そのまま使う。
インストールするのは初回同期後とロックファイル変更後だけである。

インストールには `--frozen-lockfile` を付ける(`yarn install --frozen-lockfile`。npm なら `npm ci`)。
ロックファイルの正本はローカルにあり、SSH 先で書き換わると正本と食い違ったうえ、次回同期で失われる。

## 実行先の判断規則

- ファイル編集、`git add` や `git commit` などの Git 操作：ローカル。
- テスト、ビルド、サーバー起動、`docker compose`、`nix develop`：SSH 先の同期先。
- サーバーなど長時間動くプロセスは、`docker compose up -d` のようにデタッチで起動する。
- NixOS 側だけに置きたい一時ファイルは、同期先の `.remote-dev-local/` に置く。

## 同期の性質

- 同期は `rsync --delete` で行う。NixOS 側だけにある通常ファイルは削除される(`.remote-dev-local/` は除外されるため残る)。
- NixOS 側での編集は次回同期で失われる。編集してしまった場合は、同期前にローカルへ回収する。
- `.env` や `.env.local` のような Git 管理外ファイルも同期される。同期してはいけない秘密情報がないか、初回同期の前に確認する。
- `node_modules`、`.direnv`、`result`、`dist`、`build` などのビルド成果物は同期されない。全リストは [references/remote-dev.md](references/remote-dev.md) にある。
- detached HEAD では同期できない。ブランチをチェックアウトしてから実行する。
- SSH 接続先は既定で `nixos-remote-dev` であり、`REMOTE_DEV_SSH_TARGET` で上書きできる。

## remote-dev 本体の変更

`remote-dev` の実装と SSH 設定は `~/workspace/dotfiles` で管理している。

- 実装：`bin/remote-dev`
- SSH 設定：`ssh/config.d/nixos-remote-dev`
- テスト：`tests/remote-dev-config.sh`

これらを変更したら、dotfiles リポジトリで `tests/remote-dev-config.sh` を実行する。
挙動が変わる変更では、このスキルと references の記述も合わせて更新する。

実機接続、mDNS 解決、NixOS 側の公開鍵登録は環境依存である。
確認していない場合は、確認済みとして書かない。
