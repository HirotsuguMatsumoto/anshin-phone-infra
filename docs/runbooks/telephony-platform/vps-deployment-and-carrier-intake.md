---
schema_version: 2
doc_id: anshin.phone.vps-deployment-and-carrier-intake
title: "MS-A2-2 Phone VM配置準備・キャリア接続情報受領手順"
domain: telephony-platform
document_kind: runbook
scope: product
product: anshin-phone
owner: anshin-phone-infra
authority: reference
status: inventory
risk_level: critical
source_doc_ids: []
consumers: [anshin-phone-infra]
code_paths: [compose.phase1.yaml, scripts/render_phase1_firewall.py, scripts/validate_carrier_intake.py]
contract_paths: [configs/carrier-intake.example.json]
test_paths: [scripts/test_carrier_and_firewall_tools.py]
last_reviewed: "2026-10-02"
review_interval_days: 30
sensitivity: internal
---

# MS-A2-2 Phone VM配置準備・キャリア接続情報受領手順

## 専門用語一覧

| 用語 | 正式名称・読み方 | 意味・本書での扱い |
| --- | --- | --- |
| VPS | Virtual Private Server | 仮想化された専用環境として利用するserver |
| JSON | JavaScript Object Notation | keyとvalueの構造でデータを表現するテキスト形式 |
| Git | Git | ファイルの変更履歴とブランチを管理する分散型バージョン管理システム |
| SIP | Session Initiation Protocol | IP網上で電話の発着信や通話sessionを制御する通信規約 |
| RTP | Real-time Transport Protocol | SIP等で確立した通話の音声データを運ぶ通信規約 |
| DTMF | Dual-Tone Multi-Frequency | 電話機の数字キー等の押下情報を伝える信号方式 |
| DID | Direct Inward Dialing | 着信番号をPBX等へ通知し、番号別に着信先を制御する方式 |
| FAX | Facsimile | 電話網等を使って文書画像を送受信する通信サービス |
| SHA-256 | Secure Hash Algorithm 256-bit | データから256bitのhash値を生成し、同一性・改ざん有無を確認するアルゴリズム |
| Docker | Docker | アプリケーションと依存関係をcontainerとして実行・配布する基盤 |
| PostgreSQL | PostgreSQL | open sourceのリレーショナルデータベース管理システム |
| SSH | Secure Shell | 暗号化された通信でserverへログイン・コマンド実行するプロトコル |
| E2E | End-to-End | 利用者操作から最終処理までの一連の経路又はそのテスト |
| DB | Database | 業務データを永続的に保存・検索するデータベース |
| schema | Schema | dataの項目、型、制約及び構造を定義したもの |

## 接続情報の取込み

2026年9月30日に確認したClocoの返信・添付図は[接続・責任分界の確認仕様](../../specs/telephony-platform/cloco-sip-trunk-interface.md)に記録した。インターネット経由SIPトランク接続と概略責任分界は確認済みだが、具体的な接続先、認証、SIP/RTP、FAX及びチャネル容量は未受領である。番号数の上限なしを同時通話容量の確定値として入力しない。物理配置先も当該添付図から確定しない。

Cloco等から回答を受領したら、`configs/carrier-intake.example.json`をGit外へ複製し、SIP/RTP CIDR、認証方式、codec、DTMF、DID形式、FAX、チャネル、CPS、緊急通報条件を記録する。passwordは記録せず、外部secret保管先の識別子だけを設定する。

```bash
python3 scripts/validate_carrier_intake.py /protected/path/carrier-intake.json
```

`approved_by`と緊急通報条件を含め、FAILが0件になるまで実番号・本番へ反映しない。メール本文や添付をそのまま実行入力にせず、担当者が転記して二者確認する。

## 配置先と実行停止条件

現在の唯一の予定配置先はMS-A2-2（東京）のPhone専用LXD VM内のDockerである。Core/AuthのDocker daemon・DB・volume・credentialとは分離するが、物理host・電源・LAN・NVMe障害は共有する。旧Marketing VPS又は別Phone VPSへ配置しない。既存doc_id・filenameは参照互換のため保持するだけであり、VPS配備を許可しない。

Phone VMは未作成・稼働未確認、資源予算は未実測である。Phone deploy adapter及びhost再配置operationは未実装・未登録であり、配置・firewall適用・再起動・実番号接続はBLOCK。下記は将来の資格取得要件であり、現時点で実行できる配備手順ではない。SSH・対話sudo・印刷したshellで正規release経路を迂回しない。

## 将来の配置資格要件（現時点では実行不可）

1. `main`とPhone VMのcheckout SHA、dirty差分、Docker/空き容量/メモリを確認する。
2. PostgreSQL logical backup、named volume一覧、現在のCompose展開結果、旧image digestをGit外のアクセス制限済み領域へ保存する。
3. host firewallの既存管理主体を確認し、既存SSH許可を失わない別セッションでrulesetを検証する。
4. review用rulesetは`render_phase1_firewall.py`でGit外へ生成する。このscriptは適用しない。
5. `docker compose config`、repository-local check、モックE2Eに合格し、実測資源予算・変更直前snapshot・immutable artifact・独立reviewを固定する。正規release bundleと登録済みoperation・deploy adapterが実装済みの場合だけ変更窓で配備できる。未実測overrideを通常配備へ含めない。
6. health、REGISTER、着信、発信、RTP、FAX、履歴を順に確認する。

## 切戻し

着信不能、片通話、誤った発信者番号、FAX欠落、履歴欠落、SIP不正利用又は既存Core/Auth又はMS-A2-2 hostへの影響が1件でもあれば、新規発信を止める。旧image digestと旧Compose定義へ戻し、DB schemaを先に巻き戻さない。番号経路はClocoと合意した旧関連付けへ戻し、旧経路の復旧を確認する。復旧後に差分・SIP response・時刻・影響を記録する。

host firewall適用、container再起動、DB restore、番号経路変更は本番mutationであり、正規release資格及び登録済みoperation・deploy adapterなしに実行しない。VM資源変更は変更直前snapshotへ戻し、過去の仮定値をrollback値として流用しない。
