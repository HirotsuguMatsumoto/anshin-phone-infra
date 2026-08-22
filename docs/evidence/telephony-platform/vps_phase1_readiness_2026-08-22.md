---
schema_version: 2
doc_id: anshin.phone.vps-phase1-readiness-2026-08-22
title: "VPS Phase 1配置前監査 2026-08-22"
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

# VPS Phase 1配置前監査 2026-08-22

## 1. 判定

**配置停止を継続する。**

2026年8月22日16時01分（日本時間）に、対象VPS `153.126.164.14`を読み取り専用で再監査した。SIP/RTPポートは待受しておらず、アンシンフォンの配置による外部公開は始まっていない。

UFWサービスはactiveだったが、非対話sudoでは実ルールを取得できなかった。UFW、nftables及びVPS事業者側packet filterのどこで最終的に通信を遮断・許可するかと、KamailioのSIP `5060/UDP`及びRTPengineのRTP `20000-20100/UDP`が許可済み接続元だけに限定されることを確認できていない。

infra及びBackendのVPS working treeには既存差分があり、Swapもない。既存アンシンマーケティングの稼働を保護するため、差分の帰属、firewall実ルール、リソース対策、backup及び切戻しを確定するまで上書き配置しない。

## 2. 確認結果

| 項目 | 2026-08-22確認結果 | 判定 |
| --- | --- | --- |
| OS・host | host `ik1-318-19010`。既存の2026-08-21監査から対象変更なし | 対象一致 |
| Disk | 約99GB中、使用約9%、空き約86GB | Phase 1に十分 |
| Memory | 約1.9GiB、確認時available約1.1GiB | 実行時制限と監視が必要 |
| Swap | なし | 配置停止条件 |
| 稼働コンテナ | 7件 | 既存サービス影響を要確認 |
| SIP/RTP待受 | `5060/UDP`、`20000/UDP`及び`20100/UDP`の待受なし | 未公開 |
| UFWサービス | active | サービス状態のみ確認 |
| Firewall実ルール | 非対話sudoでは取得不可 | 配置停止条件 |
| infra Git | branch `main`、tracked差分2件、未追跡を含む差分6件 | 上書き禁止 |
| Backend Git | branch `main`、tracked差分2件、未追跡を含む差分7件 | 上書き禁止 |

Git差分は件数だけを記録し、内容、秘密情報又は環境ファイルを本証跡へ複製していない。既存差分はユーザー又は既存運用の成果物として扱い、所有者判断なしにrestore、stash、reset、削除又は上書きしない。

## 3. 配置再開条件

1. VPS上のinfra及びBackend差分について、各ファイルの帰属と保持・統合方針をownerが確定する。
2. UFW、nftables及びVPS事業者側packet filterの実ルールを権限のある担当者が確認し、正本となる制御点を一つ確定する。
3. Clocoから接続元IP/CIDR、RTP範囲、認証方式、DID形式及びコーデックを受領する。
4. KamailioのSIP `5060/UDP`及びRTPengineのRTP `20000-20100/UDP`を、Cloco接続元と承認済み試験端末経路だけに許可する変更案と切戻し案をレビューする。
5. AsteriskのSIP及び内部RTP `10000-10100/UDP`がホストへ公開されないことを展開後設定で確認する。
6. 約2GiB RAM、Swapなし及び既存7コンテナを前提に、メモリ上限、OOM時の影響及びイメージbuild場所を確定する。
7. Git管理外のsecret保管、backup、ログ、監視及びアンシンフォンだけを停止・切戻しできる手順を確定する。

## 4. 実施していない操作

- サービス、コンテナ又はhostの再起動
- firewall、packet filter又は公開ポートの変更
- Gitのpull、commit、restore、stash、reset又はclean
- `.env`、secret、認証情報又はログ本文の参照
- アンシンフォンの配置又は実番号接続

本証跡は読み取り専用監査結果であり、配置承認、セキュリティ承認又は実番号接続の合格を意味しない。
