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
code_paths: [anshin-phone-backend/app/api/routes.py, anshin-phone-backend/app/models/telephony.py, deploy/asterisk/scripts/pbx_fax_worker.py, deploy/asterisk/scripts/pbx_event_spool.py, deploy/pbx-event-forwarder/forwarder.py, deploy/asterisk/config/extensions.conf.template]
contract_paths: [anshin-phone-backend/app/api/schemas.py, docs/specs/changes/2026-10-21-fax-attempt-source-ack.change.yaml]
test_paths: [anshin-phone-backend/tests/test_phase1_api.py, scripts/test_pbx_event_pipeline.py, scripts/test_phase1_sip_e2e.py]
last_reviewed: "2026-10-21"
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
| ACK | Acknowledgement | Backendが対象結果・保護原本・履歴の受理を応答すること |
| DLQ | Dead Letter Queue | 自動配送できなかったeventを保全する既存directory |

## 番号

キャリア払い出し直後は`provisioning`とし、PBXへの到達確認中は`testing`、着信・発信・番号通知・緊急通報条件・履歴を確認後に`active`とする。`active`にはroute targetを必須とし、`released`からの復帰を禁止する。TEL番号とSIP endpointの割当は同一tenantだけを許可し、FAX番号を音声endpointへ割り当てない。

番号の直接指定、標準電気通信番号使用計画、番号名義・利用場所の法令判断はこのAPIのstatusだけでは確定しない。Backendはキャリアから正当に払い出された番号の運用台帳であり、番号使用権を生成しない。

## FAX

送信APIはPDF本体・平文宛先番号をDBへ保存せず、保護ストレージ参照、保護された宛先参照、マスク済み表示値を受ける。同じidempotency keyは同じjobを返す。retryable failureは30秒から指数backoffし、管理画面で受け付けたjobは既定最大3回（既存内部APIのlegacy jobは最大5回）で終端`failed`になる。permanent failureと`sent`は再実行しない。

ローカル基礎経路は、管理画面のPDF受付、tenant AADを使用した暗号化原本と宛先、既存queue、GhostscriptによるTIFF変換及び実Asterisk SendFAX/ReceiveFAXへ接続する。10 MiB・20ページを上限とし、local fixtureの原本期限は24時間である。本番の保持期間をこの値で確定しない。保管用keyは外部secret fileで与え、backupと別に維持する。

workerはPostgreSQLのrow lockとskip-lockedでjobを取得し、同じsending jobを取得しない。callfileからprepareへclaimを引き継ぎ、currentのclaim不一致なら発信しない。PDF/TIFFはjobとclaimの組で分離する。called channelが送信結果を報告し、既存event spoolが再送する。metadata検査の失敗は結果通知を止めず、回収だけを抑止する。期限切れsendingはDELIVERY_UNCONFIRMEDを表示し、自動再送しない。後から届いた同じattemptの確定成功はsentへ整合させる。旧opaque storage referenceに対応する実adapterがなければINPUT_UNAVAILABLEとして停止し、送れる状態と表現しない。

送受信の一時TIFFは、local eventに固定basename・size・SHA-256・tenantと送信claimを保持し、wire payloadへ混入しない。forwarderは同じfileを開いたまま、送信では既存result APIのjob/status/failure_code/tenant、受信ではuploadのdocument ID/type/sizeと履歴のtenant/PBX ID/direction/status/storage参照を照合する。2xxだけでは回収しない。同じACK対象eventをsentへ移した後、読取時と同じ通常fileだけを回収する。HTTP中のevent又は原本の差替え、移動・unlink失敗、結果不明、409、不整合ACK、DLQでは原本を保全する。旧受信eventは同じ保護原本consumerへ配送できるが、事前bindingがない原本は自動回収しない。

DLQの原因修正後は既存forwarderの`python /app/forwarder.py --replay-dead-letter '<basename>.json' --expected-sha256 '<event-file-sha256>'`で指定一件だけをpendingへ戻せる。固定spool内の通常file、hashとevent schemaを照合し、pending同名があれば上書きしない。再送するのは同一ID・claimの結果通知だけで、claim取得・callfile作成・物理FAX再送はしない。unknown・DLQ・孤児原本に日数による自動削除を追加しない。本番原本の月単位保持とS3の31日保護は別の既存ownerが扱う。

`FAX_MEDIA_MODE=audio`は実G.711、`t38`はT.38交渉とaudio fallbackを選ぶ。実Cloco・T.38の適合、malware scanの商用連携及び本番提供は未確認である。今回の隔離模擬キャリアによる実FAX通信を実回線成功へ読み替えない。

## 再実行入口と追加boundary

既存`test_phase1_sip_e2e.py`のSIP suiteへ実FAXを追加し、新frameworkを増やさない。SIPpだけではFAX modemの成功・原本保管を確認できないため、同じproduction Asterisk imageから模擬キャリアのFAX endpointを作る。これはcarrier側fixtureだけで、target側は実production route・driver・DB・secret mount・storage関数を保持する。ownerはPhone infra/backend、riskはhigh、scopeは実FAXから最終Backend/UIまで。dependencyは同じAsterisk build、Ghostscript及びBackend PDF/TIFF parser。costはfixture logのwall time・resource計測を正本とし、未計測の上限を推測しない。

failure-local入口は`python3 scripts/test_phase1_sip_e2e.py --fixture fax`。一度成功後の最終経路は既存canonical processでSIP/FAX/UIを一回実行し、同じheavy testを先行・最終で重ねない。`--preflight`は非品質検査、`--fixture database`は実migration診断であり、SIP/FAX/UIの成功を代替しない。
