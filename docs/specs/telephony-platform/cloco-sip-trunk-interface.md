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
contract_paths: [docs/specs/changes/2026-10-29-cloco-provider-alignment.change.yaml]
test_paths: [scripts/build_check.sh]
last_reviewed: "2026-10-29"
review_interval_days: 30
sensitivity: restricted
---

# Cloco SIPトランク接続・責任分界の確認仕様

## 専門用語一覧

| 用語 | 正式名称・読み方 | 意味・本書での扱い |
| --- | --- | --- |
| SIP / RTP | Session Initiation Protocol / Real-time Transport Protocol | 発着信制御 / 音声伝送の規約 |
| PBX / SBC | Private Branch Exchange / Session Border Controller | 交換設備 / 当社端末側の境界制御設備 |
| B2BUA | Back-to-Back User Agent | 上流と下流のSIP通話を別々に終端する当社PBXの役割 |
| DID | Direct Inward Dialing | Clocoから提供される着信電話番号 |
| REGISTER / Contact | SIP Registration / Contact Header | 登録処理 / SIPの到達先を示すヘッダー |
| Via / SDP | Via Header / Session Description Protocol | SIP応答経路 / 媒体アドレス・port・codecの記述 |
| NAT | Network Address Translation | private/publicアドレスを変換する当社ネットワーク処理 |
| PJSIP / chan_sip | PJSIP / Asterisk SIP Channel Driver | 現PBX実装 / マニュアルの設定例に使われる旧driver |
| PCMU / DTMF | G.711 μ-law / Dual-Tone Multi-Frequency | 初期音声codec / 電話の数字キー情報 |
| PAI | P-Asserted-Identity | 発信者識別ヘッダー。番号別From指定の代替とはしない |
| T.38 / UDPTL | ITU-T T.38 / UDP Transport Layer | IP FAX規約 / T.38の媒体転送方式 |
| CPS | Calls Per Second | 単位秒の呼処理数。番号数・同時通話数とは別 |
| FAX / IP-PBX | Facsimile / Internet Protocol Private Branch Exchange | 文書画像の電話送受信 / IP網上の交換設備 |
| CIDR / ID | Classless Inter-Domain Routing / Identifier | 通信元アドレス範囲の表記 / 識別子 |
| SHA-256 | Secure Hash Algorithm 256-bit | 原本や成果物の同一性を確認するchecksum |

## 1. 設計の原則と根拠

**Clocoの既存サービス・接続仕様に当社が合わせる。Clocoに当社向けの構成変更、新規処理、NAT保証又は独自構成のサポートを依頼しない。** 当社の内部制約が仕様と両立しない場合は当社側の設計を見直す。接続成立を先方の特別対応へ依存させない。

根拠は[提供設備図](../../references/telephony-platform/SIPトランク設備構成図.pdf)（SHA-256 `bcdb481faa2d67e0337d35706ff56130b20bbfae5cef902b6c548452d1fed884`）、10/28 16:42の吉村様回答、[SIPトランク2 IP-PBX接続マニュアル Ver2.0.1](https://manual.cldpbx.com/wp-content/uploads/2026/09/siptrunk2_manual_Ver2.0.1.pdf)（2026-09-16、44頁）。10/29に元メールとマニュアル本文を再確認。PDF本文には一部文字抽出の乱れがあり、原PDF byte/hashと全頁画像は未取得。Cloco回答は責任分界の同意であり、当社全設備・機能の動作保証ではない。

技術接続の詳細は本書に集約する。契約・番号制度・届出比較は `anshin.corporate.anshin-phone.cloco-architecture-comparison` を参照し、本書で法的適用を確定しない。既存文書のauthorityはreferenceのまま維持する。本改訂は再設計であり、製品実装・ネットワーク適用・回線受入の完了ではない。

## 2. 採用する論理構成と責任分界

最小接続試験は、Clocoが提供する標準トランクと当社PBXを直接接続し、当社内のSIP端末一つで検証する。当社独自のスマホ経路をCloco側へ要求しない。これは当社の試験順序であり、試験用回線の数量・相手先は先方の標準提供条件に合わせる。

```text
最初の標準接続試験（未実装・未実施）
一般電話網 ⇄ Cloco標準SIPトランク | 責任分界 | 当社Asterisk ⇄ 社内試験SIP端末

製品側を組み込む目標構成（未実装・未実施）
SIP: Cloco ⇄ Asteriskのcarrier接続口・PBX ⇄ Kamailio ⇄ 当社端末
RTP: Cloco ⇄ Asteriskのcarrier媒体口・PBX ⇄ RTPengine ⇄ 当社端末
管理: 管理API・DB ⇄ PBXの番号/内線/権限/履歴/FAX結果（音声経路外）
```

Asterisk一つがcarrier接続とPBXを担うB2BUAとする。新しい中継製品又はPBX二重化を必要条件にしない。carrier legからKamailioの透過REGISTERとRTPengineを外す設計へ改め、両者は必要な端末側処理だけに用いる。現在の `compose.phase1.yaml` とテンプレートはこの目標に未対応で、適用してはならない。

| 処理 | 当社側の担当・設計 |
| --- | --- |
| 上流認証・登録 | AsteriskがClocoから提供される標準方式を一つ使用。認証チャレンジ、登録更新・失敗・回復を終端。卸資格を端末や管理画面へ配布しない |
| 上流SIP dialog | AsteriskがContact/Via/Route等を生成しACK/BYE/CANCEL/再INVITEまで保持。端末のContactや私設IPを上流へ透過しない |
| 上流媒体 | Asterisk自身がCloco側SDPの接続先とcodecを終端。direct mediaは使わず、当社が保有・管理し実到達する媒体口を広告 |
| 下流SIP・媒体 | 別dialog・別transportとして端末側SBC/中継へ接続。端末側の広告アドレスと上流向け広告アドレスを別設定にし、自動分離を推定しない |
| 着信番号 | ToのDIDを主に識別し、Alert-Infoが存在する場合は照合。割当台帳のtenant・音声/FAX用途・内線へ正規化。Request-URI又はREGISTER ContactのuserをDID正本にしない |
| 発信番号 | 認証IDと通知DIDを分離。tenant/端末の権限確認後、許可DIDを上流B-legのFromへ設定。音声/FAXの両方で実送出Fromを検証し、固定from_userやPAIだけで代替しない |
| FAX | Clocoの既存提供条件で可能な方式だけを当社PBXで終端。T.38は未確定。利用する場合はUDPTLの到達性・port・fallbackをRTPと分けて設計 |

Asterisk 22.10.1/PJSIPは既存資産を使う当社保守候補とする。マニュアルp3の動作確認済一覧外でサポート対象外であり、先方確認済みと表記しない。旧chan_sipの設定をそのまま流用できるとも、旧世代へ戻せば安全とも判断しない。後続の実装で当社がwire適合性と保守性を検証し、不成立なら当社側componentを再選定する。Clocoに現候補への特別サポートを求めない。

## 3. ネットワーク・登録・媒体の具体化

マニュアルp3はCloco側VoIPサーバ全てを送信元とし、送信元UDP 5060/10000～20000を許可する案内である。これを当社の宛先port範囲と混同しない。初期音声は設定例のPCMUへ絞り、DTMF等は提供条件と試験で確定する。設定例の登録3600秒はサービスの許容上限保証ではない。登録方式は標準パスワード認証を第一候補とし、実提供された標準方式へ当社が合わせる。固定IP認証への変更を決定していない。

| 区間 | 設計値の決め方・受入 |
| --- | --- |
| Cloco → 当社SIP口 | 提供元の現行VoIP送信元一覧、送信元port、当社宛先IP/portを別fieldで管理。Asteriskで認識するpeerを限定し、端末REGISTERや未認証発信へ上流用信頼を流用しない |
| 当社 → Cloco | 提供されたログインサーバ、transport、認証方式を適用。FQDN解決、認証、REGISTER/再登録、登録先Contactの到達を当社が確認 |
| Cloco ⇄ 当社媒体口 | Cloco側送信元範囲、当社側受信RTP範囲、SDP内アドレス/port、NAT対応をそれぞれ記録。媒体packetの実受信と双方向音声を確認 |
| PBX ⇄ 端末側中継 | carrier側とは別のSIP/媒体口・到達許可・広告先を使用。内部対向と端末認証を限定し、外部端末へ卸資格を渡さない |

現在のMS-A2-1専用private VMと、ルーターpublicポート転送を追加しない既存制約だけでは、上記の着信・媒体到達が成立したとは言えない。REGISTER成功・keepalive・advertise設定だけで解決したとしない。**物理接続口と経路の採用は未確定**であり、現在環境での実接続へ進める設計完成とは報告しない。

当社内で次の順に選定する。①既存の承認済み自社接続口・経路でSIP/RTPの双方向到達を確保できるかinventoryする。②不足する場合、標準通信条件を満たす当社管理の接続口への配置変更を、所在地・経路・費用・障害切分け・届出への差分込みで具体化する。③新規調達・公開設定・ルーター制約変更が必要なら具体案をownerへ示し、その変更の指示前に適用しない。VPNやHTTPS公開の存在だけでUDP経路があると推定しない。Clocoへ『ポート転送なしで使えるようにしてほしい』『代替方式を設計してほしい』とは依頼しない。

## 4. 現実装との差分と内部実装順序

比較元Infra `a858e152c07d06f0250631cf8f79f5040a4282eb`、Backend `abe90f6fdb401149e7dc85d8269ba04a0d522ce9`。記載はsourceのread-only照合であり、今回の本番live観測ではない。

| ID | 現実装 | 後続の当社修正と合格条件 |
| --- | --- | --- |
| R1 接続境界 | AsteriskがSBCをoutbound_proxyとしてcarrier登録・発信。Kamailio/RTPengineが上流にも介在 | carrier用transport・auth・registration・媒体口をAsteriskに集約。上流proxy設定を分離し、REGISTER/INVITE/response/dialog/SDPの実線上でCloco標準に一致 |
| R2 到達性 | private VM、SBC広告IP、RTPengine 20000～20100の設定 | 接続口の実在・送信元/宛先/NAT/媒体範囲を当社で確定。数値の重なりでは判定しない。アイドル後・再登録後も着信と音声が成立 |
| R3 着信 | TEL_DID/FAX_DIDとEXTENで分岐 | Toから番号正規化。Alert-Infoは存在時照合。欠落だけで拒否する新必須条件にしない。不一致・不正形式・未割当・他tenantを拒否し、正当な複数DIDを分離 |
| R4 発信 | 固定from_user=TEL_DIDとCALLERID/PAIが併存 | 固定Fromの衝突を解消し、認証IDを保ったまま音声/FAXの上流B-leg Fromへ許可番号を反映。未割当通知・別tenantの番号指定を拒否 |
| R5 音声/FAX | ulaw/alaw、T.38設定あり。実carrier未受入 | 初期PCMU音声の成立を優先。FAXは既存条件と実送達/失敗を別に確認。T.38又はPCMUの設定有無でFAX成立としない |
| R6 容量・管理 | 模擬通話・管理経路の検証済み資産 | 実契約のチャネル/予約/番号関連付けへ当社が合わせる。社内試験期間に許された範囲だけで制限/履歴/再送を検証 |

認証API・管理DB・本人履歴の受入済み経路は再利用する。carrier適合のための変更pathは既存 `deploy/asterisk/`、`deploy/kamailio/`、`compose.phase1.yaml`、firewall/intake renderer、既存SIP fixtureとする。本改訂ではこれらのruntime sourceを変更しない。実装時は当該変更のcontractと既存selectorで必要な検査を選ぶ。

## 5. 当社の検証順序と受入結果の扱い

| 段階 | 当社が用意する検証 | 現在状態 |
| --- | --- | --- |
| 0 資料・接続口 | manualへの要求対応、接続口/経路/提供資格/試験許可の具体化 | 論理再設計、物理接続口・提供条件は未確定 |
| 1 標準音声 | PBXと社内試験端末のみ。登録・アイドル後着信・再登録、双方発信/切断、再INVITE、双方向音声、許可番号のFrom | 未実装・未試験 |
| 2 製品接続 | 端末側SBC/媒体中継、組織/内線権限、複数DID、ToとRequest-URIが異なる着信、Alert-Info有無/不一致/未知番号、番号別From、履歴 | 未実装・未試験 |
| 3 FAX・容量 | 方式回答に従うFAX実送受信/対向結果/失敗、契約上限と当社制限、ログ切分け | 未実装・未試験 |
| 4 顧客提供 | 番号制度・契約・所在/設備手続・品質・告知・実機等の必要条件 | 未完了。社内試験の成功で顧客提供可としない |

当社fixtureによるwire回帰と、許可された実Cloco環境の受入を分ける。障害時は当社側で時刻・匿名化したSIP応答・媒体経路を切り分け、既存窓口が指定する情報だけを相談する。独自構成全体のデバッグ・試験設計・合格保証をClocoへ依頼しない。

## 6. 外部照会・行政・現在の適用状態

Clocoへお願いするのは、既にご案内いただいた社内テストの標準案内（利用範囲・費用・手続）、既存FAX提供条件、行政回答後の通常必要書類だけとする。現行一覧等もmanual/提供資料/管理画面で取得できるものは当社で確認し、未記載又は交付が必要な情報だけを既存窓口へお願いする。回答形式、特別な構成図、新規処理又は当社試験の合格判定を先方へ指定しない。

番号制度と設備配置手続は10/28に担当別へ照会済み。認定等を得るために単純再販と称して独自PBX/ID機能を隠さない。保存届出図はMS-A2-2専用コンテナ、管理基盤実配備はMS-A2-1専用VM、新設計のcarrier接続口は未選定という三段階を区別する。提出原本、送付済みPDF、契約原本は変更しない。

native認証・本人履歴の受入と、Cloco音声/FAX開通は別である。telephony_enabled=falseを維持し、今回のproduction mutationとメール送信は0件。source/consumer/change contractは本書metadata、検証は文書selector・図/返信/PDF同期とfixed SHA独立レビュー。管理runtimeの再配備は行わない。

PDCA：前回は方針の語調修正にとどまり、技術正本と出力TXTを同期しなかった。今回はcarrier終端・番号変換・媒体・段階試験を当社責務で設計し、同じ正本からTXTとPDFを生成して出力実体を照合する。実接続・性能・業務効果は未計測。
