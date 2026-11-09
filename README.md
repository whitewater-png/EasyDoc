# Leafweaving — 軽量クロスプラットフォーム PDF エディタ

> **名前について**: 旧名 EasyDoc（〜0.4）→ Leafwright（0.5）→ **Leafweaving**（0.6〜）。
> 0.5 の「Leafwright」は同じ PDF 分野の既存サービスと名前が重なっていたため改名しました。
> 0.5 以前からの移行では、仮想プリンター「Leafwright PDF」の再登録と、設定・追加フォントの再設定が必要です。
> 0.5 で墨塗りした PDF の保護は、そのまま有効です。

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
| 墨塗り | 範囲内の文字・画像ピクセル・範囲に収まるベクター図形・注釈・代替テキスト・ページのサムネイルを PDF から**完全に削除**して黒で塗る(文書情報・しおりは対象外。後述)(上から黒い四角を重ねるだけではない)。範囲の外は一切変えない。範囲の縁をまたぐ図形(背景・罫線など)はそのまま残して黒い箱の下に隠し、黒い箱とともに選択・移動・削除できなくする。保存前なら Ctrl+Z で戻せる |
| PDF の統合 | 「PDF を結合」で複数ファイルを任意位置に挿入 |
| ページの抽出 | 範囲指定 (`1-3,5,8-`) で別ファイルへ抽出 |
| ページの編集 | 回転・削除・空白ページ挿入(A4/A3/A5/B4/B5/Letter/Legal)・前後移動・サムネイルのドラッグ&ドロップで並べ替え |
| ページの分割 | N ページごと、または範囲指定で複数ファイルに分割 |
| 国際規格に合わせた保存 | PDF 1.4〜2.0 のバージョン指定、PDF/A-1b・2b・2u・3b (ISO 19005)、PDF/X-3 (ISO 15930-6)。Ghostscript があれば本変換、無ければベストエフォート(後述)。リニアライズ(Web 最適化)対応 |
| さまざまなフォント | OS にインストール済みの TTF/OTF/TTC を自動検出して埋め込み。足りない文字(日本語など)は CJK フォールバックで自動補完。任意のフォントファイルの追加も可能 |
| 軽量 | 依存は PyMuPDF・pikepdf・PySide6-Essentials の 3 つのみ。Electron 等のブラウザランタイム不要 |
| 共通言語 | 100% Python。ネイティブ処理は MuPDF / QPDF / Qt (いずれも 3 OS 対応) |
| 印刷 | OS の印刷ダイアログから任意のプリンターに出力(ページ範囲・部数指定可)。ページごとに向きを自動調整 |
| 他アプリからの「印刷→Leafweaving」 | 「Leafweaving PDF」という仮想プリンターを OS に登録し、Word/Excel/PowerPoint など任意のアプリの印刷メニューから Leafweaving に直接 PDF を送れる(後述) |

元に戻す / やり直す (Undo/Redo) は全操作に対応しています(最大 30 段階)。

## インストール

### A. すぐ使えるアプリ版(インストール不要)

[Releases](https://github.com/whitewater-png/Leafweaving/releases) から OS に合ったファイルをダウンロードして展開するだけ。
Python のインストールは不要です。

| OS | ファイル | 起動方法 |
|---|---|---|
| Windows 10/11 (64bit) | `leafweaving-<ver>-windows-x86_64.zip` | 展開して `leafweaving\leafweaving.exe` を実行。初回は SmartScreen の「詳細情報 → 実行」が必要(未署名のため) |
| macOS (Apple Silicon) | `leafweaving-<ver>-darwin-arm64.dmg` | 開いて `leafweaving.app` をアプリケーションへ。初回は右クリック → 開く(未署名のため) |
| Linux (x86_64) | `leafweaving-<ver>-linux-x86_64.tar.gz` | 展開して `./leafweaving/leafweaving` |

バンドルは PyInstaller 製で、Python 本体・Qt・MuPDF・QPDF を同梱(展開後 約 250MB)。
PDF/A・PDF/X の本変換と PostScript 印刷ジョブの変換に使う Ghostscript は同梱していないので、必要なら別途インストールしてください。

自分でビルドする場合:

```bash
pip install -e . pyinstaller
python packaging/build.py        # release/ に zip / dmg / tar.gz ができる
```

タグ `v*` を push すると GitHub Actions が 3 種類(Windows / macOS arm64 / Linux)をビルドして Release に添付します。

### B. Python パッケージとして

```bash
git clone https://github.com/whitewater-png/Leafweaving.git
cd Leafweaving
python -m venv .venv
# Windows: .venv\Scripts\activate   /  macOS・Linux: source .venv/bin/activate
pip install -e .
leafweaving            # または  python -m leafweaving  /  leafweaving path/to/file.pdf
```

Python 3.10 以上が必要です。

### Ghostscript(任意・PDF/A, PDF/X の本変換に推奨)

| OS | インストール |
|---|---|
| Windows | https://ghostscript.com/releases/gsdnld.html のインストーラ(`gswin64c.exe` を自動検出) |
| macOS | `brew install ghostscript` |
| Linux | `sudo apt install ghostscript` など |

**10.08.0 以降**を入れてください(それより古い版には公開済みのセキュリティ上の欠陥があります。Linux ディストリビューションで修正がバックポート済みなのに番号が古い場合は、環境変数 `LEAFWEAVING_TRUST_GHOSTSCRIPT=1` で「修正済み」として扱えます)。

Ghostscript が見つからない場合、PDF/A・PDF/X 保存は **ベストエフォート** になります。
PDF バージョン設定・sRGB 出力インテント・XMP の規格識別・暗号化解除は行いますが、
フォント埋め込みや色空間変換は行えないため検証に合格する保証はありません。
保存時にその旨の警告を表示し、未埋め込みフォント名も列挙します。
本番用途では Ghostscript をインストールし、必要に応じて [veraPDF](https://verapdf.org/) 等で検証してください。

## 印刷と仮想プリンター

### プリンターに印刷する

ツールバーの「印刷」(Ctrl+P / ⌘P) で OS 標準の印刷ダイアログが開きます。ページ範囲・現在のページ・部数を指定でき、
横長ページは自動で横向きに出力されます。ページは MuPDF で最大 300dpi にラスタライズして送ります。

### 他のアプリから Leafweaving に「印刷」する(仮想プリンター)

Word・Excel・PowerPoint・ブラウザなど、印刷できるアプリなら何でも「Leafweaving PDF」プリンターを選ぶだけで
Leafweaving に PDF が開きます。仕組みは次のとおりです。

1. Leafweaving が `127.0.0.1:9100` (変更可) で RAW 印刷データを待ち受ける(ツールバー「印刷を受け付ける」をオン。状態は記憶されます)。
2. OS 側に、そのポートへ出力するプリンターキューを **1 回だけ** 作成する(ファイル → 「Leafweaving PDF」プリンターを設定…)。
   ダイアログの「今すぐプリンターを作成」で管理者権限を求めて自動登録するか、表示されたコマンドを手動で実行します。
3. 届いたデータ(PDF / XPS / PostScript)を PDF に変換して `inbox` フォルダに保存し、**開くかどうかを確認してから** Leafweaving で開きます。

安全のための制限:

- このポートには同じパソコン上のどのプログラムからも送れるため、届いたデータは信頼しない前提で扱います。
  PostScript は Ghostscript のサンドボックス(`-dSAFER`)の中でだけ変換し、公開済みのセキュリティ上の欠陥がすべて修正された **10.08.0 以降**でないと受け付けません。
  Linux ディストリビューションの Ghostscript で、修正がバックポート済みなのに番号が古い場合は、環境変数 `LEAFWEAVING_TRUST_GHOSTSCRIPT=1` で受け付けるようにできます。
- Web ページからこのポートへ送り込まれたデータ(HTTP)は黙って捨てます。PDF・XPS・PostScript 以外の形式も受け付けず、保存もしません。
- 1 件 256 MB・5 分まで、同時 2 件までです。
- 受け取った PDF は `inbox` に残ります。不要になったら手動で削除してください。

| OS | 作成されるキュー | 届く形式 | 補足 |
|---|---|---|---|
| Windows | Standard TCP/IP ポート + 「Microsoft Print To PDF」ドライバー | PDF (XPS/PS も自動判別) | `Add-PrinterPort` / `Add-Printer` (PowerShell、管理者権限) |
| macOS | `lpadmin … -v socket://127.0.0.1:9100 -m raw` | PDF | 印刷ダイアログの「PDF として保存」でも同様のことができます |
| Linux (CUPS) | `lpadmin … -v socket://127.0.0.1:9100 -m raw` | PDF (PS は Ghostscript で変換) | GTK/Qt/LibreOffice は PDF を送ります |

#### Linux 版に必要なシステムライブラリ

Linux の配布物には OS の共有ライブラリを同梱していません(ライセンス上の理由。NOTICE 参照)。Ubuntu 22.04 以降・それに相当する glibc 2.35 以降のディストリビューションで、次のパッケージが必要です(一覧の正本は [packaging/linux-runtime-packages.txt](packaging/linux-runtime-packages.txt)。リリース時に、素の `ubuntu:22.04` コンテナへこの一覧だけを入れて起動することを確認しています):

```bash
sudo apt install libgl1 libegl1 libglib2.0-0 libdbus-1-3 libfontconfig1 libfreetype6 libharfbuzz0b libgraphite2-3 libpng16-16 libbrotli1 libpcre2-8-0 libzstd1 libgssapi-krb5-2 libkrb5-3 libssl3 libffi8 libbz2-1.0 liblzma5 libexpat1 libuuid1 zlib1g libxkbcommon0 libxkbcommon-x11-0 libx11-6 libx11-xcb1 libxext6 libxfixes3 libxi6 libxrender1 libsm6 libice6 libxcb1 libxcb-cursor0 libxcb-glx0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render0 libxcb-render-util0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-util1 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1
```

受信フォルダ: Windows `%LOCALAPPDATA%\leafweaving\inbox`、macOS `~/Library/Application Support/leafweaving/inbox`、Linux `~/.local/share/leafweaving/inbox`。

> 注意: Windows 実機での動作は未検証です。Microsoft Print To PDF ドライバーが TCP ポートへ PDF 以外(XPS)を送る場合も
> 自動変換しますが、PostScript ドライバーを使う場合は Ghostscript が必要です。

## 使い方(主な操作)

| 操作 | 方法 |
|---|---|
| テキスト編集 | 「選択」ツールでテキストをクリック → ダイアログで編集 / 「このテキストを削除」 |
| テキスト追加 | 「テキスト」ツール (T) で開始位置をクリック |
| 図形追加 | 四角形 (R) / 楕円 (E) / 直線 (L) / 矢印 (A) ツールでドラッグ。線色・塗り・線幅はツールバーで |
| 図形の移動・削除 | 「選択」ツールでクリック → ドラッグで移動、Delete で削除 |
| 元からある図形の削除 | 「図形を消去」ツール (X) でクリック |
| 墨塗り | 「墨塗り」ツール (K) で範囲をドラッグ。選択中の文字・図形をまとめて墨塗りするなら 編集 → 選択範囲を墨塗り (Ctrl+Shift+K)。縁をまたぐ図形(ベクターの署名など)のデータも残したくないときはツールバーの「墨塗り: またぐ図形も消す」をオン(背景・表の枠も消え、白で隠した内容が見えることがあるので墨塗り後に確認。起動時は常にオフ) |
| ページ並べ替え | サムネイルをドラッグ&ドロップ、または Ctrl+Shift+↑/↓ |
| 回転 | Ctrl+[ / Ctrl+] |
| ズーム | Ctrl+ホイール、Ctrl+±、Ctrl+0 (幅合わせ)、Ctrl+1 (実寸) |
| 規格保存 | ファイル → 名前を付けて保存 / 規格書き出し (Ctrl+Shift+S は分割) |
| 印刷 | Ctrl+P / ⌘P |
| 他アプリから受信 | ツールバー「印刷を受け付ける」をオン → 他アプリで「Leafweaving PDF」に印刷 |
| ファイルを開く | ウィンドウに PDF をドラッグ&ドロップ(複数なら 2 つ目以降は結合) |

UI 言語は OS のロケールが日本語なら日本語、それ以外は英語になります。
`LEAFWEAVING_LANG=en` / `ja` で強制できます。

## 構成

```
leafweaving/
  app.py               エントリポイント
  core/                GUI 非依存のロジック(単体テスト対象)
    document.py        ドキュメント + スナップショット式 Undo/Redo
    pages.py           回転・削除・移動・並べ替え・挿入・結合・抽出・分割
    text_edit.py       テキストスパン抽出・置換・追加(フォールバック付き)
    shapes.py          図形(注釈)の追加・移動・削除、埋め込み図形の消去
    fonts.py           システムフォント検出・キャッシュ・PDF フォント名マッチング
    standards.py       PDF バージョン / PDF/A / PDF/X 保存 (Ghostscript or best effort)
    printserver.py     仮想プリンター(RAW/9100 受信サーバー、PDF/XPS/PS 変換、OS へのキュー登録)
  ui/                  PySide6 の画面
    main_window.py     メニュー・ツールバー・操作の結線
    page_view.py       ページキャンバス(ツール・座標変換・ホバー/選択)
    thumbnails.py      サムネイル一覧(D&D 並べ替え)
    dialogs.py         テキスト編集・保存・分割・抽出・結合・仮想プリンター設定ダイアログ
    printing.py        Qt 印刷(QPrinter へのページ描画、印刷ダイアログ)
    icons.py           QPainter で描画するアイコン(画像アセット不要)
    theme.py           Fusion ベースのライトテーマ(QSS)
    i18n.py            日本語 / 英語の文言
packaging/             PyInstaller spec とビルドスクリプト(アプリ版の作成)
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

- 墨塗りの対象はページの中身です(本文・画像・図形・注釈・代替テキスト・ページのサムネイル・ページ単位の XMP とアプリ固有データ `/PieceInfo`)。文書情報(タイトル・作成者)・文書全体の XMP の文字・しおり・添付ファイルにある文字は消えません。必要なら別途削除してください。
- PDF/A・PDF/X 保存で使う Ghostscript が 10.08.0 より古い場合、変換の**前に**「この文書を信頼しますか」と確認します。悪意ある PDF は変換中に Ghostscript の既知の欠陥を突ける可能性があるためです。「いいえ」なら Ghostscript を使わずベストエフォートで保存します。
- 自動更新は、リリースに添付された `SHA256SUMS.txt` と照合してから保存します。これで検出できるのはダウンロード中の破損や配信経路での改ざんで、GitHub のリリース自体が書き換えられた場合は検出できません。アプリ本体のコード署名(macOS の公証、Windows の Authenticode)はまだ行っていません。

## ライセンス

- **ソースコード**: MIT ([LICENSE](LICENSE))。`pip install` すると依存として AGPL-3.0 の PyMuPDF が入ります。
- **配布しているアプリ(Releases の .dmg / .zip / .tar.gz)**: PyMuPDF / MuPDF (AGPL-3.0) を同梱しているため、**アプリ全体としては GNU AGPL-3.0** で配布しています。
  同梱物のライセンス文と著作権表示(AGPL-3.0・LGPL-3.0・GPL-3.0・MPL-2.0・Apache-2.0、MuPDF 内蔵のライブラリ・フォント、Qt 内部のサードパーティ、CPython に組み込まれたライブラリ)と説明 ([NOTICE.txt](packaging/licenses/NOTICE.txt)) は、配布物の `LICENSES` フォルダに入っています。ビルド時には配布物内の全ネイティブライブラリを列挙し、NOTICE に無い出どころのものがあればビルドを失敗させます。
  対応するソースコード(Leafweaving 本体に加え、同梱した PyMuPDF・MuPDF・Qt・PySide6 などの同じバージョンのソース)は、各リリースのページに配布物と並べて添付しています。同梱した依存ライブラリの正確なバージョンは [packaging/constraints.txt](packaging/constraints.txt) にあります。
- 依存: PyMuPDF (AGPL-3.0) / pikepdf (MPL-2.0、qpdf は Apache-2.0) / PySide6・Qt (LGPL-3.0) / certifi (MPL-2.0)。Ghostscript は同梱せず、インストールされていれば外部プログラムとして呼び出します。

---

# Leafweaving — lightweight cross-platform PDF editor (English)

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
* Print to any printer through the native print dialog.
* Redaction: the Redact tool (K) permanently removes text, image pixels, vector art lying inside,
  annotations and alternate text in an area and blacks it out, without changing anything outside it.
  Drawings crossing the edge stay as they are, hidden under the box, and are locked with it.
* Virtual printer: register an "Leafweaving PDF" printer queue (TCP/IP port on 127.0.0.1) and print into
  Leafweaving from Word, Excel, PowerPoint or any other application; PDF, XPS and PostScript jobs are converted.
* Full undo / redo.

License: the source code is MIT.  The ready-to-run packages bundle PyMuPDF/MuPDF (AGPL-3.0), so each
package as a whole is distributed under the GNU AGPL-3.0; the license texts and notices are in its
`LICENSES` folder (see [packaging/licenses/NOTICE.txt](packaging/licenses/NOTICE.txt)).

```bash
pip install -e .
leafweaving [file.pdf]
```
