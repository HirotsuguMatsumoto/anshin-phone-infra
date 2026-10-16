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
  - anshin.infrastructure.system-architecture
  - anshin.runbook.system-architecture.ms-a2-server-access
  - anshin.governance.privileged-operation-gateway
  - anshin.release.contract
  - anshin.release.impact-gate
consumers: [anshin-phone-infra, anshin-phone-backend, anshin-frontend-monorepo]
code_paths: []
contract_paths: [docs/specs/changes/2026-10-13-phone-preparation-navigation.change.yaml]
test_paths: [scripts/build_check.sh]
last_reviewed: "2026-10-17"
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

## 実装・検証・配備を分けた現在状態

| 対象 | 確認済み | 未確認・未実施 |
| --- | --- | --- |
| 基礎管理経路 | 実Docker、隔離Auth、Backend、実PBX、架空番号・模擬carrierを通す番号/端末管理・通話・G.711 FAX・監査・隔離復元 | 実Cloco、実番号、T.38、顧客通信、本番復元・商用容量 |
| 管理画面 | 説明iconのclick/Escape、必要状態・エラー・FAX制限表示。対象画面の自動試験・右サイド実browser確認。ownerの「画面問題ない。本番反映お願い」により当該画面の本人確認受領済み | 本番画面の実確認 |
| source | Backend `7770e877b2901d1b99c09cf32606f8abdc55178d`のruntime変更、Infraの既存runtime変更、Frontend `ba6bcbdb97cc4d80c0f45cb0c4aebb2e3d301c57`の説明・文書整備をmainへ統合 | source統合を本番提供と扱わない |
| 本番adapter | 既存中央registryにPhone Backend/Infraの登録がある | `production adapter is not implemented`でblocked。VM、配備、公開URL、provider設定及び本番資格の確認 |
| 無料Softphone | 既存employee/customer mobileはFlutter。公式SDK条件を比較 | Phone SDK実装、Android/iPhone実機、Push、背景着信・音声品質、採用方式・費用・UI/UX詳細設計 |

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

### 2026-10-17のMS-A2-1初期構築候補

統合済みGov `ddaf5059f6754ed8ee98990032565d58b84ed86a`の登録Worker observerをMacから実行した。物理memoryは約29.077GiB、MemAvailableは約26.714GiBの瞬間値、固定LXD保存先の同一filesystem（device 64512）空きは約99.2566GiBだった。LXD5.21.8はdefault projectだけで、VM・pool・managed networkは未作成。Ubuntu24.04/x86_64の公開VM image fingerprintは`d4ff18198fb2ed8c88d408421e610c143cf1f5c1c0178e57178fb586880c3e56`である。image本体の取得・VM作成はこの観測に含めていない。

Core/Authの18/7GiBを維持し、MS-A2-1にPhone専用project `anshin-phone`、VM `ms-a2-1-phone`、dir pool `phone-pool`、default project managed bridge `phone-br0`を置く初期構築案とする。共有2vCPU・memory4GiB・root32GiB、subnet `10.91.40.0/24`のGW `.1`・guest `.10`を固定する。将来worker17GiB＋Phone4GiB＋host/QEMU設計割当6GiB＝27GiBを物理量へ照合した。host6GiBは実測peak又は既存予約ではなく、同時負荷・商用通話容量の受入ではない。

同一filesystemの初期予算80GiBはguest32・image8・temp/rollback16・hostgrowth24の設計割当である。再開時は検証済み保存先と固定imageの実allocated blocksだけを控除し、疎fileの論理sizeを空きへ足さない。guest32GiB内にOS、image、DB/WAL、FAX、backup・隔離restoreの一時領域を収められるかは、VM構築後の実測事項として残す。GUI保全diskを再利用・削除しない。

固定入口`provision-phone-vm-v1`は既存origin、Worker carrier、sudo資格、release.lock、Release Plan DEPLOYと標準receiptを使う。Phone専用guardを最初の通信前に適用し、Core/Auth/既存workerを停止・再起動しない。本節時点ではsource実装・検査中で、VM/bridge/pool未作成・容量未受入・本番API/公開/復旧未完了である。全体構成3文書はinfra担当が同じ候補・未適用状態へ同期し、Phone writerが構築後の実結果を次の直列変更で同期する。

## 本番反映へ向けた実装単位

| 作業 | 対象・既存資産 | 完了に使う結果 |
| --- | --- | --- |
| 配置と資源 | 既存host observer、Phone専用VM。Core/AuthのVM・DB・volume・credentialは分離 | 実targetと必要資源・保存・復旧経路の事実。未測定値や旧案のPASSではない |
| 配備adapter | InfraのCompose・既存backup/restore、中央release registry/matrix、既設admin alias。中央matrixの`phone-backend`はstandalone配置へ同期済み | 選定targetへ固定する薄いtransportと既存release owner。中央runnerのPhone Backend/Infra production adapterは引き続き未実装 |
| 実入力確認 | Backend Settings、DB migration、Auth `anshin-phone` client、issuer/JWKS/audience、frontend API origin | 今回の実env/configを各consumerが受理する軽い確認後、対象の実業務integration。local Auth成功を本番Auth確認にしない |
| UI配備 | 現行frontend、既存hosting/release owner | Phoneの実project/公開経路・domain・権限・費用条件。Phone projectと既存release bindingの未確認を登録済みと扱わない |
| 保管・復旧 | 既存保護FAX・DB backup/隔離restore・rollback実装 | Phone専用の実保存先、保持期間、暗号化入力、隔離restore、既存ownerによる結果確認。新trust/journal/署名/gateを追加しない |
| 最終確認 | 対象UI、既存自動試験、instruction-originの実Docker・右サイドbrowser | AIの確認と指示者本人の明示確認を分ける。管理/MFAの実確認は本番で行い、架空stgを停止条件にしない |

各作業のcheckは既存owner/selectorが選ぶ変更範囲だけを使う。同じ固定入力のheavy試験を重ねず、sourceが変わらない経路を「念のため」全件再試験しない。releaseの業務判断は既存runnerが一回所有し、transportへ複製しない。

費用が発生し得るVM追加資産、hardware、hosting、off-host保管、外部secret/provider/Push等は、実契約・resource・料金・期間を先に確認する。追加費用を確認できない操作は実行せず、目的・対象・見積り・未確定項目・単発/継続・期間を示してownerの具体的指示を得る。既存CIの通常利用はownerの確認不要例外を適用する。内部DB/password/HMAC/FAX keyを、外部provider資格4件や有料Secret Manager作成へ自動的に置換しない。

実Cloco資格・接続/FAX/channel条件、届出・番号計画・契約の現在状態は事業側正本から照合する。資格台帳と許可済みprimary設定の確認前に再共有を要求しない。未確認の実回線・顧客開通・商用提供は、隔離基礎機能の成功と分ける。助成対象4機能は先行実装しない。

## Softphoneの技術比較と次の検証

2026-10-12に公式sourceを確認した。SDK採用versionとcomponent条件は未固定であり、無償のclosed-source商用licenseを推測しない。vendorへ連絡・契約・購入・account作成はしていない。

| 候補 | 公式情報と適用確認 | 既存資産との関係・未確認 |
| --- | --- | --- |
| PJSIP | [公式license](https://www.pjsip.org/licensing.htm)はGPL v2以降又は別途proprietary条件。third-party条件も確認する | native wrapperとFlutter連携、対象version、保守・再接続・実機音声・Pushは未検証。proprietary価格は未確認 |
| Liblinphone | [公式software/license案内](https://www.linphone.org/en/voip-software/)はGPLv3/AGPLv3又はproprietary条件。[SDK案内](https://www.linphone.org/en/liblinphone-voip-sdk/)にはJava/Kotlin・Swift wrapperとMaven/Cocoapod連携がある | Flutterはnative boundaryが必要。実component/versionのlicense、構成、保守、Push、実機品質とproprietary価格は未確認 |

公開source方針・proprietary採用・支出を本計画で決定しない。採用候補とUI/UX詳細設計を具体化してownerへ提示し、同意の必要な部分だけを確認する。既存Flutter認証・secure storage等の再利用は、当該アプリへの無断統合や他製品資格の転用を意味しない。

検証するUI状態は、ログイン、端末設定取得、登録/未登録、発信、着信、通話中、通信断/再接続、権限拒否、端末停止/失効である。説明は共通icon＋Popper、必要状態とエラーは常時表示とし、新UI実装前に詳細設計を提示する。

隔離の実SDK driverで登録・発着信・双方向音声・再接続・失効を確認し、その成功条件を既存suite/fixture/ownerへ固定する。背景/スリープ、OS終了、通知/マイク権限拒否、Wi-Fi/モバイル切替、重複着信、応答競合は両OSの実機と実Push consumerまで確認する。模擬SIP試験をAndroid/iPhone SDK・Push成功へ読み替えない。卸トランク資格を顧客端末へ配布しない。

現在のinstruction-origin PATHと確認した既存候補pathにはFlutter/adb実行環境が見つからず、iOS toolchain・接続実機・Phone Push資格も未確認である。他製品の契約・資格の不在とは一般化せず、共有済みの対象資格・実機・toolchainの所在を調べ、不足と費用を具体化する。native未確認を、完成している基礎管理経路の追加品質gateへ変更しない。


## Macでの再開と管理用配備定義（2026-10-16）

Macのcurrent integrated sourceの既存host observerからCore/Worker両hostを読取できた。今回のMac接続にGUI VMのWorker経路修復は不要であり実行していない。Phone project/VMはmissingで、Core/Authの設定18/7 GiBを変更していない。物理memory約29.08 GiB、Core側MemAvailable約5.32 GiB、Worker側約11.42 GiBは今回の瞬間観測であり、Phone容量受入ではない。旧5 GiB候補を適用しない。

Postgres・Backend・migrationのsource定義は`compose.management.yaml`が所有し、既存Phase 1と`compose.production.yaml`がextendsする。production管理定義は実carrier入力・SIP/RTP公開・source buildを含まず、Backend/migrationの同じfixed digest image、owner指定の本番FAX月単位policy及び既存secret-file入力を要求する。BackendだけにAuth/JWKS取得用egressを接続し、DBはinternalのまま維持する。

管理定義は`ANSHIN_PHONE_TELEPHONY_ENABLED=false`であり、既存Backendの管理・履歴は使えるが、端末資格・PBX・FAX送信/dispatchは503となる。既存のqueued/sending行を変更しない。実機資源、API ingress、Phone hosting binding、独立key復旧・定期backup/隔離restoreが未受入のままadapterをsupportedへ変更しない。この定義のrender成功又はsource統合を本番反映・本番Auth・実回線の成功と扱わない。


## FAX保護原本の月単位保持（2026-10-16 owner回答）

ownerは「Clocoと同じ月単位（毎月5日に前月分を削除）」を指定した。production ComposeはBackendとmigrationへ`ANSHIN_PHONE_FAX_RETENTION_POLICY=cloco_previous_month`を渡し、Backendに継承されたlocalの秒数defaultを空へ上書きする。保存受付月の翌月5日00:00 JSTを期限とし、原本だけを対象とする。既存S3標準31日・通信履歴・監査の保持は変更しない。境界、replay、catch-up、削除範囲のsourceとconsumer契約は`anshin.phone.backend.foundation-runtime-contract`を正本とする。

既存production cron ownerから同じfixed imageのBackend内`python -m app.core.fax_retention`を呼ぶ。VM・adapter・schedulerは未配備であり、sourceやCompose検証を実発火成功と扱わない。PBX一時TIFFとdead-letterのcleanupはtelephony有効化前の別受入事項として残す。


## Phone PostgreSQL専用backup資源の具体化

既存中央owner `scripts/postgresql_backup_storage.py` のPhone projectionを使い、既設classをPostgreSQL専用へ展開する。正本のbucket名は `anshin-prod-phone-postgresql-backup-691862619128` とし、既存Roles Anywhere anchorとPhone VM用のwriter/restore CNへ限定する。専用bucket・writer/restore role・writer/restore profile・bucket policyの6資源であり、他製品stackを変更しない。

DB backupはownerのKMS廃止指示に合わせ、既存age暗号化・manifest検証とSSE-S3（AES256）を使う。新しいKMS key・alias・権限を作らない。Governance 31日、Versioning、purposeごとの最小権限を維持し、元templateの30日expirationを持ち込まない。FAX・録音のbucketとprincipalをDB backupと共有しない。新規bucket等の実作成は最新費用規程に従う。共通SSE-S3 producerとrestoreの先行統合前に、このprojectionだけで本番backup適合済みとは扱わない。source、ValidateTemplate又はstack作成の成功を4世代backup・隔離restoreの成功へ読み替えない。

FAX保護原本のoff-host backupは別projectionとし、`anshin-prod-phone-fax-691862619128`、`fax/*`専用のwriter/restore role/profileを使う。DBとFAXは各6資源、合計12資源で相互アクセスを許可しない。FAXはBackend既存の保護原本暗号化と独立した復旧鍵保管を維持し、S3にはSSE-S3で保存する。FAXの通常原本はBackendの月単位期限に従い、off-host backupは31日保護を維持する。bucketへ自動expirationを追加しない。通信停止中の録音用資源は今回作成しない。

## Phone専用guestのnative配備owner

`scripts/production_runtime.py` は固定Phone guest内のDocker daemonで、既存production Compose、固定digestのBackend/PostgreSQL、実Settings検証、migration、readiness及び失敗時のBackend rollbackを担当する。中央release ownerがsourceとartifactの資格・既存release receiptを所有し、このscriptはGit取得、image build、署名、journal又はreceiptを追加しない。CLIのDocker接続はguest内socketへ固定する。fixtureのtransport指定だけをconstructorで明示する。

非secretの実行設定は `/var/lib/anshin-phone/release/runtime.json` に保持する。healthは実container image、Settings、DB readiness及びCompose healthを読み、profileのSHAだけで成功を判定しない。既存DBの更新では既存Phone backup adapterを共通lock取得前に呼び、lock取得後にprofileと実container・volume観測が不変であることを確認する。既存DB/FAXをprofileなしで自動採用しない。migration中断時は所有one-offを停止し、旧Backendの実healthが成功した場合だけrollback成功を返す。初回失敗はBackend停止を確認し、DB/FAX volumeを残す。

共有backup ownerとの接続、管理専用の実配備fixture、host容量受入及び中央Phone operationの接続は別々に実確認する。native ownerのsourceだけで本番配備adapter全体の完成又は本番反映を宣言しない。DB rollbackは自動実行せず、適用するmigrationが旧Backendと互換であることを中央change contractで扱う。source更新とprofile更新の間で中断した場合は、既存中央release結果と実container imageを照合してから復旧する。

## 既存PostgreSQL ownerへの専用入力

`scripts/phone_postgresql_backup_adapter.py --scheduled-backup` はnative `runtime.json` と実Backend healthを照合し、実Postgres container ID・Backend source SHAを、既存 `backup_postgresql_to_s3.sh` へ渡す。専用bucket、`postgresql/phone` prefix、Phone writer role/profile、`/etc/anshin-phone/aws/config` と専用鍵pathだけを使い、他製品のAWS環境・KMS入力を継承しない。`/etc/anshin-phone/postgresql-backup-profile.json` はowner-onlyで、既存manifest検証鍵のSHA-256である `manifest_key_id` 一項目だけを持つ。秘密値は格納しない。

共有producerがPhoneを許可し、lock取得後に `POSTGRES_BACKUP_EXPECTED_CONTAINER_ID` と実containerが一致することを検証してからinstallする。現行未対応の共有sourceへKMS値を偽装して接続しない。adapterのsource又は単体testだけで本番backup適合済みとは扱わない。共有ownerがage・SSE-S3・exact version readback及び既存receiptを所有し、adapterは別receipt/journalを作らない。

同梱のservice/timerは既存PostgreSQL unitを再利用し、毎日04:30・10:30・18:30・23:30（Asia/Tokyo）の4回、Persistent catchup、共通guest lock及び限定retryを使う。定義の追加はinstall・enable・定期実行の証拠を代替しない。初回取得、4世代、隔離restore、FAX backup及び復旧鍵別保管は引き続き実受入を必要とする。
