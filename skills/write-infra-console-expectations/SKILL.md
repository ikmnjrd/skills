---
name: write-infra-console-expectations
description: AWS CLI、Terraform、CloudFormation、gcloud、az、kubectl などのインフラ作成コマンドを含む手順書、README、運用ドキュメントを書くときに、対象プロバイダーのWebコンソールで作成結果を確認するための過不足ない期待値を追記・点検する。リソース作成、設定変更、権限付与、ネットワーク、監視、ストレージ、データベース、IaC 適用手順の確認観点を書くときに使用する。
---

# インフラ手順書のコンソール確認期待値

インフラ作成コマンドを含む文書には、コマンドの実行結果だけでなく、対象プロバイダーのWebコンソールで読者が確認できる期待値を書く。
期待値は、作成したリソースが存在し、意図した主要設定が反映され、誤った対象を見ていないことを確認できる最小十分な内容に絞る。

## ワークフロー

1. 対象コマンドを読む。
   `aws`、`terraform apply`、`terraform plan`、`cloudformation deploy`、`gcloud`、`az`、`kubectl apply` などから、作成・変更されるリソース、リージョン、アカウント、プロジェクト、サブスクリプション、名前、タグ、出力値を抽出する。
2. 確認対象をリソース単位に分ける。
   ひとつの確認項目に、複数のプロバイダー画面や複数のリソース種類を混ぜない。
3. 公式コンソールで実際に見える単位へ落とす。
   コンソール名、サービス名、リソース一覧または詳細画面、主要フィールド名を、対象プロバイダーの現在の表記に合わせる。
   表記が不確かな場合や最近変わった可能性がある場合は、公式ドキュメントを確認する。
4. 期待値を書く。
   名前、リージョン、状態、主要設定、関連付け、タグ、出力値との対応を中心にする。
   コンソールで直接見えない内部実装、API レスポンス専用フィールド、手順の成功に不要な全属性列挙は入れない。
5. 過不足を点検する。
   「この期待値だけで、読者は正しい対象に作られたことを判断できるか」と「この確認は成功判定に本当に必要か」を両方確認する。

## 未提示値と条件付き関係の扱い

コマンドや IaC から読み取れない実値を捏造しない。
未提示の値は、確認元が分かる表現に置き換える。

- Terraform、CloudFormation、Bicep、Kubernetes manifest などに存在する値：`Terraform 定義で指定した値`、`service.yaml の設定`、`horizontalpodautoscaler.yaml の設定` のように書く。
- 実行環境のスコープ値：`手順を実行した対象サブスクリプション`、`対象 AWS アカウント`、`<gcp-project-id>` のように、誤認防止に必要な範囲だけを書く。
- 実値が未提供だが作業前に必須の値：`<expected-vpc-or-subnets>`、`<expected-log-retention>` のように置換対象だと分かる形で書く。

不足値をこの形で確認対象または置換対象として明示できている場合は、未解決の不明点として扱わない。
ただし、その値がないと読者が別アカウント、別サブスクリプション、別プロジェクト、別クラスタを見てしまう場合は、確認項目の冒頭にスコープとして必ず書く。

関連付けが入力から断定できない場合は条件付きで書く。
「有効化している場合」「Terraform 定義で関連付けている場合」「manifest で指定している場合」のように、確認すべき条件を明示する。
推定だけで、ALB access logs、Service selector、target group association、KMS key、alert rule などの関係を断定しない。

作成直後に状態が揺れるリソースでは、一時状態と安定後の期待値を分ける。
例：ロードバランサーの `Provisioning` から `Active`、Kubernetes Pod の `Pending` から `Running`、HPA の metrics 取得待ち、外部 IP の割り当て待ち。

## 書くべき期待値

確認項目は、原則として次の形で書く。

```markdown
### Webコンソールでの確認

1. <サービス名> コンソールで <画面または一覧> を開く。
2. <識別子> が `<期待される名前やID>` のリソースを選ぶ。
3. 次の状態であることを確認する。
   - <状態フィールド>: `<期待値>`
   - <主要設定>: `<期待値>`
   - <関連付け>: `<期待値>`
   - <タグまたはラベル>: `<期待値>`
```

各確認項目には、少なくとも次を含める。

- **場所**：どのプロバイダー、アカウント、リージョン、サービス、画面で確認するか。
- **対象識別子**：リソース名、ID、ARN、プロジェクト、サブスクリプション、namespace、タグなど。
- **成功状態**：`Available`、`Active`、`CREATE_COMPLETE`、`InService` など、コンソールで見える状態。
- **主要設定**：手順の目的に直結する設定だけ。
- **関係性**：VPC と subnet、security group と EC2、IAM role と policy、load balancer と target group など、作成結果の正しさを左右する紐づき。
- **IaC との対応**：Terraform output、変数、resource 名、module 名、タグとコンソール表示の対応。

## 省くべき期待値

- コンソールで通常確認できない provider 内部 ID や API 専用属性。
- 目的と無関係なデフォルト値の全列挙。
- コマンドや Terraform state を見れば足りる内容だけの再掲。
- 画面遷移の細かすぎるクリック手順。
- 作成直後は一時的に揺れる値を、安定値のように断定した記述。
- セキュリティ上露出させるべきでない secret、access key、password、token。

## 粒度の基準

過不足ない確認は、次の問いに答える。

- **存在確認**：作成対象が正しいスコープに存在するか。
- **状態確認**：使用可能な状態まで到達しているか。
- **設定確認**：この手順で変更した要点が反映されているか。
- **接続確認**：他リソースとの関連付けが意図通りか。
- **識別確認**：同名や既存リソースとの取り違えを避けられるか。

リソースごとに 3 から 6 個程度の期待値を目安にする。
セキュリティ、ネットワーク、権限、公開範囲、課金影響がある場合は、それらの確認を優先する。

## プロバイダー別の読み替え

- **AWS**：アカウント、リージョン、サービス画面、ARN や名前、状態、VPC / subnet / security group / IAM role などの関連付けを確認する。
- **Azure**：サブスクリプション、リソースグループ、location、リソース名、状態、SKU や OS、App Service plan などの親子関係を確認する。
- **Google Cloud / GKE**：project、region または zone、cluster、namespace、workload 名、Service、Pod、HPA、安定後の Ready / Running / target 状態を確認する。
- **Kubernetes 管理コンソール**：cluster、namespace、kind、name、selector、owner、rollout 状態、replica 数、関連 Service / HPA を確認する。

## AWS の例

AWS CLI や Terraform で AWS リソースを作る文書では、AWS マネジメントコンソールで確認できる値を書く。

悪い例：

```markdown
S3 バケットが作成されていることを確認します。
```

良い例：

```markdown
### Webコンソールでの確認

1. AWS マネジメントコンソールで、対象リージョンが `ap-northeast-1` であることを確認する。
2. S3 コンソールのバケット一覧で `example-app-logs-prod` を開く。
3. 次の状態であることを確認する。
   - Block Public Access: すべて `On`
   - Versioning: `Enabled`
   - Default encryption: `SSE-S3` または手順で指定した KMS key
   - Tags: `Environment=prod`、`Service=example-app`
```

## Terraform の例

Terraform 手順では、`terraform output` とコンソール表示の対応を書く。
resource address をそのまま読者の確認対象にしない。

```markdown
### Webコンソールでの確認

1. AWS マネジメントコンソールで EC2 > Load Balancers を開く。
2. `terraform output alb_dns_name` に表示された DNS 名に対応する ALB を選ぶ。
3. 次の状態であることを確認する。
   - Scheme: `internet-facing`
   - State: `Active`
   - Listeners: `HTTPS:443` が存在する
   - Security groups: `example-prod-alb-sg` が関連付けられている
   - Target group: `example-prod-web` の Healthy targets が期待台数になっている
```

## 執筆時の注意

- 既存文書の文体、見出し階層、番号付き手順、注意書きの形式に合わせる。
- 作成コマンドの直後、または「動作確認」節の中にコンソール確認を置く。
- CLI 確認とコンソール確認を併記する場合は、役割を分ける。
  CLI は機械的な値確認、コンソールは読者が画面で判断する期待値に向く。
- プロバイダー UI の名称、サービス名、状態名、画面構成が現在も正しいか怪しい場合は、公式ドキュメントを確認してから書く。
- 実環境にアクセスして確認できない場合は、「想定される表示」と分かる書き方にし、確認済みであるかのように書かない。
