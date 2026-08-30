---
schema_version: 2
doc_id: anshin.phone.fax-and-number-provisioning
title: "FAX・番号プロビジョニング"
domain: telephony-platform
document_kind: runbook
scope: product
product: anshin-phone
owner: anshin-phone-infra
authority: reference
status: inventory
risk_level: high
source_doc_ids: []
consumers: [anshin-phone-infra, anshin-phone-backend]
code_paths: [anshin-phone-backend/app/api/routes.py, anshin-phone-backend/app/models/telephony.py]
contract_paths: [anshin-phone-backend/app/api/schemas.py]
test_paths: [anshin-phone-backend/tests/test_phase1_api.py]
last_reviewed: "2026-08-21"
review_interval_days: 30
sensitivity: internal
---

# FAX・番号プロビジョニング

## 専門用語一覧

| 用語 | 正式名称・読み方 | 意味・本書での扱い |
| --- | --- | --- |
| FAX | Facsimile | 電話網等を使って文書画像を送受信する通信サービス |
| PBX | Private Branch Exchange | 内線、外線、着信振分け及び転送等を制御する電話交換システム |
| TEL | Telephone | 音声通話に使用する電話又は電話番号 |
| SIP | Session Initiation Protocol | IP網上で電話の発着信や通話sessionを制御する通信規約 |
| 電気通信番号 | でんきつうしんばんごう | 電気通信役務の提供において端末や通信先等を識別する番号 |
| 電気通信番号使用計画 | でんきつうしんばんごうしようけいかく | 電気通信番号の使用方法、管理及び設備等を定め、認定等の対象となる計画 |
| API | Application Programming Interface | システムやソフトウェア間で機能・データを利用するための接続仕様 |
| backend | Backend | server側でAPI、業務処理及びdata管理等を担うsoftware領域 |
| PDF | Portable Document Format | 表示・印刷レイアウトを保持する文書ファイル形式 |
| DB | Database | 業務データを永続的に保存・検索するデータベース |

## 番号

キャリア払い出し直後は`provisioning`とし、PBXへの到達確認中は`testing`、着信・発信・番号通知・緊急通報条件・履歴を確認後に`active`とする。`active`にはroute targetを必須とし、`released`からの復帰を禁止する。TEL番号とSIP endpointの割当は同一tenantだけを許可し、FAX番号を音声endpointへ割り当てない。

番号の直接指定、標準電気通信番号使用計画、番号名義・利用場所の法令判断はこのAPIのstatusだけでは確定しない。Backendはキャリアから正当に払い出された番号の運用台帳であり、番号使用権を生成しない。

## FAX

送信APIはPDF本体・平文宛先番号をDBへ保存せず、保護ストレージ参照、保護された宛先参照、マスク済み表示値を受ける。同じidempotency keyは同じjobを返す。retryable failureは30秒から指数backoffし、最大5回で終端`failed`になる。permanent failureと`sent`は再実行しない。

Phase 1のAPIはqueue状態機械までを対象とする。実際のT.38/G.711送信worker、PDFからTIFFへの変換、malware scan、ページ上限、暗号化原本保管、期限削除、受信通知はClocoのFAX方式確定後に接続する。モック成功を実FAX成功の証跡にしない。
