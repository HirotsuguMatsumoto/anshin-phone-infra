# Anshin Phone Infra agent rules

## 専門用語一覧

| 用語 | 正式名称・読み方 | 意味・本書での扱い |
| --- | --- | --- |
| repository | Repository | source code、文書及び変更履歴を一まとまりで管理する単位 |
| SIP | Session Initiation Protocol | IP網上で電話の発着信や通話sessionを制御する通信規約 |
| PBX | Private Branch Exchange | 内線、外線、着信振分け及び転送等を制御する電話交換システム |
| MD | Markdown | 見出し、表、link等をplain textで記述する文書形式 |
| FAX | Facsimile | 電話網等を使って文書画像を送受信する通信サービス |
| YAML | YAML Ain't Markup Language | indentとkey-valueで構造化データを表すテキスト形式 |
| Git | Git | ファイルの変更履歴とブランチを管理する分散型バージョン管理システム |

このrepositoryは、Anshin PhoneのSIP / PBX / Phase 1通信基盤を管理する。上位の`/Users/matsumotoyuuji/dev/AGENTS.md`と、このファイルを併用する。

- `.env*`、secret、実電話番号、SIP credential、通話・FAX原本を読み書き・追跡しない。
- キャリア契約、番号利用、緊急通報、電気通信事業、第三者提供の可否を実装だけから確定しない。
- 文書は`docs/manifest.yaml`に従い、`authority: reference`をowner承認なしにcanonicalへ昇格しない。
- 変更前に`git status --short`と近傍実装を確認し、既存のdirty差分を保持する。
- 文書変更は`bash scripts/build_check.sh --documents-only`、Phase 1構成変更は`bash scripts/build_check.sh --fast`で検証する。
- commit、push、本番接続、実番号試験はユーザーの明示指示なしに行わない。

<!-- anshin-document-governance:v2 -->
