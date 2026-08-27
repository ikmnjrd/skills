---
name: nixos-local
description: ローカルの Git worktree を `remote-dev` でNixOSリモート開発環境へ同期し、SSHエイリアス `nixos-remote-dev` 経由でテスト、ビルド、サーバーを実行するワークフローを扱う。Use when the task involves the nixos-remote-dev SSH alias, the remote-dev command, syncing a worktree to NixOS, reusing or starting remote servers and SSH tunnels, running tests or builds on the remote host, or troubleshooting SSH keys and rsync sync paths for this workflow.
---

# NixOSリモート開発

このスキルは、ローカルの Git worktree をNixOSリモート開発環境上の実行コピーへ同期して開発するワークフローを扱う。
接続にはSSHエイリアス `nixos-remote-dev` を使い、実ホスト名やIPアドレスをスキル内で固定しない。

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

## 既存のサーバーと SSH トンネル

サーバーや SSH トンネルは、別のタスクやユーザー操作ですでに起動している場合がある。
長時間動くプロセスを新しく起動する前に、既存のプロセスが今回の同期先、ポート、転送先に合うか確認する。
条件が合い、疎通確認に成功したプロセスはそのまま再利用する。

確認する対象は次のとおり。

1. リポジトリの設定と `remote-dev` の出力から、同期先、サーバーのポート、ローカルとリモートの転送先を特定する。
2. ローカルの待受ポートと SSH トンネルを `lsof` と `ps` で確認する。
3. NixOS 側の待受ポートとサーバープロセスを `ss` と `ps` で確認する。
4. HTTP サーバーなら、既存のローカルポートへ `curl` またはブラウザーで接続し、今回必要な画面や応答が得られることを確認する。

```sh
# ローカルの待受ポートと SSH トンネルを確認する例
lsof -nP -iTCP:<local-port> -sTCP:LISTEN
ps -ax -o pid=,command= | rg 'ssh .*-[NLR]|<local-port>|<remote-port>'

# NixOS 側の待受ポートを確認する例
ssh nixos-remote-dev "ss -ltnp 'sport = :<remote-port>'"
ssh nixos-remote-dev 'ps -fp <pid>'
ssh nixos-remote-dev 'readlink /proc/<pid>/cwd'

# 既存のトンネル経由で疎通を確認する例
curl -fsS http://127.0.0.1:<local-port>/<health-or-page>
```

ポートが開いているだけでは再利用可能と判断しない。
プロセスのコマンド、必要なら `/proc/<pid>/cwd`、実際の応答を確認し、対象の同期先で動くサーバーかを判定する。
開発サーバーが同期後の変更を自動反映するなら、再起動せずに使い続ける。

再利用できるプロセスが無い場合だけ、新しいサーバーまたは SSH トンネルを起動する。
既存のローカルポートが別用途で使われている場合は上書きせず、別ポートを選ぶかユーザーへ確認する。
タスク外で起動されたプロセスはユーザー管理として扱い、停止、再起動、置換をしない。
終了が必要な場合も、現在のタスクで起動したプロセスだけを対象にする。
`pkill` のように対象を広く取る停止方法は使わない。

## 基本ループ

1. ローカルの worktree でファイルを編集する。
2. worktree 内で `remote-dev` を実行し、NixOS 側へ同期する。
3. 初回同期後とロックファイル変更後だけ、SSH 先で依存をインストールする(後述)。
4. SSH 先の同期先ディレクトリでテストやビルドのコマンドを実行する。
5. サーバーやブラウザーを使う確認では、既存のサーバーと SSH トンネルを再利用し、存在しないものだけを起動する。

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

ローカルの flake.lock が flake.nix より古いと、SSH 先の `nix develop` は flake.lock を書き換えて補完する(ログに lock file 更新の警告が出る)。
`--no-update-lock-file` は書き換えを防ぐがエラーで停止するため、回避策にならない。
書き換えに気付いたら、更新された flake.lock をローカルへ回収する。
ローカルで nix を使わないため、これが flake.lock の正規の更新経路である。
回収はワーキングツリーへの反映までに留め、コミットするかどうかはユーザーに委ねる(回収した事実と理由を報告する)。
回収しないと、同期のたびに古い lock へ巻き戻り、SSH 先での書き換えが毎回発生する。

```sh
# ローカルの worktree で実行する例
scp nixos-remote-dev:'<同期先>/nix/flake.lock' nix/flake.lock
```

## 依存インストール

`node_modules` は同期されないため、依存は SSH 先でインストールする。
ただし毎回ではない。
要否は次のように判定する。

- 同期先に `node_modules` が無い(初回同期後): インストールする。
- 今回の変更でロックファイルに触れた: インストールする。
- どちらでもない: そのまま使う。
- 判定に迷う: インストールする。下記の方式なら冪等で、キャッシュが効けば十数秒で終わる。mtime 比較などの判定手段を自作しない。

守る不変条件は「SSH 先でロックファイルを書き換えない」である。
対象はリポジトリ管理下のロックファイル全般(yarn.lock、package-lock.json、flake.lock など)。
flake.lock だけは `nix develop` 自身が書き換えることがあり、その扱いは「SSH 先の実行環境への入り方」に書いた。
ロックファイルの正本はローカルにあり、SSH 先で書き換わると正本と食い違ったうえ、次回同期で失われる。
このため `yarn install --frozen-lockfile` を使う(Yarn Berry では `--immutable` の別名として動作する。npm なら `npm ci`)。

## 実行先の判断規則

- ファイル編集、`git add` や `git commit` などの Git 操作：ローカル。
- テスト、ビルド、サーバー起動、`docker compose`、`nix develop`：SSH 先の同期先。
- サーバーや SSH トンネル：既存プロセスを優先して再利用し、必要な場合だけ新しく起動する。
- 新しく起動するサーバーなどの長時間プロセス：`docker compose up -d` のようにデタッチで起動する。
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

実機接続、SSHの接続先、NixOS側の公開鍵登録は環境依存である。
確認していない場合は、確認済みとして書かない。
