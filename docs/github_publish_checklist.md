# GitHub公開前チェックリスト

公開前に次を確認してください。

## 秘密情報・ローカルファイル

- [ ] `.env` が含まれていない
- [ ] `data/*.db` が含まれていない
- [ ] `__pycache__` が含まれていない
- [ ] `.pytest_cache` が含まれていない
- [ ] `*.pyc` が含まれていない
- [ ] `.venv` または `venv` が含まれていない
- [ ] 不要なログファイルが含まれていない
- [ ] APIキーやパスワードがコード内にない
- [ ] `.env.example` は設定例だけになっている

## ドキュメント

- [ ] READMEの起動手順が最新
- [ ] docs/images に管理画面スクリーンショットを配置した
- [ ] README.md でスクリーンショットが表示されることを確認した
- [ ] `docs/portfolio.md` を確認した
- [ ] `docs/operation_manual.md` を確認した
- [ ] `docs/cloudworks_portfolio_text.md` を確認した
- [ ] `docs/demo_scenario.md` を確認した
- [ ] `SECURITY.md` を確認した
- [ ] `CHANGELOG.md` を確認した

## 動作確認

- [ ] `python -m compileall app ui` が成功している
- [ ] `python -m pytest -q` が成功している
- [ ] FastAPI `/health` が `{"status": "ok"}` を返す
- [ ] Streamlit管理画面が起動する
- [ ] 管理画面のスクリーンショットを撮った
- [ ] 画像に個人情報・APIキー・パスワードが写っていないことを確認した
- [ ] サンプル予約データ作成が動く
- [ ] CSV出力が日本語列名で出力される

## スクリーンショット公開時の注意

- [ ] スクリーンショットには、実在の顧客名、電話番号、メールアドレス、LINEユーザーID、APIキー、パスワードを載せない
- [ ] 公開用画像では、サンプル太郎、demo-user-001 などの確認用データを使う

## 公開後

- [ ] READMEにスクリーンショットを追加する場合、秘密情報が写っていない
- [ ] リポジトリ説明文に「LINE予約受付」「FastAPI」「Streamlit」などの要点を入れた
- [ ] クラウドワークス・ランサーズ掲載文とGitHub URLを対応させた
