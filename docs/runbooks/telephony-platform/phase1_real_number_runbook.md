---
schema_version: 2
doc_id: anshin.phone.phase1-real-number-runbook
title: "Phase 1 実番号接続手順"
domain: telephony-platform
document_kind: runbook
scope: product
product: anshin-phone
owner: anshin-phone-infra
authority: reference
status: inventory
risk_level: critical
source_doc_ids: []
consumers:
  - anshin-phone-infra
  - anshin-phone-backend
code_paths:
  - compose.phase1.yaml
  - compose.phase1.mock.yaml
  - scripts/verify_phase1.sh
  - scripts/phase1_status.sh
contract_paths: []
test_paths:
  - scripts/test_phase1_render_config.py
  - scripts/test_pbx_event_pipeline.py
  - scripts/test_phase1_sip_e2e.py
last_reviewed: "2026-08-22"
review_interval_days: 30
sensitivity: internal
---

# Phase 1 実番号接続手順

## 専門用語一覧

| 用語 | 正式名称・読み方 | 意味・本書での扱い |
| --- | --- | --- |
| TEL | Telephone | 音声通話に使用する電話又は電話番号 |
| FAX | Facsimile | 電話網等を使って文書画像を送受信する通信サービス |
| SIP | Session Initiation Protocol | IP網上で電話の発着信や通話sessionを制御する通信規約 |
| IP | Internet Protocol | パケット通信網でデータの宛先と配送を制御する通信規約 |
| DID | Direct Inward Dialing | 着信番号をPBX等へ通知し、番号別に着信先を制御する方式 |
| PJSIP | PJSIP | SIP、SDP、RTP等を実装するopen source communication library |
| Docker | Docker | アプリケーションと依存関係をcontainerとして実行・配布する基盤 |
| backend | Backend | server側でAPI、業務処理及びdata管理等を担うsoftware領域 |
| E2E | End-to-End | 利用者操作から最終処理までの一連の経路又はそのテスト |
| UDP | User Datagram Protocol | 送達確認や再送を必須としないdatagram型の通信規約 |
| TCP | Transmission Control Protocol | 送達確認、順序制御及び再送を行う接続型の通信規約 |
| TLS | Transport Layer Security | 通信の暗号化、改ざん検知及び接続先認証を行うプロトコル |
| RTP | Real-time Transport Protocol | SIP等で確立した通話の音声データを運ぶ通信規約 |
| API | Application Programming Interface | システムやソフトウェア間で機能・データを利用するための接続仕様 |
| 0AB-J番号 | ゼロエービージェイ番号 | 03、0157、06等の市外局番から始まる固定電話番号 |
| 電気通信番号 | でんきつうしんばんごう | 電気通信役務の提供において端末や通信先等を識別する番号 |
| 電気通信番号使用計画 | でんきつうしんばんごうしようけいかく | 電気通信番号の使用方法、管理及び設備等を定め、認定等の対象となる計画 |
| Git | Git | ファイルの変更履歴とブランチを管理する分散型バージョン管理システム |
| repository | Repository | source code、文書及び変更履歴を一まとまりで管理する単位 |
| YAML | YAML Ain't Markup Language | indentとkey-valueで構造化データを表すテキスト形式 |
| PostgreSQL | PostgreSQL | open sourceのリレーショナルデータベース管理システム |
| PBX | Private Branch Exchange | 内線、外線、着信振分け及び転送等を制御する電話交換システム |
| CLI | Command-Line Interface | コマンド文字列でソフトウェアを操作するインターフェース |
| VPS | Virtual Private Server | 仮想化された専用環境として利用するserver |
| VPN | Virtual Private Network | public network上に暗号化等でprivateな通信経路を構成する仕組み |
| ID | Identifier | 利用者、会社、データ等を一意に識別する値 |
| CDR | Content Disarm and Reconstruction | ファイルを分解し、危険なコンテンツを除去して再構成する無害化技術 |
| UFW | Uncomplicated Firewall | Linuxのfirewall ruleを管理するtool |
| MD | Markdown | 見出し、表、link等をplain textで記述する文書形式 |
| SBC | Session Border Controller | SIP通信の境界で接続制御、セキュリティ及び相互接続を担う設備 |
| SRTP | Secure Real-time Transport Protocol | 音声等のRTP packetを暗号化・認証するprotocol |
| CPU | Central Processing Unit | serviceの処理を実行する演算resource。使用量と飽和時間を計測する。 |
| memory | Memory | serviceとOSが実行中のdataを保持するresource。通常値、peak及び回収後の値を計測する。 |
| process数 | Process count | serviceが同時に作成するprocess及びthreadの規模。Composeでは`pids_limit`の候補となる。 |
| latency | Latency | 通話確立、API又はevent配送が完了するまでの遅延。 |
| packet loss | Packet loss | 送信されたRTP packetのうち受信側へ届かなかった割合。 |
| OOM | Out Of Memory | 利用可能なmemoryを使い切り、OS等がprocessを強制終了する状態。 |

## 1. ゴール

上位キャリアから払い出されたTEL番号とFAX番号をアンシンフォンへ収容し、次を実機で確認する。

- 外部電話からTEL番号へ発信すると、アンシンフォンのAsteriskを経由してスマートフォンSIPクライアントが着信する
- スマートフォンと外部電話の間で双方向音声が成立し、30分通話でも片通話・無音・切断がない
- スマートフォンから国内固定・携帯へ発信でき、キャリアが許可したTEL番号が発信者番号として通知される
- FAX番号への受信が専用経路へ振り分けられ、受信結果と原本を保持できる
- 番号、端末、発着信履歴、FAX履歴をテナント単位で追跡できる

## 2. 実番号試験前にキャリアから受領する情報

キャリア回答を待つ間は、`./scripts/verify_phase1.sh`を実行し、文書用IPアドレス、架空DID及び一時テスト値だけで次を確認する。この検査は実キャリアとの疎通、スマートフォン実機、実音声又はFAX品質の合格証跡には使用しない。

- REGISTER認証と固定IP認証の両方でPJSIP設定を生成できる
- TEL DIDとFAX DIDが別の着信経路へ展開される
- 110、118、119、国際電話、0570及び0990がPhase 1では遮断される
- キャリア接続元CIDR、発信者番号及びスマートフォン内線が設定へ反映される
- 生成された設定に未解決テンプレート値が残らず、ファイル権限が`0600`になる
- 隔離Dockerネットワーク上で、仮想キャリアからスマートフォンへの着信と、スマートフォンから仮想キャリアへの発信が成立する
- Asteriskの通話/FAXイベントがマスクされ、Backend停止時に消失せず、復旧後に重複登録されない

完全な隔離E2Eは次で実行する。実番号、キャリア認証情報及び外部secretは使用しない。

```bash
RUN_PHASE1_SIP_E2E=1 ./scripts/verify_phase1.sh
```

| 項目 | 必須 | 合格条件 |
| --- | --- | --- |
| TEL DID | 必須 | E.164表記と国内数字表記の双方を確認 |
| FAX DID | 必須 | TELとは別DIDとして着信ルーティング可能 |
| SIP接続先・port・transport | 必須 | FQDN/IP、UDP/TCP/TLS、送受信portが明記されている |
| 認証方式 | 必須 | REGISTER認証又は固定IP認証を確定 |
| 接続元IP/CIDR | 必須 | 着信SIPを許可する最小範囲を確定 |
| RTP IP/port | 必須 | 音声用の送受信範囲を確定 |
| コーデック | 必須 | G.711 μ-law/A-lawの優先順位を確定 |
| 発信番号形式 | 必須 | 国内数字、`+81`、PAI/Fromの要件を確定 |
| FAX方式 | 必須 | T.38、G.711パススルー又はWeb FAX APIを確定 |
| 緊急通報 | 必須 | 対応可否、登録住所、位置通知及び利用制限を文書化 |
| 同時通話数・CPS | 必須 | 契約値と超過時挙動を確認 |

## 3. 配置前の停止条件

- キャリア名、契約主体、番号名義が登記事項と一致していない
- 03、0157、06等の0AB-J番号について、利用場所と番号区画の確認が終わっていない
- 発信者番号の正当な利用権限をキャリアが確認していない
- 緊急通報の提供可否を利用者へ説明する文言が確定していない
- 電気通信事業の届出又は登録区分について、管轄総合通信局への事前相談が終わっていない
- 標準電気通信番号使用計画と同一にできるか、上位キャリアの確認が得られていない

## 4. 配置

本節では、server上の既存deployment rootを`DEPLOYMENT_ROOT=/ops`とする。

1. `${DEPLOYMENT_ROOT}/anshin-phone-infra` と `${DEPLOYMENT_ROOT}/anshin-phone-infra/anshin-phone-backend` がそれぞれ正しいGitリポジトリであることを確認する。
2. Git管理外かつアクセス制限された専用ディレクトリへ4つのsecretを配置する。`.env`は作らない。
3. キャリアから受領した非secret接続値を、運用中のsecret manager又は起動プロセスの環境変数から渡す。
4. `docker compose -f compose.phase1.yaml config` で展開結果を確認する。出力を保存する場合はsecret値を含めない。
5. Kamailio、RTPengine、Asterisk、PostgreSQL、Backend及びPBX event forwarderを起動し、Kamailio/RTPengineのhealthcheckとAsterisk CLIのendpoint、registration、contactを確認する。
6. MS-A2-2 Phone VMのSIP/RTPは、Clocoのoutbound registrationで成立する場合だけNAT越しに試験する。固定public inbound又はIP認証が必要な場合は別公開relay又は別回線の受入まで停止し、自宅routerへport forwardingしない。スマートフォンは試験用Wi-Fi又はWireGuard等の管理経路から接続する。

Phase 1の発信ダイヤルプランは、国内の10桁・11桁番号だけを許可し、国際電話、110、118、119、0570及び0990を停止する。緊急通報は上位キャリア、登録住所及び位置通知の要件が確定した後に専用設計として開放する。

## 5. 監視とセキュリティ

- Backend、PBX event forwarder及びAsteriskはDocker healthcheckで死活を判定する。
- Backend、PostgreSQL及びevent forwarderは外部到達不能の内部Docker networkへ置き、Backendのhost公開はloopbackだけに限定する。
- Asteriskは起動処理後に専用非root userへ権限を落とす。Backendとevent forwarderは常時非root、read-only root filesystem、capabilityなしで実行する。
- Docker logは1ファイル10MB、最大5世代に制限する。
- 通話相手番号はAsterisk側でマスクしてから耐障害スプールへ書き、Backendへはマスク済み番号だけを送る。
- 送信済みeventは`sent`、入力不正は`dead-letter`へ移す。5分を超える未送信又はdead-letter発生時はforwarderをunhealthyとして扱う。
- 日常点検は`./scripts/phase1_status.sh`でservice、Asterisk、SIP endpoint、Backend及びevent spool件数を確認する。event本文やsecret値は表示しない。
- 実番号、Cloco接続方式、SIP/RTP経路、host firewall及びVPN経路が確定するまで、MS-A2-2 Phone VMで外部SIP/RTPを有効化しない。AsteriskのSIP及び内部RTP `10000-10100/UDP`はVM外へ公開しない。自宅routerのport forwardingは禁止する。

## 6. 実番号切替・切戻し台帳

Clocoから既存番号の付替え可否と手順を受領した後、切替作業を依頼する前に次を一件の作業台帳へ記録する。実番号、アカウントID及び認証情報は台帳本文へ保存せず、マスク済み識別子とアクセス制御済み保管先IDだけを記録する。

| 項目 | 記録内容 |
| --- | --- |
| 対象番号 | TEL/FAXの区分と末尾4桁をマスクした試験ID |
| 現在経路 | Cloco上のユニーク、サークル及び機能のマスク済み識別子 |
| 変更後経路 | SIPトランク2、アンシンフォンPBX及びスマートフォン/FAX経路 |
| 作業日時 | 開始、判定期限及び業務影響を許容する時間帯 |
| 担当 | アンシン実施者、承認者、Cloco営業・技術窓口 |
| 事前証跡 | 現在設定、通話履歴、録音及びFAX原本の保持・バックアップ確認 |
| 合格条件 | 着信、発信、発信者番号、双方向音声、FAX、履歴及び監視 |
| 切戻し条件 | 着信不能、誤番号通知、片通話、FAX不成立、履歴欠落又は重大なセキュリティ異常 |
| 切戻し手段 | Cloco内の旧関連付けへ戻す操作主体、依頼方法及び所要時間 |

切戻し条件に該当した場合は、次の順番で処理する。

1. 試験端末からの外線発信を停止し、対象番号への追加変更を中止する。
2. Clocoへ事前合意した方法で切戻しを依頼するか、許可された管理操作で旧関連付けへ戻す。
3. 旧経路でTEL着信又はFAX受信が復旧したことを確認する。
4. 通話履歴、録音、FAX原本及び設定情報の欠落有無を確認する。
5. 発生日時、症状、SIP response、影響、切戻し時刻及び次回試験条件を障害記録へ残す。

代表番号、自社保有番号、行政・利用者・家族・関係機関に広く認知された番号は、低影響TEL/FAX各1番号の切替・切戻しと30日間の実運用が合格するまで変更しない。

## 7. 試験順序

1. キャリア疎通・REGISTER又はIP認証
2. 外線着信し、スマートフォンが呼び出されること
3. 双方向音声、保留、切断、再発信
4. 国内固定電話への外線発信と番号通知
5. 国内携帯電話への外線発信と番号通知
6. FAX受信、FAX送信、失敗通知
7. CDR、番号台帳、FAX履歴の突合
8. キャリア断、Asterisk再起動、端末オフライン時の挙動

## 8. 合格証跡

実際の電話番号、SIP認証情報、相手先電話番号、通話録音、FAX原本及び個人情報は公開リポジトリへ保存しない。試験台帳には日時、試験ID、DID末尾4桁をマスクした識別子、方向、結果、SIP response、音声品質、実施者、障害番号だけを残す。

## 9. MS-A2-2 Phone VM配置前監査

2026-08-22の読み取り専用再監査では、Disk空き約86GB、available memory約1.1GiB、Swapなし、既存コンテナ7件、SIP/RTP待受なしを確認した。UFWサービスはactiveだったが、実ルールは非対話sudoで取得できず、infra/Backendの両Git working treeには既存差分が残っていた。

過去のVPS readiness evidenceは当時の調査記録として保持するが、現在の配置判断には流用しない。既存差分の統合、MS-A2-2のCore/Auth/Phone resource分離、Cloco接続方式、firewall制御点、secret保管、第2NVMe、別物理障害領域backup及び切戻しを確定するまで顧客通信を接続しない。詳細な現行値は全体infra正本とMS-A2-2 Phone colocation change contractを参照する。

## 10. Phase 1構成と商用化前の差分

Phase 1の外部SIPはKamailio SBCだけで受け、RTPはRTPengineへ固定し、Asteriskを内部networkへ隔離する。隔離モックではスマホREGISTER、キャリア着信、スマホ発信、RTPengineのSDP書換えまで自動検査する。実キャリア接続情報を受領するまでは実疎通や実音声の合格とは扱わない。

外部顧客へ提供する前に、TLS/SRTP、モバイルPush、fraud検知・rate limit、冗長化、監視、暗号化backup、災害時切替、端末provisioning lifecycle及び実負荷試験を必須追加する。Phase 1の成功を、そのまま商用提供可能の判定に使わない。

### 10.1 顧客通信有効化前のresource計測

現時点では、対象host又はVM上の通話・FAX負荷を計測しておらず、`compose.phase1.yaml`にもservice別のCPU、memory又はprocess数上限を設定していない。顧客通信を有効化する前に、対象環境で少なくともidle、想定同時通話、通話中のevent配送、FAX処理及びDB処理を再現し、次をservice別に記録する。

- CPU使用量と飽和時間
- memoryの通常値、peak及び回収後の値
- process数とthread数のpeak
- 通話確立時間、API及びevent配送のlatency
- RTP packet loss、片通話、無音及び切断
- OOM kill、process異常終了、healthcheck失敗及びrestart回数
- host又はVM全体に残るCPU、memory、process及びstorageの余白

計測fixture、同時通話数、FAX件数、継続時間、対象SHA及び対象環境を証跡へ固定する。実電話番号、SIP credential、相手先番号、録音又はFAX原本は証跡へ保存しない。計測中に音声品質低下、event欠落、OOM、予期しないrestart又はhost余白不足が一件でもあれば、有効化を停止する。

計測結果からservice別のCPU、memory及びprocess数予算を決め、Compose上限、監視閾値、異常時停止条件及び切戻し手順を別の実装changeへ記録する。そのfixed SHAで隔離E2Eと同じ負荷条件を再実行し、上限内で品質と余白を維持できるまで顧客通信を有効化しない。未計測値又は過去の別環境の値を流用せず、この作業に伴ってCore又はAuthのresource若しくは配置を変更しない。
