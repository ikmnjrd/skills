# remote-dev 参照

`remote-dev` の実体は `~/workspace/dotfiles` で管理し、`./deploy.sh set` でユーザーコマンドとしてリンクしている。
日常の編集→同期→実行のループは SKILL.md 側に書いてある。
このファイルは、同期仕様の詳細、初期設定、トラブルシュートを扱う。

## 関連ファイル(~/workspace/dotfiles 内)

- `bin/remote-dev`：同期コマンド本体。
- `ssh/config.d/nixos-remote-dev`：NixOSリモート開発環境へのSSH接続設定。
- `deploy.sh`：`remote-dev` と SSH 設定をホームディレクトリへリンクする。
- `tests/remote-dev-config.sh`：同期先パス、除外設定、廃止済みサブコマンドを検証する。
- `README.md`：利用者向けの概要手順。

## SSH 設定

既定のSSHエイリアスは `nixos-remote-dev` である。
実ホスト名、IPアドレス、ユーザー、認証鍵は `ssh/config.d/nixos-remote-dev` を正本とし、スキル内で固定しない。
接続設定を確認するときは `ssh -G nixos-remote-dev` を使う。

別の SSH ホストを試す場合は、`REMOTE_DEV_SSH_TARGET` を指定する。

```sh
REMOTE_DEV_SSH_TARGET=<ssh-host> remote-dev doctor
REMOTE_DEV_SSH_TARGET=<ssh-host> remote-dev
```

## 同期先パス

同期先は次の形式である。

```text
~/workspace/remote-dev/<host>/<repo>/<branch>/
```

`<host>` は `REMOTE_DEV_HOST_ID` があればその値を使い、なければ `hostname -s` を使う。

`<repo>` は `remote.origin.url` のリポジトリ名から決める。
remote が無い場合は、worktree のディレクトリ名を使う。

`<branch>` は現在ブランチ名から決める。
detached HEAD はサポートしない。

各 ID は小文字化され、`a-z`、`0-9`、`_`、`.`、`-` 以外は `-` に置換される。
先頭と末尾の `-` は 1 文字ずつ取り除かれる。
空文字または 48 文字超の ID はエラーになる。

## 同期対象

同期は `rsync -az --delete` で実行する。

除外対象は次のとおり。

```text
.git
node_modules
.direnv
result
result-*
.next
.nuxt
.output
dist
build
coverage
.cache
.turbo
.vite
.remote-dev-local
```

`.env` や `.env.local` は除外しない。
ローカルだけにある Git 管理外ファイルも同期される。

## 初期設定(未設定の環境の場合)

初回だけ、ホスト別の SSH 鍵を作成する。

```sh
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_nixos_remote_dev
```

作成した公開鍵を NixOS 側の設定へ追加する。
dotfiles リポジトリには NixOS 側の設定は含まれないため、追加先は利用者の `nixos-config` で確認する。

`~/workspace/dotfiles` でリンクを張る。

```sh
./deploy.sh set
```

リンク後、`~/.ssh/config.d/nixos-remote-dev` と `~/.local/bin/remote-dev` が使われる。

## トラブルシュート

### 接続確認

ローカルで必要なコマンドと SSH 接続を確認する。

```sh
remote-dev doctor
```

成功時は、少なくとも次の確認結果が出る。

```text
ok: git
ok: rsync
ok: ssh
ok: ssh nixos-remote-dev
```

### remote-dev コマンドが見つからない

`~/.local/bin/remote-dev` のリンクが無い。
`~/workspace/dotfiles` で `./deploy.sh set` を実行する。

### SSH 接続に失敗する

次の順で切り分ける。

1. `~/.ssh/id_ed25519_nixos_remote_dev` が存在するか。
2. 公開鍵が NixOS 側に登録されているか(`nixos-config` を確認する)。
3. `~/.ssh/config.d/nixos-remote-dev` のリンクが張られているか。
4. `ssh -G nixos-remote-dev` が意図した接続設定を返すか。
5. SSH設定が示す実接続先へ到達できるか。

## 実装変更時のテスト

`bin/remote-dev` を変更したら、`~/workspace/dotfiles` でテストを実行する。

```sh
tests/remote-dev-config.sh
```

このテストは、SSH と rsync をスタブ化して次を検証する。

- `remote-dev doctor` が `ssh -o BatchMode=yes nixos-remote-dev true` を実行する。
- 同期先が `workspace/remote-dev/<host>/<repo>/<branch>` になる。
- `rsync --delete` が使われる。
- `node_modules` と `.remote-dev-local` が除外される。
- `.env` は除外されない。
- 廃止済みの `remote-dev up` は成功しない。
