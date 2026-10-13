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
last_reviewed: "2026-10-13"
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

修復後、同じ統合済みSHAの既存`inspect-worker-host-recovery-v1`による観測を既存schemaで検証した。MS-A2-1は`running`、failed unitは0、固定GUI VMと既存三workerは`running`だった。物理memoryは約29.08 GiB、MemAvailableは約10.87 GiBの瞬間値、root空きは約99.75 GiBである。これらはPhone専用VMの割当・負荷・容量・復旧受入を代替しない。今回のoperationはPhone VMを作成せず、既存サービスの資源割当を変更していない。現在の配置正本はMS-A2-2の専用VM予定を維持しており、MS-A2-1の空きだけを理由に配備先を変更しない。

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
