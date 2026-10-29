---
schema_version: 2
doc_id: anshin.phone.vps-deployment-and-carrier-intake
title: "VPS配備・キャリア接続情報受領手順"
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
contract_paths: [configs/carrier-intake.example.json, docs/specs/changes/2026-10-29-cloco-provider-alignment.change.yaml]
test_paths: [scripts/test_carrier_and_firewall_tools.py]
last_reviewed: "2026-10-29"
review_interval_days: 30
sensitivity: internal
---

# VPS配備・キャリア接続情報受領手順

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

10/29の[接続・責任分界の確認仕様](../../specs/telephony-platform/cloco-sip-trunk-interface.md)を技術上の優先参照とする。Cloco株式会社様の原図・10/28回答・Ver2.0.1の既知条件は同仕様へ取り込んだ。To/Alert-Info、番号別From、標準認証方式と通信許可条件を再質問せず当社が実装する。個別トランクの値、既存FAX条件、試験利用条件は受領資料・管理画面・通常案内から確定する。

carrierをAsteriskで終端し、まず社内端末だけをつなぐ最小試験へ変更する設計である。現在のPhase1 Composeは旧SBC透過接続の実装であり、新設計の配備手順としてそのまま使わない。接続口・物理配置未選定、private VMでの到達未証明を維持する。新しい公開・調達・ルーター変更、旧runtimeの適用は行わない。標準仕様へ当社が合わせ、先方へ特別構成を求めない。

Cloco株式会社様等から回答を受領したら、`configs/carrier-intake.example.json`をGit外へ複製し、SIP/RTP CIDR、認証方式、codec、DTMF、DID形式、FAX、チャネル、CPS、緊急通報条件を記録する。passwordは記録せず、外部secret保管先の識別子だけを設定する。

```bash
python3 scripts/validate_carrier_intake.py /protected/path/carrier-intake.json
```

`approved_by`と緊急通報条件を含め、FAILが0件になるまで実番号・本番へ反映しない。メール本文や添付をそのまま実行入力にせず、担当者が転記して二者確認する。

## VPS配備gate

1. `main`とVPSのcheckout SHA、dirty差分、Docker/空き容量/メモリを確認する。
2. PostgreSQL logical backup、named volume一覧、現在のCompose展開結果、旧image digestをGit外のアクセス制限済み領域へ保存する。
3. host firewallの既存管理主体を確認し、既存SSH許可を失わない別セッションでrulesetを検証する。
4. review用rulesetは`render_phase1_firewall.py`でGit外へ生成する。このscriptは適用しない。
5. `docker compose config`、`bash scripts/build_check.sh --fast`、モックE2Eに合格してから、承認済み変更窓で配備する。
6. health、REGISTER、着信、発信、RTP、FAX、履歴を順に確認する。

## 切戻し

着信不能、片通話、誤った発信者番号、FAX欠落、履歴欠落、SIP不正利用又は既存マーケティング基盤への影響が1件でもあれば、新規発信を止める。旧image digestと旧Compose定義へ戻し、DB schemaを先に巻き戻さない。番号経路はCloco株式会社様と合意した旧関連付けへ戻し、旧経路の復旧を確認する。復旧後に差分・SIP response・時刻・影響を記録する。

host firewall適用、container再起動、DB restore、番号経路変更は本番mutationであり、各操作の明示承認なしに実行しない。
