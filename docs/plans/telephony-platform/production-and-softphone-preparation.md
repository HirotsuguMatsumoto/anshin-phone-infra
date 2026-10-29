---
schema_version: 2
doc_id: anshin.phone.production-and-softphone-preparation
title: Phone 本番準備・ソフトフォン技術検証計画
domain: telephony-platform
document_kind: plan
plan_state: proposed
scope: product
product: anshin-phone
owner: anshin-phone-infra
authority: reference
status: draft
risk_level: high
source_doc_ids:
  - anshin.corporate.anshin-phone.foundation-development-instructions
  - anshin.corporate.anshin-phone.notification-status
  - anshin.infrastructure.system-architecture
  - anshin.infrastructure.mac-codex-ms-a2-runtime-migration
  - anshin.runbook.system-architecture.ms-a2-server-access
  - anshin.governance.privileged-operation-gateway
  - anshin.release.contract
  - anshin.release.impact-gate
consumers: [anshin-phone-infra, anshin-phone-backend, anshin-frontend-monorepo]
code_paths: [scripts/phone_postgresql_backup_adapter.py, scripts/production_runtime.py, compose.production.yaml]
contract_paths: [docs/specs/changes/2026-10-29-cloco-provider-alignment.change.yaml, docs/specs/changes/2026-10-13-phone-preparation-navigation.change.yaml, docs/specs/changes/2026-10-17-phone-vm-native-architecture-sync.change.yaml, docs/specs/changes/2026-10-20-filing-acceptance-cloco-intake.change.yaml, docs/specs/changes/2026-10-21-phone-backup-maintenance.change.yaml, docs/specs/changes/2026-10-21-phone-backup-deploy-transition.change.yaml, docs/specs/changes/2026-10-21-phone-softphone-internal.change.yaml, docs/specs/changes/2026-10-22-own-call-history.change.yaml]
test_paths: [scripts/build_check.sh]
last_reviewed: "2026-10-29"
review_interval_days: 30
sensitivity: internal
---

# Phone 本番準備・ソフトフォン技術検証計画

## 専門用語一覧

| 用語 | 意味・本書での扱い |
| --- | --- |
| LXD VM | LXD Virtual Machine。Core/Authから分離するPhone専用仮想マシン |
| SHA | Git Commit SHA。source・検証・統合を識別する固定commit |
| SIP / RTP | Session Initiation Protocol / Real-time Transport Protocol。端末登録・通話制御と音声伝送 |
| SDK | Software Development Kit。通話機能を組み込む開発library |
| GPL / AGPL | GNU General Public License / GNU Affero General Public License。componentごとに適用条件を確認するOSS license |
| Push | バックグラウンド着信等の通知。実機と実providerの確認を模擬試験で代替しない |
| Release Plan | 既存release規程が定める機械可読入力。本書の作業計画とは区別する |

## 位置付け

ownerの本番反映依頼と基礎開発指示に対する準備計画である。配置、費用、SDK採用、UI/UX又は商用提供の承認書ではない。本書をmain統合・releaseの追加開始条件にせず、正規check、Release Plan、既存runner及びgatewayを再利用する。

事業・行政・契約は[Phone総合資料入口](https://github.com/HirotsuguMatsumoto/anshin-corporate-strategy/blob/main/documents/plans/anshin-phone/README.md)、機能・検証は[Backend運用契約](https://github.com/HirotsuguMatsumoto/anshin-phone-backend/blob/main/documents/specs/telephony-platform/foundation-runtime.md)と[UI資料入口](https://github.com/HirotsuguMatsumoto/anshin-frontend-monorepo/blob/main/apps/anshin-phone/documents/README.md)を参照する。

## 2026-10-29 Cloco標準接続を先に成立させる再設計

[Cloco接続仕様](../../specs/telephony-platform/cloco-sip-trunk-interface.md)を技術詳細の参照先とする。上流を当社暫定実装へ合わせる前提を廃し、最初はCloco標準トランク↔当社Asterisk↔社内SIP端末で確認する。製品段階でKamailio/RTPengineを端末側へ組み込み、上流はAsteriskで終端する目標へ変更する。物理接続口・到達経路は未選定で、現在のprivate VM・outbound REGISTERだけで成立するとしない。既存carrier用Composeは目標へ未対応で、後続実装・検査・実回線受入が必要。管理・native認証の受入済み経路は保全し、telephonyは無効のまま。既存ポート転送制約の無断解除、新調達・公開・Cloco特別対応の要求は行わない。

## 実装・検証・配備を分けた現在状態

| 対象 | 確認済み | 未確認・未実施 |
| --- | --- | --- |
| 基礎管理経路 | 実Docker、隔離Auth、Backend、実PBX、架空番号・模擬carrierを通す番号/端末管理・通話・G.711 FAX・監査・隔離復元 | 実Cloco、実番号、T.38、顧客通信、商用容量 |
| 管理画面 | 説明iconのclick/Escape、必要状態・エラー・FAX制限表示。対象画面の自動試験・右サイド実browser確認。ownerの「画面問題ない。本番反映お願い」により当該画面の本人確認受領済み。公式 https://phone.anshin.care で本番Google loginと管理6画面を確認 | h-test3の再登録完了を本番管理画面で読取済み。別Chromeでの再ログイン・MFA通過はowner報告により完了 |
| source | Backend `7770e877b2901d1b99c09cf32606f8abdc55178d`のruntime変更、Infraの既存runtime変更、Frontend `ba6bcbdb97cc4d80c0f45cb0c4aebb2e3d301c57`の説明・文書整備をmainへ統合 | source統合を本番提供と扱わない |
| 本番adapter | MS-A2-1専用VM・管理API/DB・公式公開・本番Google認証・実S34世代・同世代DB/FAX隔離復旧と両timer有効化を2026-10-20に受入 | 中央generic経路の完成は専用operationの受入から推定せず、中央runnerの実装・検査・release結果で判定。定期実発火と証明書更新切替の実施結果を別記 |
| 無料Softphone | 10/21、画面・操作設計とPJSIP 2.17社内評価の独立package実装scopeを本人承認。既存職員アプリを変更せず実装・隔離検査中 | 商用配布license・本番mobile認証/Push binding・Android/iPhone実機・背景着信・通信切替・音声品質・本人実UI最終確認 |

runtime codeが変わっていない文書commitを、新しい実通信成功SHAへ読み替えない。正式な詳細結果はinstruction originの既存Git外証跡で管理し、秘密、一時path、原本又はraw観測結果を本書へコピーしない。

## 配置判断に使う観測と限界

2026-10-12 23:56:43 UTC、統合済みGov source `ec0000440c82fd91594ca827fd26142687de6878`の既存`inspect-core-host-recovery-v1`から、次の公開resource fieldを観測した。観測schemaを既存validatorで確認済みであり、容量受入ではない。

| MS-A2-2の項目 | 観測・設定 | 解釈の限界 |
| --- | --- | --- |
| CPU | 8 sibling組、16 thread | SMT siblingを別物理coreとして数えない。Phoneの専有CPUは未割当 |
| 物理memory | 約29.08 GiB、MemAvailable約6.26 GiBの瞬間値 | MemAvailableを継続的な割当可能量へ読み替えない |
| Core / Auth VM | running、設定memoryは18 GiB / 7 GiB | 今回の準備で縮小・restartしない。memory peak fieldの0を負荷上限の証明にしない |
| NVMe | 1台、約1TB | 第2台、mirror、off-host復旧又はPhone保存容量の証明ではない |
| Phone | `anshin-phone` projectなし、`ms-a2-2-phone` VMなし | sourceに予定配置があることと、実配備を区別する |

旧未統合branchのPhone 5 GiB候補を現在のCore/Authへそのまま加えると30 GiBとなり、host分を含める前に物理量を超える。旧候補を適用しない。実負荷・必要余裕・storage・復旧経路を確認し、既存サービスを変えない配置案を具体化する。

MS-A2-1の初回読取は開発VMのDocker subnetと社内LANの重なりによって停止した。ownerのoperation登録・両origin対応指示を受け、統合済みGov source `2e17033a9fae5798de6faddc131451031ee3acdb`の登録operation `configure-ui-worker-route-v1`をANSHIN_UIで実行した。固定Worker宛一件のreadbackは`ready: true`、既存Core/Docker経路とbootは不変である。kernel一時経路のため`persistent: false`であり、再起動後の自動復旧を受入済みと扱わない。共通入口と責任分界は`anshin.governance.privileged-operation-gateway`を参照する。MAC経路は登録・自動試験・独立source review済みだが、実MAC端末からの実行は未確認である。

修復後、同じ統合済みSHAの既存`inspect-worker-host-recovery-v1`による観測を既存schemaで検証した。MS-A2-1は`running`、failed unitは0、固定GUI VMと既存三workerは`running`だった。物理memoryは約29.08 GiB、MemAvailableは約10.87 GiBの瞬間値、root空きは約99.75 GiBである。これらはPhone専用VMの割当・負荷・容量・復旧受入を代替しない。今回のoperationはPhone VMを作成せず、既存サービスの資源割当を変更していない。この観測時点ではMS-A2-2の専用VM予定だった。現在の初期構築候補と新しい実読取は、次節の2026-10-17記録を参照する。旧瞬間値だけを配置・容量受入の根拠にしない。

### 2026-10-17のMS-A2-1初期構築と未受入事項

統合済みGov `ddaf5059f6754ed8ee98990032565d58b84ed86a`の登録Worker observerをMacから実行した。物理memoryは約29.077GiB、MemAvailableは約26.714GiBの瞬間値、固定LXD保存先の同一filesystem（device 64512）空きは約99.2566GiBだった。LXD5.21.8はdefault projectだけで、VM・pool・managed networkは未作成。Ubuntu24.04/x86_64の公開VM image fingerprintは`d4ff18198fb2ed8c88d408421e610c143cf1f5c1c0178e57178fb586880c3e56`である。image本体の取得・VM作成はこの観測に含めていない。

Core/Authの18/7GiBを維持し、MS-A2-1にPhone専用project `anshin-phone`、VM `ms-a2-1-phone`、dir pool `phone-pool`、default project managed bridge `phone-br0`を置く初期構築案を採用し、同日の登録済みreleaseからVM bootstrapを構築した。共有2vCPU・memory4GiB・root32GiB、subnet `10.91.40.0/24`のGW `.1`・guest `.10`を固定する。将来worker17GiB＋Phone4GiB＋host/QEMU設計割当6GiB＝27GiBを物理量へ照合した。host6GiBは実測peak又は既存予約ではなく、同時負荷・商用通話容量の受入ではない。

同一filesystemの初期予算80GiBはguest32・image8・temp/rollback16・hostgrowth24の設計割当である。再開時は検証済み保存先と固定imageの実allocated blocksだけを控除し、疎fileの論理sizeを空きへ足さない。guest32GiB内にOS、image、DB/WAL、FAX、backup・隔離restoreの一時領域を収められるかは、VM構築後の実測事項として残す。GUI保全diskを再利用・削除しない。

固定入口`provision-phone-vm-v1`は既存origin、Worker carrier、sudo資格、release.lock、Release Plan DEPLOYと標準receiptを使う。Phone専用guardを最初の通信前に適用し、Core/Auth/既存workerを停止・再起動しない。main `ee519f2d28f4c0e8350511cc07ceaa3b14f90260`、release `release-2a5c6f2351cad4963ae8339b`の標準plan/transport receipt consumerからVM/bridge/pool構築とbootstrap成功を照合した。Docker 29.1.3・Compose 2.40.3+ds1-0ubuntu1~24.04.1・agent active、SSH masked・root locked・interactive account 0、既存worker IDとhost boot不変、LXD operation終端を確認した。autostartは設定後の読取まででhost再起動試験は未実施、商用容量未受入・本番API/公開/復旧未完了である。Phone writerが構成正本・移行計画B3・復旧計画・七ページ図へ同じ結果と未受入を同期する。

今回apply前のinspect（既存VM Running時）で物理memory31,221,350,400 bytes、MemAvailable27,514,101,760 bytes、同一filesystem空き103,018,164,224 bytesを観測した。`remaining_memory_budget_bytes=6,442,450,944`はこの状態で要求する最低MemAvailable閾値6GiBであり、実測残容量やPhone4GiB控除後の計算値ではない。これらは初期配置の観測・設計条件であり、負荷時の保証ではない。guest root空き29,706,870,784 bytesをhost空きへ加算しない。`vm_capacity_accepted=false`、`public_proxy_installed=false`を維持する。

Phone guestのproduction RuntimeはAPIを固定private IPv4 `10.91.40.10`へbindする設計とする。直接のmanagement Composeはloopbackを既定とし、既存の実Docker fixtureも明示loopbackで動作する。描画値と実containerのHostIp/HostPortは区別して検証し、private ingressとEdgeの閉じた公開経路は後続の中央releaseで同期する。今回のsource変更だけでAPI公開済みとは扱わない。子processの回収が確認不能な場合は追加cleanup/migration/rollbackを続けず、既存の失敗enumで未確認として保全する。Phone app未配備・shared producerがPhoneを拒否・新timer未導入の状態に限り、guest lockを`/tmp/anshin-ms-a2-1-platform-release.lock`、backup source IDを`ms-a2-1/phone-postgresql`へsource上で先行同期する。旧lockでactorが稼働する状態へこの順序を一般化しない。実backup/restoreの有効化前にはshared側も同じMS1 lockと未解決retention actor除外へ同期し、実consumerで確認する。

## 本番反映へ向けた実装単位

| 作業 | 対象・既存資産 | 完了に使う結果 |
| --- | --- | --- |
| 配置と資源 | 既存host observer、Phone専用VM。Core/AuthのVM・DB・volume・credentialは分離 | 実targetと必要資源・保存・復旧経路の事実。未測定値や旧案のPASSではない |
| 配備adapter | InfraのCompose・既存backup/restore、中央release registry/matrix、既設admin alias。中央matrixの`phone-backend`はstandalone配置へ同期済み | 中央正規経路による管理専用の本番配備・公式公開・同世代隔離復旧を受入済み。2026-10-21の記録を参照。実carrier・商用容量とは別 |
| 実入力確認 | Backend Settings、DB migration、Auth `anshin-phone` client、issuer/JWKS/audience、frontend API origin | 今回の実env/configを各consumerが受理する軽い確認後、対象の実業務integration。local Auth成功を本番Auth確認にしない |
| UI配備 | 現行frontend、既存hosting/release owner | Phoneの実project/公開経路・domain・権限・費用条件。Phone projectと既存release bindingの未確認を登録済みと扱わない |
| 保管・復旧 | 既存保護FAX・DB backup/隔離restore・rollback実装 | Phone専用の実保存先、保持期間、暗号化入力、隔離restore、既存ownerによる結果確認。新trust/journal/署名/gateを追加しない |
| 最終確認 | 対象UI、既存自動試験、instruction-originの実Docker・右サイドbrowser | AIの確認と指示者本人の明示確認を分ける。管理/MFAの実確認は本番で行い、架空stgを停止条件にしない |

各作業のcheckは既存owner/selectorが選ぶ変更範囲だけを使う。同じ固定入力のheavy試験を重ねず、sourceが変わらない経路を「念のため」全件再試験しない。releaseの業務判断は既存runnerが一回所有し、transportへ複製しない。

費用が発生し得るVM追加資産、hardware、hosting、off-host保管、外部secret/provider/Push等は、実契約・resource・料金・期間を先に確認する。追加費用を確認できない操作は実行せず、目的・対象・見積り・未確定項目・単発/継続・期間を示してownerの具体的指示を得る。既存CIの通常利用はownerの確認不要例外を適用する。内部DB/password/HMAC/FAX keyを、外部provider資格4件や有料Secret Manager作成へ自動的に置換しない。

電気通信事業届出は、2026-10-20に通知書原本から受理・当社A-08-24437（届出日10月2日、通知日10月16日）を確認済み。事業側正本 `anshin.corporate.anshin-phone.notification-status` を参照し、受理待ちへ戻さない。番号計画の当社への適用・必要手続、Cloco契約・実SIP/RTP/FAX/channel条件と資格は未確認として個別照合する。資格台帳と許可済みprimary設定の確認前に再共有を要求しない。基礎管理基盤の本番化、実回線、顧客開通及び商用提供を区別し、受理通知だけで実回線を有効化しない。助成対象4機能は先行実装しない。

## Softphoneの技術比較と次の検証

2026-10-12の候補調査を経て、10/21に公式release・license・FAQを再確認し、社内評価用SDKをPJSIP 2.17、公式commit `5a457451fa2712ba18e12b01738e8ff3af2b26fd`へ固定した。無償のclosed-source商用licenseや配布条件への適合を推測しない。vendorへ連絡・契約・購入・account作成はしていない。

| 候補 | 公式情報と適用確認 | 既存資産との関係・未確認 |
| --- | --- | --- |
| PJSIP | [公式license](https://www.pjsip.org/licensing.htm)はGPL v2以降又は別途proprietary条件。third-party条件も確認する | native wrapperとFlutter連携、対象version、保守・再接続・実機音声・Pushは未検証。proprietary価格は未確認 |
| Liblinphone | [公式software/license案内](https://www.linphone.org/en/voip-software/)はGPLv3/AGPLv3又はproprietary条件。[SDK案内](https://www.linphone.org/en/liblinphone-voip-sdk/)にはJava/Kotlin・Swift wrapperとMaven/Cocoapod連携がある | Flutterはnative boundaryが必要。実component/versionのlicense、構成、保守、Push、実機品質とproprietary価格は未確認 |

公開source方針・proprietary採用・支出を本計画で決定しない。採用候補とUI/UX詳細設計を具体化してownerへ提示し、同意の必要な部分だけを確認する。既存Flutter認証・secure storage等の再利用は、当該アプリへの無断統合や他製品資格の転用を意味しない。

検証するUI状態は、ログイン、端末設定取得、登録/未登録、発信、着信、通話中、通信断/再接続、権限拒否、端末停止/失効である。説明は共通icon＋Popper、必要状態とエラーは常時表示とし、新UI実装前に詳細設計を提示する。

隔離の実SDK driverで登録・発着信・双方向音声・再接続・失効を確認し、その成功条件を既存suite/fixture/ownerへ固定する。背景/スリープ、OS終了、通知/マイク権限拒否、Wi-Fi/モバイル切替、重複着信、応答競合は両OSの実機と実Push consumerまで確認する。模擬SIP試験をAndroid/iPhone SDK・Push成功へ読み替えない。卸トランク資格を顧客端末へ配布しない。

2026-10-21に同じMacの既存toolchainを読取り、Flutter 3.44.2/Dart 3.12.2、Xcode 26.6/iPhoneOS SDK 26.5、Android API 34/35/36・adb 36.0.2の所在を確認した。install/build、署名qualification、接続実機、Phone Push資格、SDK実装の成功ではない。Git外の既存案件設計書へSDK条件・Push・実機計画と新UI詳細を整理し、同日の本人回答で画面・操作設計§4の事前承認を受領した。続いて本人からPJSIP 2.17の社内評価用独立package・Phone専用API consumer・最小native bridge・既存隔離PBX fixtureの追加実装scopeを承認済み。商用license確定・購入・Store公開・実Cloco開通・本番mobile client/Push binding・実機/マイクは含めず、実装後の本人実UI最終確認も未受領。他製品資格を転用せず、native未確認を完成した基礎管理経路の追加品質gateへ変更しない。


## Macでの再開と管理用配備定義（2026-10-16）

Macのcurrent integrated sourceの既存host observerからCore/Worker両hostを読取できた。今回のMac接続にGUI VMのWorker経路修復は不要であり実行していない。この10月16日観測ではPhone project/VMはmissingで、Core/Authの設定18/7 GiBを変更していない。10月17日の構築実績は上記のMS-A2-1初期構築節を参照する。物理memory約29.08 GiB、Core側MemAvailable約5.32 GiB、Worker側約11.42 GiBは今回の瞬間観測であり、Phone容量受入ではない。旧5 GiB候補を適用しない。

Postgres・Backend・migrationのsource定義は`compose.management.yaml`が所有し、既存Phase 1と`compose.production.yaml`がextendsする。production管理定義は実carrier入力・SIP/RTP公開・source buildを含まず、Backend/migrationの同じfixed digest image、owner指定の本番FAX月単位policy及び既存secret-file入力を要求する。BackendだけにAuth/JWKS取得用egressを接続し、DBはinternalのまま維持する。

管理定義は`ANSHIN_PHONE_TELEPHONY_ENABLED=false`であり、既存Backendの管理・履歴は使えるが、端末資格・PBX・FAX送信/dispatchは503となる。既存のqueued/sending行を変更しない。実機資源、API ingress、Phone hosting binding、独立key復旧・backup/隔離restoreの実受入を経て管理専用adapterを中央正規経路で配備済みである。sourceのrender成功と、本番Auth・実回線・商用通話容量の受入を区別し、以下の実結果と未確認事項を参照する。


## FAX保護原本の月単位保持（2026-10-16 owner回答）

ownerは「Clocoと同じ月単位（毎月5日に前月分を削除）」を指定した。production ComposeはBackendとmigrationへ`ANSHIN_PHONE_FAX_RETENTION_POLICY=cloco_previous_month`を渡し、Backendに継承されたlocalの秒数defaultを空へ上書きする。保存受付月の翌月5日00:00 JSTを期限とし、原本だけを対象とする。既存S3標準31日・通信履歴・監査の保持は変更しない。境界、replay、catch-up、削除範囲のsourceとconsumer契約は`anshin.phone.backend.foundation-runtime-contract`を正本とする。

既存Phone backup adapterの`--purge-expired`から、production Composeの`backend-retention` maintenance serviceで同じfixed imageの`python -m app.core.fax_retention`を呼ぶsourceを追加する。UID/GIDは10001:10001、restartなし・公開portなし・DB用internal networkだけを使う。systemdの`anshin-phone-fax-retention.timer`は毎日00:00 Asia/Tokyoに実行し、Persistent catchupで毎月5日期限の取りこぼしを回収する。VM・管理API/DBと専用backup adapterは実配備済みであり、両timerのenable/active読取まで受入済みである。sourceやCompose検証・enableを実発火成功へ読み替えない。PBX一時TIFFとdead-letterのcleanupはtelephony有効化前の別受入事項として残す。


## Phone PostgreSQL専用backup資源の具体化

既存中央owner `scripts/postgresql_backup_storage.py` のPhone projectionを使い、既設classをPostgreSQL専用へ展開する。正本のbucket名は `anshin-prod-phone-postgresql-backup-691862619128` とし、既存Roles Anywhere anchorとPhone VM用のwriter/restore CNへ限定する。専用bucket・writer/restore role・writer/restore profile・bucket policyの6資源であり、他製品stackを変更しない。

DB backupはownerのKMS廃止指示に合わせ、既存age暗号化・manifest検証とSSE-S3（AES256）を使う。新しいKMS key・alias・権限を作らない。Governance 31日、Versioning、purposeごとの最小権限を維持し、元templateの30日expirationを持ち込まない。FAX・録音のbucketとprincipalをDB backupと共有しない。新規bucket等の実作成は最新費用規程に従う。共通SSE-S3 producerとrestoreの先行統合前に、このprojectionだけで本番backup適合済みとは扱わない。source、ValidateTemplate又はstack作成の成功を4世代backup・隔離restoreの成功へ読み替えない。

FAX保護原本のoff-host backupは別projectionとし、`anshin-prod-phone-fax-691862619128`、`fax/*`専用のwriter/restore role/profileを使う。DBとFAXは各6資源、合計12資源で相互アクセスを許可しない。FAXはBackend既存の保護原本暗号化と独立した復旧鍵保管を維持し、S3にはSSE-S3で保存する。FAXの通常原本はBackendの月単位期限に従い、off-host backupは31日保護を維持する。bucketへ自動expirationを追加しない。通信停止中の録音用資源は今回作成しない。

## Phone専用guestのnative配備owner

`scripts/production_runtime.py` は固定Phone guest内のDocker daemonで、既存production Compose、固定digestのBackend/PostgreSQL、実Settings検証、migration、readiness及び失敗時のBackend rollbackを担当する。中央release ownerがsourceとartifactの資格・既存release receiptを所有し、このscriptはGit取得、image build、署名、journal又はreceiptを追加しない。CLIのDocker接続はguest内socketへ固定する。fixtureのtransport指定だけをconstructorで明示する。

非secretの実行設定は `/var/lib/anshin-phone/release/runtime.json` に保持する。healthは実container image、Settings、DB readiness及びCompose healthを読み、profileのSHAだけで成功を判定しない。既存DBの更新では既存Phone backup adapterを共通lock取得前に呼び、lock取得後にprofileと実container・volume観測が不変であることを確認する。既存DB/FAXをprofileなしで自動採用しない。migration中断時は所有one-offを停止し、旧Backendの実healthが成功した場合だけrollback成功を返す。初回失敗はBackend停止を確認し、DB/FAX volumeを残す。

初回失敗結果のcandidateとresource snapshotは、Runtimeが同じrelease lockを保持している間に一緒に取得する。lock解放後の別candidateの資源を旧candidateへbindしない。初回失敗後のforward repairは、中央ownerの既存標準failed receiptがbindする同じcandidateと、実container・volume観測の完全一致を受け取る場合だけ許可する。volumeは名前やlabelだけで採用せず、固定driver/scope/options/mountpoint/created時刻/Compose属性と実backing directoryのdevice/inodeを照合し、読取前後のvolume属性不変を確認する。profileなしの未知資源、同名の再作成、inode不一致又は確認不能は保全して拒否する。fixtureはdaemon側の実mountpointをreadonly bindで読み、消えたvolumeを自動再作成しない。実Dockerで初回health失敗からの同candidate復旧、DB rowとvolume実体の保全、foreign identity拒否を確認する。この検証は本番保存・隔離restoreの成功とは別である。

共有backup ownerとの接続、管理専用の実配備fixture、host容量受入及び中央Phone operationの接続は別々に実確認する。native ownerのsourceだけで本番配備adapter全体の完成又は本番反映を宣言しない。DB rollbackは自動実行せず、適用するmigrationが旧Backendと互換であることを中央change contractで扱う。source更新とprofile更新の間で中断した場合は、既存中央release結果と実container imageを照合してから復旧する。

## 既存PostgreSQL ownerへの専用入力

`scripts/phone_postgresql_backup_adapter.py --scheduled-backup` はnative `runtime.json` と実Backend healthを照合し、実Postgres container ID・Backend source SHAを、既存 `backup_postgresql_to_s3.sh` へ渡す。専用bucket、`postgresql/phone` prefix、Phone writer role/profile、`/etc/anshin-phone/aws/config` と専用鍵pathだけを使い、他製品のAWS環境・KMS入力を継承しない。`/etc/anshin-phone/postgresql-backup-profile.json` はowner-onlyで、`manifest_key_id`、配備元の `governance_sha` / `infra_sha`、検証済み公開bindingの `public` を持つ。`public` にはPhone専用role/profile、共通anchorと資格の固定数値versionを記録し、秘密値は格納しない。

共有producerがPhoneを許可し、同じMS1 guest lock取得後に `POSTGRES_BACKUP_EXPECTED_CONTAINER_ID` と実containerの一致及び固定retention actor不存在を検証してからinstallする。shared restoreにも保存操作前の同じ未解決actor除外を適用する。現行未対応の共有sourceへKMS値を偽装して接続しない。adapterのsource又は単体testだけで本番backup適合済みとは扱わない。共有ownerがage・SSE-S3・exact version readback及び既存receiptを所有し、adapterは別receipt/journalを作らない。

同梱のservice/timerは既存PostgreSQL unitを再利用し、毎日04:30・10:30・18:30・23:30（Asia/Tokyo）の4回、Persistent catchup、共通guest lock及び限定retryを使う。定義の追加はinstall・enable・定期実行の証拠を代替しない。初回取得、4世代、隔離restore、FAX backup及び復旧鍵別保管は引き続き実受入を必要とする。

FAX retentionは同じguest lockを取得してから固定one-offの不存在を確認する。作成が返した64桁IDと実name・project・service・oneoff・image・userが一致した場合だけ、そのIDを使ってwait・stop・rmし、最終absenceを確認する。create応答喪失、未知ID、metadata不一致又はchildren unknownを名前で採用せず保全する。Runtimeのlock取得後も、stoppedを含む未解決retention actorが残っていれば保存操作を始めない。source切戻しは削除済み原本を復元しない。削除済み原本の復旧可否は、独立した既存backup・保持・隔離restoreの受入で判定する。新timerはshared backup/restore整合と実consumer検証後に既存installerから導入する。

### Phone専用本番backupの実行adapter

固定MS-A2-1 Phone guestへ既存`deploy-phone-backend-v1`のstdinから資格を配布し、共通PostgreSQL producer/restoreを使用する。新SSH入口・CA秘密鍵のguest配布・別receiptは作らない。承認済み共通issuerの実anchor `916219bc-2500-4f73-a7b2-82e0c94ec215`とPhone専用4 role/profile、11 credentialの固定数値versionを受け付ける。旧anchor/他製品資格へfallbackしない。

producerは同じguest lock下でPhone writerを止め、native DB dumpと暗号化FAX原本を同じcutoffへ固定し、age/SSE-S3・31日保護・exact object versionを既存manifestへ記録する。GOVERNANCE31日は削除期日ではなく、今回の自動削除を追加しない。FAX運用原本の毎月5日前月分削除とは区別する。復旧鍵はSecret Managerへ別障害領域で保管し、対応するS3 objectが残る間は旧鍵も保持する。

隔離restoreは同じmanifestが指すDB/FAX object versionとbackend imageを使用する。DB schema/件数、実backendのFAX復号・tenant拒否・有効期限・監査履歴を確認し、本番DBへ書き込まない。子processや未知containerの終端を確認できない場合はprivate入力と既存attention証跡を保全する。確認済みの失敗では自分の一時資格とruntimeだけを回収する。producer/restoreは有限timeoutとcleanup猶予で管理し、未知actorを名前で停止・削除しない。

初回取得・同世代の隔離復旧に合格してから既存backup/retention timerを有効化し、同じownerのstatusで確認する。source、main統合、native install、取得、隔離復旧、定期有効化を別状態として既存案件記録へ残す。月次の期限・保管・復旧確認と失敗改善は共通PostgreSQL S3 backup正本§7のPDCAへ接続する。


### 2026-10-20の基礎本番受入と更新運用

中央source `b6c00f076afb22f51ffc3cc16d88539d77a21967` とbackup source Infra `a10b2515befdcd63088855a9111013698c38a562` の登録済みoperationで、Phone VMへの初回install、実S3の手動4世代取得、4世代目の同exact manifest/VersionIdによるDB/FAX隔離復旧を受入した。11 table/head `20261012_0002` と `public.phone_numbers` 0件のread-only assertion、固定Backend imageのFAX reader、隔離project及び一時資格の回収が成功した。実回線FAXの成功とは区別する。既存標準receiptはinstall `release-cdd9e00647043c6b9b77d2d4`、4世代目restore `release-ee27b437b7aa5da3d48bf818`、schedule `release-f1bf22e35c2ceabffb923721` である。

backup/retention timerはenabled/activeを読取済み。4手動世代を4定期実行の実績へ読み替えない。`backup-status`はtimerのLastTrigger/次回UTC時刻とserviceの開始・終了時刻、Result/exit statusを投影し、JSTへの変換と実発火・取得成功を既存完了記録へ残す。新しい監視基盤や台帳は作らない。

更新は同じ `backup-install` とoptional公開preimageを使う。originは旧Gov/InfraのGit blobから全sourceとunitのhashを再構成し、statusのsource closureと照合する。profile fingerprintは公開profile、AWS profile及び既設producer鍵のbyte hashを束ね、秘密値は返さない。候補codeは自己所有の一時directoryから読み込み、旧installed moduleと混在させず、旧sourceを先に書き換えて実行しない。

native ownerはPhone timerと管理serviceだけを有限時間で停止し、既存guest lock下でpreimageを再確認する。非leaf鍵・既存S3世代・latest-successを保持し、固定4roleの新leafで証明書pair/CN/期限、実Roles Anywhere認証と保持中exact世代の読取を確認する。source/profile/leafは既知の旧byteに限りatomic置換し、失敗時は自分が変更したfileを独立に補償する。既存のenabled/active状態の復元はguest lock解放後に行い、Persistent timerの即時発火と競合させない。未知consumer・補償未確認では一時資格/candidateを保全し、標準FAILED結果へ記録する。初回installへこの更新入力を暗黙適用しない。

2026-10-21にはGov `fa74ca3be56878ef2b566cc11aeeabf65ed21c59` / Infra `e6627eb0caa9831612399240ec50f5fe898f2752`で既設backupを更新し、4roleの新leaf数値version 2の認証と保持世代読取、新しいDB/FAXの同世代隔離復旧を確認した。capture `release-c4b23327629e361364c8d259`、restore `release-c7927c91715f631e40851058`、DB artifact SHA-256 `7ad12b2254038d89631695c4194a75e74c266c650c59a2245702243ab35d8218`である。11 table/head `20261012_0002`、原本0件と保護reader probe、cleanupまでの結果であり、実回線FAXの受入ではない。更新前にはtimerのUTC 2026-10-20 19:30:07の実発火、service exit 0、同じS3 VersionIdを照合し、定期1回の成功を手動世代と区別した。更新後の定期発火をこの手動取得から推定しない。

### 配備前captureが行う停止・再開の責任境界

`capture_pair()`は既存guest lock内で完全なruntime観測を取得し、既知Backend IDの`StartedAt`だけが変わる停止・再開、再開後health、profile・container ID/image/RestartCount・他container・volume/backingの不変を確認する。許容判定はこのcapture ownerだけが所有し、既存`status=captured`の公開JSONに`runtime_transition.before/after`とsource SHAを返す。

共有S3 producerの同じ呼出しが保存・既存receipt commitを完了してexit 0となった後、`scheduled_backup()`がstdout中の唯一のtyped capture結果を既存completed結果へ渡す。wrapperで呼出し前後を観測して差分を正当化せず、欠落・重複・不正結果を拒否する。`Runtime.backup()`を経た`Runtime.deploy()`は、最初の観測とcapture-before、lock再取得後とcapture-after、profileをそれぞれ完全一致で照合する。全containerの開始時刻を比較から除外せず、producer完了後の追加restart等はpull/migration前に止める。新しいreceipt、journal又はauthorityを作らない。

### 2026-10-21の正規配備・systemd consumer・同世代復旧

Gov `d2b980cb3cefcd138553c8868529f8c1bf55ddb4` / Infra `e2b53ffafcbc3a44837a2dbc8b78c7fc41867536`へbackup sourceを更新した後、中央正規release `prod-20261021-548edead1f81`（transport `release-579683fa370c758ea0adf4c0`）で管理専用runtimeを配備した。固定Backend source `11946f334bbc2c2d1c970ceef14cb896a6421e27`、既存tenant/phone-owner、telephony無効を確認し、同じ配備前backup世代を`release-c977b954e747530270a6066b`で隔離復旧した。公式管理画面`https://phone.anshin.care/dashboard`のowner tenant表示・最新状態取得を確認済み。MFA復旧後のh-test3再ログイン・MFA通過は本人の別Chromeでの完了報告を受入済みであり、再初期化しない。

10:30 JSTの旧source service失敗は、backup source更新の停止処理と時刻が重なる履歴として保存した。新sourceの欠陥又は停止が原因と断定せず、Gov `4d8077f93b03a0e686132d9e1092008468196b70`の既存`backup-run`から固定systemd unitを実行した。新operation・producer・unit・外側lock・名前によるstopは追加しない。同一Invocation `d7b1153ffd7a4db8b59e47932bfc21f6`の開始から終了、`Result=success / ExecMainCode=1 / ExecMainStatus=0`（UTC 02:27:51〜02:28:25）、fresh DB artifact/manifest両VersionIDを照合した。captureは`release-da58b4feaf10d85191f0b65b`、DB artifact SHA-256は`54adb4275ddb3268a98e4ef25e81018046edd14170c4fb21726929710a654e7f`、作成UTC 02:27:52・保護期限11月21日02:27:52、SSE-S3 AES256である。

このexact世代を`release-1c4210cf08aca66b30956ad4`で隔離restoreし、11 table/head `20261012_0002`・`public.phone_numbers` 0件・application read-only smoke・cleanupを確認した。final statusも同じlatest世代とbackup service成功、backup/retention両timerのactive/enabledを示した。今回の手動unit実行を定刻発火の追加実績へ読み替えず、翌予定のbackup UTC09:30（18:30 JST）、retention UTC15:00（翌日00:00 JST）は予定として記録する。実FAX原本0件のため、非空の実原本の本番restore、実Cloco・実番号・商用容量・Softphone実機は未確認のまま維持する。

FAX一時TIFFはInfra `a00b0a4c3bb7631ac646e78b2ee55e4803d82860`でclaim別原本・実ACK後回収・旧受信event互換・指定DLQ一件の通知再送を修正し、既存HTTP回帰、隔離の実G.711送受信、canonical及びfixed-SHA独立reviewを通してmainへ統合した。[FAX運用契約](../../runbooks/telephony-platform/fax-and-number-provisioning.md)を参照する。管理専用productionへPBXを追加しておらず、実回線での適用・受入成功とは扱わない。


### 2026-10-21 社内評価用Softphone実装

sourceは`anshin-frontend-mobile/packages/anshin_phone_softphone`、generated APIは同repoの`packages/anshin_phone_api`と`spec/openapi.phone.json`。職員アプリのroute・bundle・root dependencyは変更しない。初期評価は組織一覧・端末設定の2 GETで、2026-10-22の本人承認後に本人履歴GETを追加する。tenant/roleとBearerを維持し、Core opaque session、管理用組織全体履歴、卸SIP資格を流用しない。

共通PJSUA C coreを専用threadで実行し、Android JNI／iOS SPM経由のFlutter Method/EventChannelへ接続する。登録はengine/account世代、callはprocess単調IDへ束縛する。通話中切替・logoutを止め、停止は既通話を保って新規登録・発信を止める。SDK callbackからFlutterへ直接入らず、SDK destroyとthread joinを完了してprocess所有を解放する。

評価構成はarm64・UDP・G.711・null audioで、マイク・speakerを開かない。TLS/SRTP・商用インターネット経路の完成を示さない。Android APKのlink、iOS Simulator app buildと案件専用Simulatorの実MethodChannel初期化・二重初期化拒否・destroy/reinitを確認した。既存隔離PBXのSoftphone分岐では同じ固定SDK/native coreでREGISTER、発着信、PCMU送受信packet、復号した非無音のcarrier 440Hz受信、transport再接続、停止資格の拒否、active復帰、revoke・旧call拒否を確認。これらは作業中検査であり、fixed SHAのcanonical・独立review・main統合の完了とは別に記録する。

Web exampleは明示的な架空データで共有Flutter画面を確認する。native通話・Google認証・Pushの成功へ読み替えない。本人用履歴は次節の承認済み変更束として実装・検証する。Phone mobile Auth client/redirect、secure storage正式binding、OS標準着信・Push、実機と背景/通信切替の受入は別残件。商用配布のlicense/第三者条件・保守と配布方式を確定してから当該scopeを具体化する。基礎管理画面の本番公開を停止しない。


### 2026-10-22 Simulatorの実SIP consumer検証

Mobile `2569456ad0643c4409ab8fb523d23841b726e9eb`はAndroid shared STLのpackagingを正規CMake modelへ一致させ、APK内の両SO・専用Emulator上のnative lifecycle・canonical・独立reviewを確認してmainへ統合した。Infra `48ec330b23729acdca87b0764f7a8e5743867ebb`もmain統合済み。本人の実UI最終確認は「表示・操作に問題なし」。職員app bundle及びPhone本番runtimeに変更がなく、release分類はNOOP、本番操作0件。

次の入力は既存 `scripts/test_phase1_sip_e2e.py --fixture softphone`へ `PHONE_SOFTPHONE_SIMULATOR=android|ios` と当該Task専用 `PHONE_SOFTPHONE_DEVICE` を渡す。既存lease・一意Compose project・Backend fixture・SIPp carrier・cleanupを再利用する。Mac loopbackだけの5070/UDP公開bindingを実観測値と照合し、無資格OPTIONSで観測したNAT一件だけをfixture側で許可する。Digest認証はPBXが所有し、資格は試験中だけの端末loopback HTTPへmemory上で渡し、argv・log・端末fileへ保存しない。Androidは当該serialへ割り当てた一時ADB forwardだけを使い、終了時に回収する。production template・carrier5060・DB・他Simulatorは変更しない。

Flutter integration consumerで実REGISTER、着信表示、応答、SDK接続、相手BYE、発信と終話、再登録、revokeと旧call拒否を検証する。media-activeはSDKのmedia準備状態であり、このSimulator laneのRTP到達・復号音声・マイク・Push・背景着信の合格を示さない。既存Linux core音声結果とも区別する。各実行結果は既存Task記録へ固定SHA付きで記録し、試験追加だけで成功済みとは扱わない。

検証専用SBCだけを第三bridge `10.254.252.0/24`へ追加し、`10.254.252.40:5070`をMac loopbackの一件へ公開する。Dockerのinternal-only networkでは実公開bindingが成立しないためであり、carrier5060・PBX・DBの非公開境界を拡張しない。既存ownerのsubnet競合検査とproject cleanupにこのbridgeも含める。端末Contactの標準 `;ob` は一度だけ許可し、観測IP以外・不正port・重複aliasは拒否する。

## 本人履歴の承認済み追加範囲（2026-10-22）

ownerは、既存Mobile/Infra/Backendの専用worktreeで、通話時の本人帰属・追加migration・本人専用GET・generated consumerと履歴画面を実装する六項目を承認した。Macを唯一のwriterとし、政策支援4機能・本番Auth client・Push資格・実回線の開通を含めない。従来の社内評価UI確認を新しい履歴画面の受入へ流用しない。

実PBXは音声routeを内部token付きPOSTで取得し、unique IDと同じauthorized endpoint行から本人帰属をDBへ固定してからDialする。FAXの既存route GETは維持する。着信のanswer hookだけで実応答endpointをCDRへ追加し、発信のcarrier endpointを本人内線として報告しない。spool/forwarderは既存経路を使い、APIの受理前にeventを破棄しない。

Backendの2table追加は旧CDRを保持し、再割当・遅延・再送で帰属を変えない。Mobileは本人専用GETの結果だけを表示し、masked相手から再発信しない。履歴取得中も通話状態を維持し、組織切替・失効・logoutではcacheと旧応答を捨てる。管理向けの組織全体一覧は変更しない。

既存SIP fixtureの発着信後、同じ実PostgreSQLのmigration head、PBX snapshot、CDRとproduction本人queryを検証する。これはnative認証を通したHTTP受入ではなく、認可wireの拒否条件はBackend既存suiteで別に検証する。実行・fixed SHA review・本人履歴UI確認・main統合・必要なDEPLOYを分けて記録し、sourceだけで本番反映済みとは扱わない。


## 2026-10-28 native認証の本番接続

本人はPhone専用HMAC鍵と`anshin-phone-enrollment`資格が未発行であることを前提に、既存Auth/資格管理owner・Secret Managerでの新規発行登録、規定検証・独立review・main統合・本番有効化と実Google callback受入を明示した。以前の隔離限定範囲を本番接続へ進めるが、Push・Cloco開通・番号切替・Store・政策支援4機能は含めない。

Authのpublic clientは`anshin-phone-mobile`、package/bundleは`care.anshin.phone`、callback/logoutは`care.anshin.phone:/oauthredirect`と`care.anshin.phone:/logout`、署名backchannelは`https://phone.anshin.care/api/v1/auth/native/backchannel-logout`。issuer、managed AAL2/AMR、Policy1/provider-assurance-v1を既存正本へ固定する。資格の値はこの文書へ記録せず、共通資格管理正本のPhone専用2 ID・固定数値version・read-only FILE consumerを使う。

既存資格ownerのcandidate canary/promotionは鍵の配布までを所有し、Phone Runtimeは通常配備のComposeへそのprojectionを引き継ぐ。両資格とAuthをqualification後、`compose.production.yaml`の明示flagでnativeを有効化する。Settings/healthはnative有効時にHMAC・enrollment資格とpolicy版が揃うことを確認し、telephonyはfalseを維持する。通常backup/migration/health/rollbackを既存release ownerに任せ、DB/FAX鍵・S3 SSE-S3/31日を変更しない。

資格の登録、native配備、案件専用Simulatorでの実Google→OS AppAuth callback、本人API/refresh/logout/失効の受入は別の完了項目として実結果へ記録する。本人操作が必要なGoogle login/MFAのみ案内し、端末提供・既存UI承認を再質問しない。
