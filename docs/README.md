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
source_doc_ids: [anshin.phone.cloco-sip-trunk-interface]
consumers:
  - anshin-phone-infra
  - anshin-phone-backend
code_paths: []
contract_paths: [docs/specs/changes/2026-10-12-phone-document-navigation.change.yaml]
test_paths: [scripts/build_check.sh]
last_reviewed: "2026-10-12"
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

## 資料を探す入口

- [Phone総合資料入口](https://github.com/HirotsuguMatsumoto/anshin-corporate-strategy/blob/main/documents/plans/anshin-phone/README.md): 事業・申請・MS-A2-2配置設計の履歴・技術・様式・受領原本の参照先。
- [Backend README](https://github.com/HirotsuguMatsumoto/anshin-phone-backend/blob/main/README.md) / [Backend資料入口](https://github.com/HirotsuguMatsumoto/anshin-phone-backend/blob/main/documents/README.md): 管理API、DB、認証認可、監査及び保護FAX原本。
- [管理画面README](https://github.com/HirotsuguMatsumoto/anshin-frontend-monorepo/blob/main/apps/anshin-phone/README.md) / [基礎管理画面の設計](https://github.com/HirotsuguMatsumoto/anshin-frontend-monorepo/blob/main/apps/anshin-phone/documents/plans/telephony-platform/foundation-ui-plan.md): 画面、操作導線及び検証条件。

Backend三文書・管理画面二文書は既存resolverで一意に解決できる登録へ修正した。reference／derivedのauthorityは変更しない。2026-10-12のowner継続指示により予定配置をMS-A2-2内のPhone専用LXD VMへ同期し、Core/AuthのVM・DB・volume・credentialと分離する。本番未配備、旧branch全体の未統合、実機資源・配備経路の確認中を区別する。

## 現在の文書

- [Cloco SIPトランク接続・責任分界の確認仕様](specs/telephony-platform/cloco-sip-trunk-interface.md): 2026年9月30日に確認したCloco返信・添付図の確定範囲、当社予定構成への対応及び未受領の詳細仕様。

- [Cloco × アンシンフォン 論理・物理構成図](specs/telephony-platform/cloco-anshin-phone-end-to-end.drawio): 電話発信者・受信者、Cloco SIPトランク2、SBC、RTPengine、Asterisk、Backend及び管理系を発着信方向別に示すdraw.io XML。
- [Phase 1 実番号接続手順](runbooks/telephony-platform/phase1_real_number_runbook.md): 実番号試験の参照runbook。`reference / inventory`であり、商用提供可否や法令適合の正本ではない。
- [スマートフォン実機・音声品質検証](runbooks/telephony-platform/smartphone-and-voice-validation.md): 端末credentialの安全な投入、失効、実機・30分音声品質の合格条件。
- [FAX・番号プロビジョニング](runbooks/telephony-platform/fax-and-number-provisioning.md): PDF参照、送信queue/retry、TEL番号とSIP endpointの割当・状態遷移。
- [VPS配備・キャリア接続情報受領手順](runbooks/telephony-platform/vps-deployment-and-carrier-intake.md): 配備gate、firewall、backup/rollback、Cloco等の接続情報検証。
- [VPS Phase 1配置前監査 2026-08-21](evidence/telephony-platform/vps_phase1_readiness_2026-08-21.md): 初回の読み取り専用監査結果。
- [VPS Phase 1配置前監査 2026-08-22](evidence/telephony-platform/vps_phase1_readiness_2026-08-22.md): 再監査結果と現在の配置停止条件。

## 受領構成図・変更履歴

- [受領したSIPトランク設備構成図](references/telephony-platform/SIPトランク設備構成図.pdf): 受領PDF。物理配置先・契約許諾・本番稼働の承認書とは分ける。
- [通信基盤の変更契約一覧](https://github.com/HirotsuguMatsumoto/anshin-phone-infra/tree/main/docs/specs/changes): 日付付き変更契約は履歴参照。現行Markdownの代替正本にしない。
