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

送信APIはPDF本体・平文宛先番号をDBへ保存せず、保護ストレージ参照、保護された宛先参照、マスク済み表示値を受ける。同じidempotency keyは同じjobを返す。retryable failureは30秒から指数backoffし、管理画面で受け付けたjobは既定最大3回（既存内部APIのlegacy jobは最大5回）で終端`failed`になる。permanent failureと`sent`は再実行しない。

ローカル基礎経路は、管理画面のPDF受付、tenant AADを使用した暗号化原本と宛先、既存queue、GhostscriptによるTIFF変換及び実Asterisk SendFAX/ReceiveFAXへ接続する。10 MiB・20ページを上限とし、local fixtureの原本期限は24時間である。本番の保持期間をこの値で確定しない。保管用keyは外部secret fileで与え、backupと別に維持する。

workerはPostgreSQLのrow lockとskip-lockedでjobを取得し、同じsending jobを取得しない。called channelが送信結果を一度だけ報告し、既存event spoolが再送する。受信の一時TIFFはBackendの保管及び履歴確定後だけ削除する。期限切れsendingはDELIVERY_UNCONFIRMEDを表示し、自動再送しない。後から届いた同じattemptの確定成功はsentへ整合させる。旧opaque storage referenceに対応する実adapterがなければINPUT_UNAVAILABLEとして停止し、送れる状態と表現しない。

`FAX_MEDIA_MODE=audio`は実G.711、`t38`はT.38交渉とaudio fallbackを選ぶ。実Cloco・T.38の適合、malware scanの商用連携及び本番提供は未確認である。今回の隔離模擬キャリアによる実FAX通信を実回線成功へ読み替えない。

## 再実行入口と追加boundary

既存`test_phase1_sip_e2e.py`のSIP suiteへ実FAXを追加し、新frameworkを増やさない。SIPpだけではFAX modemの成功・原本保管を確認できないため、同じproduction Asterisk imageから模擬キャリアのFAX endpointを作る。これはcarrier側fixtureだけで、target側は実production route・driver・DB・secret mount・storage関数を保持する。ownerはPhone infra/backend、riskはhigh、scopeは実FAXから最終Backend/UIまで。dependencyは同じAsterisk build、Ghostscript及びBackend PDF/TIFF parser。costはfixture logのwall time・resource計測を正本とし、未計測の上限を推測しない。

failure-local入口は`python3 scripts/test_phase1_sip_e2e.py --fixture fax`。一度成功後の最終経路は既存canonical processでSIP/FAX/UIを一回実行し、同じheavy testを先行・最終で重ねない。`--preflight`は非品質検査、`--fixture database`は実migration診断であり、SIP/FAX/UIの成功を代替しない。
