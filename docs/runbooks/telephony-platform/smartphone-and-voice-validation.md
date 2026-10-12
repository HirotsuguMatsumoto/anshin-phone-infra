---
schema_version: 2
doc_id: anshin.phone.smartphone-and-voice-validation
title: "スマートフォン実機・音声品質検証"
domain: telephony-platform
document_kind: runbook
scope: product
product: anshin-phone
owner: anshin-phone-infra
authority: reference
status: inventory
risk_level: high
source_doc_ids: []
consumers: [anshin-phone-infra]
code_paths: [scripts/create_sip_enrollment_bundle.py, scripts/evaluate_voice_quality.py]
contract_paths: []
test_paths: [scripts/test_device_and_voice_tools.py]
last_reviewed: "2026-08-21"
review_interval_days: 30
sensitivity: internal
---

# スマートフォン実機・音声品質検証

## 専門用語一覧

| 用語 | 正式名称・読み方 | 意味・本書での扱い |
| --- | --- | --- |
| SIP | Session Initiation Protocol | IP網上で電話の発着信や通話sessionを制御する通信規約 |
| IP | Internet Protocol | パケット通信網でデータの宛先と配送を制御する通信規約 |
| VPN | Virtual Private Network | public network上に暗号化等でprivateな通信経路を構成する仕組み |
| Git | Git | ファイルの変更履歴とブランチを管理する分散型バージョン管理システム |
| QRコード | Quick Response Code | カメラ等で読み取る二次元コード |
| PBX | Private Branch Exchange | 内線、外線、着信振分け及び転送等を制御する電話交換システム |
| RTP | Real-time Transport Protocol | SIP等で確立した通話の音声データを運ぶ通信規約 |
| OS | Operating System | computerや端末のhardwareとapplicationを管理する基本software |
| JSON | JavaScript Object Notation | keyとvalueの構造でデータを表現するテキスト形式 |
| repository | Repository | source code、文書及び変更履歴を一まとまりで管理する単位 |

## 端末登録

Phase 1はiOS・Android各1台を対象に、標準SIP、Digest認証、outbound proxy、G.711 μ-law/A-lawを扱えるクライアントで検証する。到達可能な固定IP又はVPN内IPから登録し、端末ごとに異なる内線・credentialを発行して共有credentialを禁止する。設定用バンドルはGit外へ`0600`で一度だけ作成し、端末取込直後に削除する。QR画像化する場合も同じ有効期限（最大15分）と削除条件を適用する。

```bash
python3 scripts/create_sip_enrollment_bundle.py \
  --host sip.example.invalid --extension 2001 \
  --password-file /protected/path/device-secret \
  --output /protected/path/enrollment.json
```

端末紛失・退職・再設定時は、PBX側credentialを先に失効し、既存contactが消えたことを確認してから再発行する。端末上のアカウント削除だけを失効として扱わない。

## 実機合格条件

Wi-Fi、4G/5G、アプリforeground/background、端末再起動後でREGISTER、着信、発信、保留、復帰、切断を確認する。初期検証ではSIP/RTPを全世界へ開けず、許可済み固定IP又はVPN経路を使う。Push着信はPhase 2の独立要件とし、Phase 1のOS常駐可否と混同しない。

## 音声品質

固定電話・携帯電話との各方向で30分通話を行い、双方向音声、packet loss 1%以下、jitter 30ms以下、RTT 300ms以下、MOS 3.6以上、予期しない切断0件を合格条件とする。測定値だけを個人情報のないJSONへ記録し、次で判定する。

```bash
python3 scripts/evaluate_voice_quality.py /protected/path/measurement.json
```

通話録音、実番号、SIP credential、相手先番号はリポジトリへ保存しない。


## 基礎管理との連動

端末設定のownerはBackendのactive endpointである。実Asteriskは内部APIから同じtenantの設定を読み、端末ごとのpasswordを適用する。番号停止・割当解除は新規発着信のroute照会で拒否する。端末停止・失効は設定から当該endpointを除き、旧credentialでのREGISTERを拒否する。既に成立した通話の終了を待つ。

設定bundleの`expires_at`及び`consume_once`は取込・削除のclient側運用条件であり、PBXが同じSIP passwordを15分後に自動失効させる証明ではない。実際のcredential lifetimeは端末停止・失効までである。Backend APIは卸トランク資格を返さず、operatorは自分がownerの端末設定だけを取得できる。

## 無料Softphoneの採用比較と端末挙動

2026-10-12の既存Android/iPhone資産はFlutterの職員・顧客アプリである。両方にAppAuth、secure storage、Firebase Messagingがあり、SIP SDKはまだ組み込まれていない。Phone専用の端末認証を既存のログインと分離せず、AAL2後の自分の端末設定APIを使用する。今回の隔離prototypeはその実Backend設定を実PBXとSIPpへ渡す。顧客端末へ卸資格を渡さない。

| 選択肢 | Android / iPhone | 利用条件と継続費用 | 今回の扱い |
| --- | --- | --- | --- |
| PJSIP native SDKをFlutter platform channelから使用 | 両OSでnative SIP/mediaを扱う | GPL v2以降又は商用license。閉じた商用配布の条件を自動確定しない。native橋渡し・OS更新・着信統合の保守が必要 | protocolの互換確認を先行、SDK組込と購入は未実施 |
| Linphone SDK | 両OS向けSDK、Push連携機能 | GPL v3又は商用license。配布条件、Pushサービス条件及び見積り確認が必要 | SDKとPush費用の採用比較候補 |
| 既存Flutterの認証・設定画面を再利用 | 両OSの既存資産 | 認証・secure storageの既存保守を再利用。SIPとnative着信統合は別途必要 | 共通設定APIを実装済み |

primary source: [PJSIP license](https://docs.pjsip.org/en/2.17/overview/license_pjsip.html)、[Linphone FAQ](https://www.linphone.org/en/faq/)、[Linphone SDK](https://wiki.linphone.org/xwiki/wiki/public/view/Lib/)、[Push integration](https://wiki.linphone.org/xwiki/wiki/public/view/Lib/Features/Push%20notifications/)。アプリ無料配布はSDK license、APNs/FCM運用、OS追従、障害対応及び通信原価がゼロという意味ではない。商用見積り・人員工数を未取得のため金額を捏造しない。

バックグラウンド・スリープ・OS終了時はPush受信からnative着信画面へ接続し、SIPの常時foreground動作だけで合格扱いにしない。iPhoneは[PushKit / CallKit](https://developer.apple.com/documentation/pushkit/responding-to-voip-notifications-from-pushkit)、Androidは[Core-Telecom](https://developer.android.com/develop/connectivity/telecom/voip-app/telecom)の要件へ接続する。通知権限拒否は設定画面で可視化し、着信保証を表示しない。回線切替は古いtransport/contactを閉じ再REGISTERし、通話中の切替失敗を履歴の切断と区別する。Push重複とSIP再送は同じcall IDへ束ね、応答は一つのsessionだけが取得し、他端末へ終了を伝える。これは設計であり、実機の動作証明ではない。

紛失時は管理者が端末を失効し、新しい端末IDと資格を発行する。交換時に旧端末の資格を移植しない。一時停止は再開可能、失効は復元不可とする。通信障害時は通話中・新規登録不可・着信未確認を区別し、既存の代替連絡手段と問い合わせ窓口を案内する。無料端末の対応OS、商用SDKの採用、Push運用とサポート体制は実機qualification後に確定する。

今回の自動入口は既存`test_phase1_sip_e2e.py`である。設定取得・REGISTER・発着信・合成PCMUの双方向packet・停止後の旧REGISTER拒否を実runtimeで確認する。packetの成功を人の聴感、30分MOS、Wi-Fi/モバイル切替、OS終了、Push・重複応答の実機成功へ読み替えない。

## 復旧とローカル資源観測

既存`create_phase1_backup.sh`は同じCompose inputsと独立backend rootを読み、DB dumpと暗号化FAX原本をGit外の0700/0600領域へ保存する。keyはbackupへ含めない。snapshot前に今回所有のproducerをpauseし、完了後にunpauseする。live業務の別writerがある環境では整合したsnapshotとして扱わない。

既存SIP/FAX fixtureの最後に、別DBと別原本directoryへ復元し、actual production readerで同じtenantの原本を復号・検査する。検査後に復元用DBとdirectoryだけを削除する。これは隔離localのlogical restoreであり、host障害・外部backup保管先の復旧証明ではない。切戻しは同じsource、schema、key、原本の組を戻す。新schemaのtenant間で同じPBX IDを使った後に旧global unique indexへdowngradeすると競合するため、旧versionへの無条件downgradeを許可しない。

同じfixtureで2通話、1FAX、2合成通話のMixMonitor録音を同時に実行し、DockerのCPU/memory、active channel数、録音byte数を一つのoverlap sampleとして保存する。録音は今回の合成通信だけで、原本確認後に削除する。負荷限界、長時間性能、障害時容量、production capacity又は顧客録音保管機能の合格値へ読み替えない。新しいsuite又はmonitoring frameworkを追加しない。

`PHONE_PREVIEW_DIR`を明示した成功runは同じproducerとUIをownerの最後のbrowser consumerまで保持する。source SHA、Compose argv及び所有projectを外部runtime metadataへ記録する。既存directoryへの上書き、失敗runの保持、foreign projectのcleanupを許可しない。確認後は記録された同じCompose inputsから所有projectとmanagement UIだけを削除する。
