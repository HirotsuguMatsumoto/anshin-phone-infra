---
schema_version: 2
doc_id: anshin.phone.cloco-sip-trunk-interface
title: Cloco SIPトランク接続・責任分界の確認仕様
domain: telephony-platform
document_kind: spec
scope: product
product: anshin-phone
owner: anshin-phone-infra
authority: reference
status: draft
risk_level: high
source_doc_ids: [anshin.corporate.anshin-phone.cloco-response-2026-09-30, anshin.corporate.anshin-phone.notification-status, anshin.infrastructure.system-architecture]
consumers: [anshin-phone-infra, anshin-phone-backend, anshin-corporate-strategy]
code_paths: [compose.phase1.yaml, configs/carrier-intake.example.json]
contract_paths: [docs/specs/changes/2026-10-20-filing-acceptance-cloco-intake.change.yaml]
test_paths: [scripts/build_check.sh]
last_reviewed: "2026-10-20"
review_interval_days: 30
sensitivity: restricted
---

# Cloco SIPトランク接続・責任分界の確認仕様

## 専門用語一覧

| 用語 | 正式名称・読み方 | 意味・本書での扱い |
| --- | --- | --- |
| SIP | Session Initiation Protocol | 通話の発着信を制御する通信規約 |
| RTP | Real-time Transport Protocol | 通話音声を運ぶ通信規約 |
| PSTN | Public Switched Telephone Network | 一般電話網 |
| SBC | Session Border Controller | 当社側でSIP接続を制御する境界設備 |
| IP-PBX | Internet Protocol Private Branch Exchange | IP網上で外線・内線を制御する交換設備 |
| FAX | Facsimile | 電話網等を使う文書送受信 |
| SHA-256 | Secure Hash Algorithm 256-bit | 原本ファイルの同一性を確認するchecksum |

## 根拠と確定範囲

2026年9月30日にownerが提示したCloco 吉村様の返信と[添付設備構成図](../../references/telephony-platform/SIPトランク設備構成図.pdf)全1ページを確認した。PDFのSHA-256は `bcdb481faa2d67e0337d35706ff56130b20bbfae5cef902b6c548452d1fed884` である。この日付は確認日であり、メール送受信日時は未確認である。

Cloco回答で確認できたのは、インターネット経由のSIPトランク接続、電話番号のSIPトランク経由提供、番号数の上限なし、及び以下の概略境界である。

```text
一般電話網 <-> Cloco SIPトランク | 責任分界点 | 当社IP-PBX <-> 当社側電話端末
```

添付図はIP-PBXの例としてAsterisk又はAspireX等を示している。実際の当社構成、呼流、物理配置、契約許諾及び詳細接続仕様の承認書ではない。契約前に確認する番号認定資料を含む回答の行政・契約上の位置づけは `anshin-corporate-strategy/documents/evidence/anshin-phone/cloco-response-2026-09-30.md` を参照する。

## 当社の予定経路への対応

添付図の下流IP-PBX部分を、当社のSBC、音声中継、非公開Asterisk及び端末へ対応させる。ただし、この詳細構成は当社設計であり、Cloco図に明示されたものではない。

| 領域 | Cloco資料で確認できた範囲 | 当社の予定実装又は未確定事項 |
| --- | --- | --- |
| 番号・一般電話網接続 | Cloco設備の一般電話網とSIPトランク | 番号通知形式、地域別供給、緊急通報及び既存番号付替え条件を個別確認 |
| 卸接続 | インターネット経由SIPトランク | 接続元・接続先、認証、SIP/RTP、暗号化、チャネル容量を確認 |
| 接続境界 | SIPトランクと当社IP-PBXの間 | 具体的なアドレス・port・interface・障害対応の分担は未確定 |
| 当社通信設備 | 図にはIP-PBXと端末を例示 | 当社計画はKamailio SBC、RTPengine、非公開Asterisk及びSIP端末 |
| 当社管理系 | Cloco図には記載なし | 当社API・番号台帳・DBは音声の直列経路へ含めず、管理経路として扱う |
| 物理配置 | Cloco図に記載なし | 技術正本の2026-10-17実配備記録はMS-A2-1の専用VM `anshin-phone/ms-a2-1-phone`。提出準備時のMS-A2-2は履歴として、実提出の構成との差を行政判断正本で照合する |

## 接続情報受領時の未確定項目

番号数の上限なしは同時通話数の上限なしを意味しない。当初提供番号数、同時通話数、チャネル数及び単位時間当たり発信数は別に確定する。

- SIP/RTP接続先と接続元の許可範囲、port及び認証方式
- コーデック、DTMF、着信番号・発信者番号の通知形式、TLS/SRTPの可否
- FAX方式、T.38又はG.711、再送・品質及び通話チャネルとの関係
- 110・118・119、番号区画・所在地確認、番号移転及び転送の条件
- 障害通知、停止・復旧、SLA、冗長接続及び切戻し

受領した値は[キャリア接続情報受領手順](../../runbooks/telephony-platform/vps-deployment-and-carrier-intake.md)に従い、Git外の台帳へ記録する。SIP credential、実電話番号及び接続情報を本仕様へ追記しない。

## 実接続前の状態

2026年10月20日にowner提示の通知書原本を確認し、電気通信事業届出の受理・当社届出番号A-08-24437を確認した。届出日は2026年10月2日、通知日は10月16日。証跡・Git外保管と提出内容の未照合範囲は `anshin.corporate.anshin-phone.notification-status` を参照する。予定卸元ClocoのA-27-14344を当社番号で上書きしない。

| 接続準備 | 現在の確認結果・次の作業 |
| --- | --- |
| 当社の事業届出 | 受理通知・届出番号確認済み。取得待ちを再開しない |
| 番号使用計画 | 標準計画の当社への適用確認・完成保存、独自設備・転送を含む必要手続は未確認。受理通知を番号認定証にしない |
| Clocoへの提示・契約 | 受理通知は提示準備可能。実提示、契約第2条・第18条等の書面確定・契約締結は未確認 |
| 実接続入力 | 既存資格台帳・許可済みprimary設定を先に照合し、当該Phone用SIP/RTP・認証・番号通知・FAX・チャネル条件を既存consumer検証へ通す。資格本文はGit・logへ出さない |
| 実回線・番号移行 | 未確認。卸トランク資格を顧客端末へ配布せず、模擬carrier成功を実Cloco成功へ読み替えない |
| 実施範囲 | 資料更新と既存の接続準備を進める。外部への連絡・送信、契約・発注・番号付替えは実行許可に広げない |

実回線の法令・契約の各条件と詳細技術仕様を照合する。管理基盤の本番化と実回線開通は分ける。この資料更新自体はruntime、firewall、DNS又は実番号経路を変更しない。
