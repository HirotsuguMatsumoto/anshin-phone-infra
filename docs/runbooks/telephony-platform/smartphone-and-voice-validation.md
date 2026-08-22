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
