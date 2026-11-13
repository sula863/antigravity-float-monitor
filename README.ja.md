<div align="center">

# Antigravity Float Monitor · 桌面任务与实时额度监控悬浮窗

**Google Antigravity 向けの軽量 Windows デスクトップフローティング監視ウィジェット**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)

[简体中文](README.md) | [English](README.en.md) | **日本語**

</div>

---

## ✨ 主な機能

- **2つの表示モード**：コンパクトな**ミニピル（Pill）**と詳細表示の**カード（Card）**をワンクリックで切り替え可能。Windows 11 のアクリルブラー効果に対応しています。
- **マルチウィンドウ自動認識**：稼働中の Antigravity セッションを自動検出し、実行中のタスクを最優先（`W1`）で表示。マウスホイールやボタンで即座に切り替えでき、ダブルクリックで対象ウィンドウを前面に呼び出せます。
- **トークン消費ゼロでリアルタイム残量を取得**：バックグラウンドスレッドからローカルの Language Server RPC に直接接続し、各モデルの 5 時間 / 週間クォータ残量とリセットまでのカウントダウンを表示します。
- **ハートビート監視＆緊急停止**：ログやタスクの更新停止を検知してアラート表示。ワンクリックの緊急停止・再開ボタンや、フルスクリーンアプリ使用時の自動非表示モードも搭載しています。
- **快適な非同期処理**：RPC 通信とファイル監視は専用の `QThread` で実行されるため、UI のドラッグや操作が一切重くなりません。

---

## 🚀 クイックスタート

### 1. 依存パッケージのインストール

Windows 環境の **Python 3.10+** で以下を実行します：

```bash
pip install -r requirements.txt
```

### 2. バックグラウンド起動

**`start_monitor.bat`** または **`start_monitor.vbs`** をダブルクリックするか、以下を実行してください：

```bash
pythonw float_monitor.py
```

### 3. デモ再生

`simulate_task.bat` を実行すると、3 段階タスクの動作デモを確認できます。

---

## 📄 ライセンス

[MIT License](LICENSE) の下で公開されています。
