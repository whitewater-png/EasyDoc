"""Tiny translation table (Japanese / English) selected from the system locale."""
from __future__ import annotations

import locale
import os

_STRINGS: dict[str, tuple[str, str]] = {
    # key: (en, ja)
    "app.title": ("easydoc PDF Editor", "easydoc PDF エディタ"),
    "menu.file": ("&File", "ファイル(&F)"),
    "menu.edit": ("&Edit", "編集(&E)"),
    "menu.page": ("&Page", "ページ(&P)"),
    "menu.view": ("&View", "表示(&V)"),
    "menu.tools": ("&Tools", "ツール(&T)"),
    "menu.help": ("&Help", "ヘルプ(&H)"),
    "act.new": ("&New", "新規作成(&N)"),
    "act.open": ("&Open…", "開く(&O)…"),
    "act.save": ("&Save", "上書き保存(&S)"),
    "act.saveas": ("Save &As / Export…", "名前を付けて保存 / 規格書き出し(&A)…"),
    "act.merge": ("&Merge PDFs into this document…", "PDFを結合(&M)…"),
    "act.quit": ("&Quit", "終了(&Q)"),
    "act.undo": ("&Undo", "元に戻す(&U)"),
    "act.redo": ("&Redo", "やり直す(&R)"),
    "act.delete_sel": ("&Delete selected shape", "選択図形を削除(&D)"),
    "act.rot_left": ("Rotate &Left", "左に回転(&L)"),
    "act.rot_right": ("Rotate &Right", "右に回転(&R)"),
    "act.del_page": ("&Delete page", "ページを削除(&D)"),
    "act.insert_page": ("&Insert blank page…", "空白ページを挿入(&I)…"),
    "act.move_up": ("Move page &up", "ページを前へ(&U)"),
    "act.move_down": ("Move page d&own", "ページを後ろへ(&O)"),
    "act.extract": ("&Extract pages…", "ページを抽出(&E)…"),
    "act.split": ("&Split document…", "ドキュメントを分割(&S)…"),
    "act.zoom_in": ("Zoom &in", "拡大(&I)"),
    "act.zoom_out": ("Zoom &out", "縮小(&O)"),
    "act.zoom_fit": ("Fit &width", "幅に合わせる(&W)"),
    "act.zoom_100": ("&Actual size", "実寸(&A)"),
    "act.about": ("&About", "バージョン情報(&A)"),
    "act.add_font": ("Add font &file…", "フォントファイルを追加(&F)…"),
    "tool.select": ("Select", "選択"),
    "tool.text": ("Text", "テキスト"),
    "tool.rect": ("Rectangle", "四角形"),
    "tool.ellipse": ("Ellipse", "楕円"),
    "tool.line": ("Line", "直線"),
    "tool.arrow": ("Arrow", "矢印"),
    "tool.erase": ("Erase drawing", "図形を消去"),
    "tip.select": ("Click text to edit it, click a shape to select it (Delete removes it)",
                   "テキストをクリックで編集、図形をクリックで選択(Deleteで削除)"),
    "tip.text": ("Click where new text should start", "新しいテキストの開始位置をクリック"),
    "tip.shape": ("Drag to draw", "ドラッグして描画"),
    "tip.erase": ("Click an existing vector drawing to remove it", "既存のベクター図形をクリックで消去"),
    "lbl.stroke": ("Stroke", "線色"),
    "lbl.fill": ("Fill", "塗り"),
    "lbl.width": ("Width", "線幅"),
    "lbl.font": ("Font", "フォント"),
    "lbl.size": ("Size", "サイズ"),
    "lbl.none": ("none", "なし"),
    "lbl.pages": ("Pages", "ページ"),
    "lbl.page_of": ("Page {0} / {1}", "{0} / {1} ページ"),
    "lbl.zoom": ("Zoom {0}%", "ズーム {0}%"),
    "lbl.ranges_help": ("e.g. 1-3,5,8-", "例: 1-3,5,8-"),
    "dlg.edit_text": ("Edit text", "テキストを編集"),
    "dlg.new_text": ("New text", "新しいテキスト"),
    "dlg.text": ("Text", "テキスト"),
    "dlg.color": ("Color", "色"),
    "dlg.delete_text": ("Delete this text", "このテキストを削除"),
    "dlg.original_font": ("Original font: {0}", "元のフォント: {0}"),
    "dlg.saveas": ("Save As / Export", "名前を付けて保存 / 規格書き出し"),
    "dlg.standard": ("Standard", "規格"),
    "dlg.version": ("PDF version", "PDFバージョン"),
    "dlg.keep": ("keep current", "現在のまま"),
    "dlg.linearize": ("Optimize for fast web view (linearize)", "Web表示用に最適化(リニアライズ)"),
    "dlg.compress": ("Compress streams & remove unused objects", "ストリーム圧縮・不要オブジェクト削除"),
    "dlg.gs_found": ("Ghostscript found: {0} — full PDF/A & PDF/X conversion available",
                     "Ghostscript検出: {0} — PDF/A・PDF/X の完全変換が可能"),
    "dlg.gs_missing": ("Ghostscript not found — PDF/A & PDF/X will be best-effort only (not guaranteed to validate)",
                       "Ghostscript未検出 — PDF/A・PDF/X はベストエフォート(検証合格は保証されません)"),
    "dlg.title_meta": ("Title", "タイトル"),
    "dlg.author_meta": ("Author", "作成者"),
    "dlg.split": ("Split document", "ドキュメントを分割"),
    "dlg.split_every": ("Every N pages:", "N ページごと:"),
    "dlg.split_ranges": ("By ranges (one per line):", "範囲指定(1行に1ファイル):"),
    "dlg.out_dir": ("Output folder", "出力フォルダ"),
    "dlg.prefix": ("File prefix", "ファイル名の接頭辞"),
    "dlg.browse": ("Browse…", "参照…"),
    "dlg.extract": ("Extract pages", "ページを抽出"),
    "dlg.extract_ranges": ("Pages to extract:", "抽出するページ:"),
    "dlg.merge": ("Merge PDFs", "PDFを結合"),
    "dlg.add_files": ("Add files…", "ファイルを追加…"),
    "dlg.remove": ("Remove", "削除"),
    "dlg.up": ("Up", "上へ"),
    "dlg.down": ("Down", "下へ"),
    "dlg.insert_at": ("Insert after page (0 = at start, blank = at end):",
                      "挿入位置(この番号のページの後。0=先頭、空欄=末尾):"),
    "dlg.insert_page": ("Insert blank page", "空白ページを挿入"),
    "dlg.page_size": ("Page size", "用紙サイズ"),
    "dlg.position": ("Position", "挿入位置"),
    "dlg.before_current": ("Before current page", "現在のページの前"),
    "dlg.after_current": ("After current page", "現在のページの後"),
    "msg.saved": ("Saved to {0} ({1})", "{0} に保存しました ({1})"),
    "msg.saved_warn": ("Saved with warnings", "警告付きで保存しました"),
    "msg.unsaved": ("The document has unsaved changes. Save them?", "未保存の変更があります。保存しますか?"),
    "msg.error": ("Error", "エラー"),
    "msg.open_failed": ("Could not open file:\n{0}", "ファイルを開けません:\n{0}"),
    "msg.split_done": ("Wrote {0} files to {1}", "{1} に {0} ファイルを書き出しました"),
    "msg.extract_done": ("Extracted {0} pages to {1}", "{0} ページを {1} に抽出しました"),
    "msg.merge_done": ("Added {0} pages", "{0} ページを追加しました"),
    "msg.need_doc": ("Open or create a document first", "先にドキュメントを開くか作成してください"),
    "msg.about": ("easydoc {0}\nLightweight cross-platform PDF editor.\n\nPyMuPDF {1} · pikepdf {2} · Qt {3}",
                  "easydoc {0}\n軽量クロスプラットフォームPDFエディタ\n\nPyMuPDF {1} · pikepdf {2} · Qt {3}"),
    "filter.pdf": ("PDF files (*.pdf);;All files (*)", "PDFファイル (*.pdf);;すべてのファイル (*)"),
    "filter.open": ("Documents (*.pdf *.xps *.epub *.png *.jpg *.jpeg *.tiff *.svg);;All files (*)",
                    "ドキュメント (*.pdf *.xps *.epub *.png *.jpg *.jpeg *.tiff *.svg);;すべてのファイル (*)"),
    "filter.font": ("Fonts (*.ttf *.otf *.ttc)", "フォント (*.ttf *.otf *.ttc)"),
    # printing
    "act.print": ("&Print…", "印刷(&P)…"),
    "act.vprinter": ("Receive print jobs (virtual printer)", "印刷を受け付ける(仮想プリンター)"),
    "act.vprinter_setup": ("Set up the \"easydoc PDF\" printer…", "「easydoc PDF」プリンターを設定…"),
    "msg.printed": ("Sent {0} pages to the printer", "{0} ページをプリンターに送信しました"),
    "msg.print_failed": ("Printing failed:\n{0}", "印刷に失敗しました:\n{0}"),
    "msg.vprinter_on": ("Virtual printer listening on 127.0.0.1:{0}", "仮想プリンター待受中 127.0.0.1:{0}"),
    "msg.vprinter_off": ("Virtual printer stopped", "仮想プリンターを停止しました"),
    "msg.vprinter_fail": ("Could not start the virtual printer on port {0}:\n{1}",
                          "ポート {0} で仮想プリンターを開始できません:\n{1}"),
    "msg.job_received": ("Print job received: {0}", "印刷ジョブを受信: {0}"),
    "msg.job_failed": ("A print job could not be converted:\n{0}", "印刷ジョブを変換できませんでした:\n{0}"),
    "dlg.vprinter": ("Virtual printer setup", "仮想プリンターの設定"),
    "dlg.vprinter_intro": (
        "Print from Word, Excel, PowerPoint or any other application straight into easydoc.\n"
        "easydoc listens on a local network port; the operating system needs a printer queue that "
        "sends its output to that port. Create it once with the command below, then keep "
        "\"Receive print jobs\" switched on while printing.",
        "Word・Excel・PowerPoint など任意のアプリの「印刷」から、easydoc に直接 PDF を送れます。\n"
        "easydoc はローカルのネットワークポートで待ち受けます。OS 側に、そのポートへ出力するプリンター"
        "キューを 1 回だけ作成してください(下のコマンド)。印刷するときは「印刷を受け付ける」をオンにしておきます。"),
    "dlg.vprinter_port": ("Port", "ポート"),
    "dlg.vprinter_cmd": ("Command (run as administrator / with sudo):", "コマンド(管理者権限 / sudo で実行):"),
    "dlg.vprinter_install": ("Create printer now", "今すぐプリンターを作成"),
    "dlg.vprinter_remove": ("Remove printer", "プリンターを削除"),
    "dlg.vprinter_copy": ("Copy command", "コマンドをコピー"),
    "dlg.vprinter_status_yes": ("Printer \"{0}\" is installed.", "プリンター「{0}」は設定済みです。"),
    "dlg.vprinter_status_no": ("Printer \"{0}\" is not installed yet.", "プリンター「{0}」は未設定です。"),
    "dlg.vprinter_status_unknown": ("Printer status could not be determined.", "プリンターの状態を確認できませんでした。"),
    "dlg.vprinter_note_win": (
        "Windows: uses the built-in \"Microsoft Print To PDF\" driver on a Standard TCP/IP port. "
        "If a job arrives as XPS or PostScript it is converted automatically (PostScript needs Ghostscript).",
        "Windows: 標準の「Microsoft Print To PDF」ドライバーを Standard TCP/IP ポートで使用します。"
        "XPS や PostScript で届いた場合も自動変換します(PostScript は Ghostscript が必要)。"),
    "dlg.vprinter_note_mac": (
        "macOS: creates a raw CUPS queue; applications send PDF directly. "
        "(macOS can also \"Save as PDF\" from any print dialog, then open the file in easydoc.)",
        "macOS: raw の CUPS キューを作成します。アプリは PDF をそのまま送ります。"
        "(macOS の印刷ダイアログ「PDF として保存」→ easydoc で開く、でも同じことができます)"),
    "dlg.vprinter_note_linux": (
        "Linux: creates a raw CUPS queue; GTK/Qt/LibreOffice applications send PDF directly. "
        "PostScript jobs are converted with Ghostscript.",
        "Linux: raw の CUPS キューを作成します。GTK/Qt/LibreOffice 系アプリは PDF をそのまま送ります。"
        "PostScript は Ghostscript で変換します。"),
    "dlg.vprinter_result_ok": ("Printer created.", "プリンターを作成しました。"),
    "dlg.vprinter_result_fail": ("Command failed:\n{0}", "コマンドが失敗しました:\n{0}"),
    "grp.file": ("FILE", "ファイル"),
    "grp.edit": ("EDIT", "編集"),
    "grp.tools": ("TOOLS", "ツール"),
    "grp.page": ("PAGES", "ページ"),
    "grp.view": ("VIEW", "表示"),
    "grp.style": ("STYLE", "スタイル"),
    "lbl.drop_hint": ("Drop a PDF here, or use File ▸ Open", "ここに PDF をドロップ、またはファイル ▸ 開く"),
}


def _detect_lang() -> str:
    forced = os.environ.get("EASYDOC_LANG")
    if forced:
        return forced[:2].lower()
    try:
        from PySide6.QtCore import QLocale

        name = QLocale.system().name()
    except Exception:  # pragma: no cover
        name = locale.getdefaultlocale()[0] or "en"
    return "ja" if (name or "").lower().startswith("ja") else "en"


LANG = _detect_lang()


def tr(key: str, *args) -> str:
    en, ja = _STRINGS.get(key, (key, key))
    s = ja if LANG == "ja" else en
    return s.format(*args) if args else s
