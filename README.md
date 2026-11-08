# easydoc — 軽量クロスプラットフォーム PDF エディタ

GUI で直感的に操作できる、Python 製の軽量 PDF エディタです。
Windows / macOS / Linux で同じコードがそのまま動きます。

![screenshot](docs/screenshot.png)

## 機能

| 要件 | 実装 |
|---|---|
| GUI で簡単操作 | Qt (PySide6) 製。左にページサムネイル、中央にページビュー。ツールバーから選択/テキスト/四角形/楕円/直線/矢印/図形消去を切替 |
| PDF の読み取り・書き出し | PyMuPDF で読み込み・描画。画像 (PNG/JPEG/TIFF/SVG)・XPS・EPUB も PDF として開ける |
| 簡単な文章の編集 | テキストをクリック → ダイアログで文字列・フォント・サイズ・色を変更/削除。元の位置(ベースライン)に書き戻す。任意の位置に新規テキスト追加も可能 |
| 図形の挿入・削除 | 四角形・楕円・直線・矢印を注釈として追加(線色・塗り・線幅指定)。クリックで選択、ドラッグで移動、Delete で削除。PDF 内に元から埋め込まれたベクター図形も「図形を消去」ツールで削除 |
| PDF の統合 | 「PDF を結合」で複数ファイルを任意位置に挿入 |
| ページの抽出 | 範囲指定 (`1-3,5,8-`) で別ファイルへ抽出 |
| ページの編集 | 回転・削除・空白ページ挿入(A4/A3/A5/B4/B5/Letter/Legal)・前後移動・サムネイルのドラッグ&ドロップで並べ替え |
| ページの分割 | N ページごと、または範囲指定で複数ファイルに分割 |
| 国際規格に合わせた保存 | PDF 1.4〜2.0 のバージョン指定、PDF/A-1b・2b・2u・3b (ISO 19005)、PDF/X-3 (ISO 15930-6)。Ghostscript があれば本変換、無ければベストエフォート(後述)。リニアライズ(Web 最適化)対応 |
| さまざまなフォント | OS にインストール済みの TTF/OTF/TTC を自動検出して埋め込み。足りない文字(日本語など)は CJK フォールバックで自動補完。任意のフォントファイルの追加も可能 |
| 軽量 | 依存は PyMuPDF・pikepdf・PySide6-Essentials の 3 つのみ。Electron 等のブラウザランタイム不要 |
| 共通言語 | 100% Python。ネイティブ処理は MuPDF / QPDF / Qt (いずれも 3 OS 対応) |

元に戻す / やり直す (Undo/Redo) は全操作に対応しています(最大 30 段階)。

## インストール

```bash
git clone https://github.com/whitewater-png/easydoc.git
cd easydoc
python -m venv .venv
# Windows: .venv\Scripts\activate   /  macOS・Linux: source .venv/bin/activate
pip install -e .
easydoc            # または  python -m easydoc  /  easydoc path/to/file.pdf
```

Python 3.10 以上が必要です。

### Ghostscript(任意・PDF/A, PDF/X の本変換に推奨)

| OS | インストール |
|---|---|
| Windows | https://ghostscript.com/releases/gsdnld.html のインストーラ(`gswin64c.exe` を自動検出) |
| macOS | `brew install ghostscript` |
| Linux | `sudo apt install ghostscript` など |

Ghostscript が見つからない場合、PDF/A・PDF/X 保存は **ベストエフォート** になります。
PDF バージョン設定・sRGB 出力インテント・XMP の規格識別・暗号化解除は行いますが、
フォント埋め込みや色空間変換は行えないため検証に合格する保証はありません。
保存時にその旨の警告を表示し、未埋め込みフォント名も列挙します。
本番用途では Ghostscript をインストールし、必要に応じて [veraPDF](https://verapdf.org/) 等で検証してください。

## 使い方(主な操作)

| 操作 | 方法 |
|---|---|
| テキスト編集 | 「選択」ツールでテキストをクリック → ダイアログで編集 / 「このテキストを削除」 |
| テキスト追加 | 「テキスト」ツール (T) で開始位置をクリック |
| 図形追加 | 四角形 (R) / 楕円 (E) / 直線 (L) / 矢印 (A) ツールでドラッグ。線色・塗り・線幅はツールバーで |
| 図形の移動・削除 | 「選択」ツールでクリック → ドラッグで移動、Delete で削除 |
| 元からある図形の削除 | 「図形を消去」ツール (X) でクリック |
| ページ並べ替え | サムネイルをドラッグ&ドロップ、または Ctrl+Shift+↑/↓ |
| 回転 | Ctrl+[ / Ctrl+] |
| ズーム | Ctrl+ホイール、Ctrl+±、Ctrl+0 (幅合わせ)、Ctrl+1 (実寸) |
| 規格保存 | ファイル → 名前を付けて保存 / 規格書き出し (Ctrl+Shift+S は分割) |

UI 言語は OS のロケールが日本語なら日本語、それ以外は英語になります。
`EASYDOC_LANG=en` / `ja` で強制できます。

## 構成

```
easydoc/
  app.py               エントリポイント
  core/                GUI 非依存のロジック(単体テスト対象)
    document.py        ドキュメント + スナップショット式 Undo/Redo
    pages.py           回転・削除・移動・並べ替え・挿入・結合・抽出・分割
    text_edit.py       テキストスパン抽出・置換・追加(フォールバック付き)
    shapes.py          図形(注釈)の追加・移動・削除、埋め込み図形の消去
    fonts.py           システムフォント検出・キャッシュ・PDF フォント名マッチング
    standards.py       PDF バージョン / PDF/A / PDF/X 保存 (Ghostscript or best effort)
  ui/                  PySide6 の画面
    main_window.py     メニュー・ツールバー・操作の結線
    page_view.py       ページキャンバス(ツール・座標変換・ホバー/選択)
    thumbnails.py      サムネイル一覧(D&D 並べ替え)
    dialogs.py         テキスト編集・保存・分割・抽出・結合ダイアログ
    i18n.py            日本語 / 英語の文言
tests/                 pytest(コア + オフスクリーン GUI スモーク)
```

## テスト

```bash
pip install -e .[dev]
QT_QPA_PLATFORM=offscreen pytest
```

## 既知の制限

- テキスト編集は「スパン(同一フォント・同一行の連続文字)」単位です。段落の再流し込みは行いません。
- 元の PDF のフォントが OS に無い場合は、名前と属性(太字/斜体/セリフ/等幅)から最も近いフォントに置き換えます。
- PDF/X-4 は Ghostscript が対応していないため常にベストエフォート(識別メタデータのみ)です。
- 埋め込みベクター図形の削除は、クリックした図形のバウンディングボックス内に完全に収まる線画を取り除きます。重なった図形は巻き込まれることがあります(Undo 可能)。

## ライセンス

MIT。PyMuPDF (AGPL-3.0) / pikepdf (MPL-2.0) / PySide6 (LGPL-3.0) に依存します。
配布形態によっては PyMuPDF の AGPL 条件にご注意ください。

---

# easydoc — lightweight cross-platform PDF editor (English)

A GUI PDF editor written entirely in Python (PySide6 + PyMuPDF + pikepdf) that runs
unchanged on Windows, macOS and Linux.

* Open PDFs (and images / XPS / EPUB), render, save.
* Edit existing text spans (string, font, size, colour) and add new text; any installed
  TTF/OTF font can be used, with automatic CJK fallback.
* Insert rectangles / ellipses / lines / arrows, move and delete them; erase vector drawings
  baked into the page.
* Merge files, extract pages, split documents, rotate / delete / insert / reorder pages
  (drag & drop thumbnails).
* Save as a specific PDF version (1.4–2.0), PDF/A-1b/2b/2u/3b or PDF/X-3 — a real conversion
  when Ghostscript is installed, a clearly-labelled best-effort otherwise — with optional linearization.
* Full undo / redo.

```bash
pip install -e .
easydoc [file.pdf]
```
