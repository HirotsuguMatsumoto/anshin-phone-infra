---
schema_version: 2
doc_id: anshin.phone.documents-index
title: Anshin Phone documents
domain: telephony-platform
document_kind: index
scope: product
product: anshin-phone
owner: anshin-phone-infra
authority: reference
status: inventory
risk_level: high
source_doc_ids: []
consumers:
  - anshin-phone-infra
  - anshin-phone-backend
code_paths: []
contract_paths: []
test_paths: []
last_reviewed: null
review_interval_days: 30
sensitivity: internal
---

# Anshin Phone documents

このルートは、Anshin Phone の通信・infra運用文書を管理する。登録時点では正本を宣言せず、実装、契約、法令・キャリア条件との照合が完了した文書だけを別途canonical候補として審査する。

## 現在の文書

- [Phase 1 実番号接続手順](runbooks/telephony-platform/phase1_real_number_runbook.md): 実番号試験の参照runbook。`reference / inventory`であり、商用提供可否や法令適合の正本ではない。
- [VPS Phase 1配置前監査 2026-08-21](evidence/telephony-platform/vps_phase1_readiness_2026-08-21.md): 読み取り専用監査の結果と配置停止条件。
