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

## 専門用語一覧

| 用語 | 正式名称・読み方 | 意味・本書での扱い |
| --- | --- | --- |
| MD | Markdown | 見出し、表、link等をplain textで記述する文書形式 |
| FAX | Facsimile | 電話網等を使って文書画像を送受信する通信サービス |
| PDF | Portable Document Format | 表示・印刷レイアウトを保持する文書ファイル形式 |
| TEL | Telephone | 音声通話に使用する電話又は電話番号 |
| SIP | Session Initiation Protocol | IP網上で電話の発着信や通話sessionを制御する通信規約 |
| VPS | Virtual Private Server | 仮想化された専用環境として利用するserver |

このルートは、Anshin Phone の通信・infra運用文書を管理する。登録時点では正本を宣言せず、実装、契約、法令・キャリア条件との照合が完了した文書だけを別途canonical候補として審査する。

## 現在の文書

- [Cloco × アンシンフォン 論理・物理構成図](specs/telephony-platform/cloco-anshin-phone-end-to-end.drawio): 電話発信者・受信者、Cloco SIPトランク2、SBC、RTPengine、Asterisk、Backend及び管理系を発着信方向別に示すdraw.io XML。
- [Phase 1 実番号接続手順](runbooks/telephony-platform/phase1_real_number_runbook.md): 実番号試験の参照runbook。`reference / inventory`であり、商用提供可否や法令適合の正本ではない。
- [スマートフォン実機・音声品質検証](runbooks/telephony-platform/smartphone-and-voice-validation.md): 端末credentialの安全な投入、失効、実機・30分音声品質の合格条件。
- [FAX・番号プロビジョニング](runbooks/telephony-platform/fax-and-number-provisioning.md): PDF参照、送信queue/retry、TEL番号とSIP endpointの割当・状態遷移。
- [VPS配備・キャリア接続情報受領手順](runbooks/telephony-platform/vps-deployment-and-carrier-intake.md): 配備gate、firewall、backup/rollback、Cloco等の接続情報検証。
- [VPS Phase 1配置前監査 2026-08-21](evidence/telephony-platform/vps_phase1_readiness_2026-08-21.md): 初回の読み取り専用監査結果。
- [VPS Phase 1配置前監査 2026-08-22](evidence/telephony-platform/vps_phase1_readiness_2026-08-22.md): 再監査結果と現在の配置停止条件。
