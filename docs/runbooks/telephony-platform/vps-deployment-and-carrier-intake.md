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
contract_paths: [configs/carrier-intake.example.json]
test_paths: [scripts/test_carrier_and_firewall_tools.py]
last_reviewed: "2026-08-21"
review_interval_days: 30
sensitivity: internal
---

# VPS配備・キャリア接続情報受領手順

## 接続情報の取込み

Cloco等から回答を受領したら、`configs/carrier-intake.example.json`をGit外へ複製し、SIP/RTP CIDR、認証方式、codec、DTMF、DID形式、FAX、チャネル、CPS、緊急通報条件を記録する。passwordは記録せず、外部secret保管先の識別子だけを設定する。

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

着信不能、片通話、誤った発信者番号、FAX欠落、履歴欠落、SIP不正利用又は既存マーケティング基盤への影響が1件でもあれば、新規発信を止める。旧image digestと旧Compose定義へ戻し、DB schemaを先に巻き戻さない。番号経路はClocoと合意した旧関連付けへ戻し、旧経路の復旧を確認する。復旧後に差分・SIP response・時刻・影響を記録する。

host firewall適用、container再起動、DB restore、番号経路変更は本番mutationであり、各操作の明示承認なしに実行しない。
