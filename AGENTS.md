# Anshin Phone Infra agent rules

このrepositoryは、Anshin PhoneのSIP / PBX / Phase 1通信基盤を管理する。上位の`/Users/matsumotoyuuji/dev/AGENTS.md`と、このファイルを併用する。

- `.env*`、secret、実電話番号、SIP credential、通話・FAX原本を読み書き・追跡しない。
- キャリア契約、番号利用、緊急通報、電気通信事業、第三者提供の可否を実装だけから確定しない。
- 文書は`docs/manifest.yaml`に従い、`authority: reference`をowner承認なしにcanonicalへ昇格しない。
- 変更前に`git status --short`と近傍実装を確認し、既存のdirty差分を保持する。
- 文書変更は`bash scripts/build_check.sh --documents-only`、Phase 1構成変更は`bash scripts/build_check.sh --fast`で検証する。
- commit、push、本番接続、実番号試験はユーザーの明示指示なしに行わない。

<!-- anshin-document-governance:v2 -->
