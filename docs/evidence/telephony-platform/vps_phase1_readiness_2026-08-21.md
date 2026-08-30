---
schema_version: 2
doc_id: anshin.phone.vps-phase1-readiness-2026-08-21
title: "VPS Phase 1配置前監査 2026-08-21"
domain: telephony-platform
document_kind: evidence
scope: product
product: anshin-phone
owner: anshin-phone-infra
authority: reference
status: inventory
risk_level: critical
source_doc_ids:
  - anshin.phone.phase1-real-number-runbook
consumers:
  - anshin-phone-infra
code_paths:
  - compose.phase1.yaml
  - scripts/audit_phase1_host.sh
contract_paths: []
test_paths: []
last_reviewed: "2026-08-22"
review_interval_days: 30
sensitivity: restricted
---

# VPS Phase 1配置前監査 2026-08-21

## 専門用語一覧

| 用語 | 正式名称・読み方 | 意味・本書での扱い |
| --- | --- | --- |
| VPS | Virtual Private Server | 仮想化された専用環境として利用するserver |
| Git | Git | ファイルの変更履歴とブランチを管理する分散型バージョン管理システム |
| Docker | Docker | アプリケーションと依存関係をcontainerとして実行・配布する基盤 |
| OS | Operating System | computerや端末のhardwareとapplicationを管理する基本software |
| LTS | Long-Term Support | 長期間の保守・security updateが提供されるrelease区分 |
| backend | Backend | server側でAPI、業務処理及びdata管理等を担うsoftware領域 |
| Redis | Redis | memory上のkey-valueデータを扱うdata store |
| PostgreSQL | PostgreSQL | open sourceのリレーショナルデータベース管理システム |
| MinIO | MinIO | S3互換APIを提供するobject storageソフトウェア |
| TCP | Transmission Control Protocol | 送達確認、順序制御及び再送を行う接続型の通信規約 |
| SIP | Session Initiation Protocol | IP網上で電話の発着信や通話sessionを制御する通信規約 |
| RTP | Real-time Transport Protocol | SIP等で確立した通話の音声データを運ぶ通信規約 |
| UDP | User Datagram Protocol | 送達確認や再送を必須としないdatagram型の通信規約 |
| IP | Internet Protocol | パケット通信網でデータの宛先と配送を制御する通信規約 |
| VPN | Virtual Private Network | public network上に暗号化等でprivateな通信経路を構成する仕組み |
| UFW | Uncomplicated Firewall | Linuxのfirewall ruleを管理するtool |

## 1. 判定

対象VPSはPhase 1の配置候補として利用可能だが、現時点では配置を実行しない。ファイアウォール、メモリ余力、既存の未コミット差分、secret保管、バックアップ及び切戻しを確定してから変更作業を承認する。

本監査は読み取り専用で行った。VPS上のファイル変更、Git操作、Docker起動・停止、port開放及び再起動は行っていない。

## 2. 確認結果

| 項目 | 2026-08-21確認結果 | 判定 |
| --- | --- | --- |
| OS | Ubuntu 24.04 LTS、x86_64 | 対応可能 |
| Disk | 約99GB中、使用約9%、空き約86GB | Phase 1に十分 |
| Memory | 約1.9GiB、確認時available約1.1GiB | 実行時制限と監視が必要 |
| Swap | なし | イメージbuild前に対策判断が必要 |
| Docker | Server 29.1.3 | 対応可能 |
| Docker Compose | 2.40.3 | 対応可能 |
| 既存サービス | アンシンマーケティングのWeb、Backend、worker、Redis、PostgreSQL、MinIOが稼働 | 競合・資源影響を事前確認 |
| 公開待受 | 22/TCP、80/TCP、443/TCP | SIP/RTPは未開放 |
| SIP/RTP | 外部SIP `5060/UDP`及び外部RTP `20000-20100/UDP`は未開放。Asterisk内部RTP `10000-10100/UDP`はホスト非公開 | キャリア情報確定後だけKamailio/RTPengineへの最小範囲を許可 |
| Firewall | 読み取り監査で有効状態を確認できず | 配置停止条件 |
| infra Git | `main`だが既存の変更・未追跡ファイルあり | 上書き禁止、統合方針が必要 |
| Backend Git | `main`だが既存の変更・未追跡ファイルあり | 上書き禁止、統合方針が必要 |

## 3. 配置前の必須対応

1. ローカルの検証済み差分を正規のcommitとして確定し、VPSの既存差分を消さずに比較する。
2. VPS側の既存差分について、保持、commit、退避又は破棄の責任者判断を得る。
3. キャリアのSIP接続元IP/CIDRとRTP範囲を受領し、5060/UDP及びRTPをその最小範囲だけ許可する。スマートフォン端末はVPN経路を優先する。
4. UFW、nftables又はVPS事業者側packet filterの有効な制御点を一つ確定し、ルールと切戻しをレビューする。
5. 約2GB RAM、Swapなし、既存サービス同居を前提に、AsteriskのVPS内build可否、メモリ上限、OOM時の影響を確認する。可能なら検証済みx86_64イメージを外部でbuildして配置する。
6. Git管理外のsecret保管先、権限、バックアップ、ローテーション及び緊急失効手順を確定する。
7. 現行マーケティング基盤のバックアップと、アンシンフォンだけを停止・切戻しできる手順を用意する。

## 4. 合格条件

- `scripts/audit_phase1_host.sh`の再実行結果に未解決の停止条件がない
- ローカルとVPSのGit差分が照合され、ユーザー作業を上書きしない
- SIP/RTP許可元が全世界ではなく、キャリア又はVPNの確定範囲に限定される
- 既存サービスを含むメモリ余力、Disk、ログローテーション及びコンテナhealthが監視される
- 配置、実番号試験、切戻しを別々の承認点として扱う
