# MCD Bridge v0.1 の構成

Megadev v1.2.0 (`7a7246c14b845ad2f1bd3c7d73afb04cf67d83ef`) を固定し、
ネイティブCD起動を使う開発基盤です。カートリッジのMode 1起動ではありません。

## 起動とCPUの分担

1. 日本版BIOSがCD上のIP/SPをロードする。
2. Main IPがVBlankを有効にし、毎フレームSub INT2を送る。
3. Sub常駐カーネルがISO9660のルートファイル一覧をキャッシュする。
4. Mainが`IPX.MMD`を要求し、SubがWord RAMへロードして所有権を返す。
5. MMDの自己コピー処理がプログラムをMain Work RAMへ移し、Cの`main()`を呼ぶ。
6. サンプルが画像をCDからロードしてVDPに転送し、ADPCMをロード・展開する。

CDアクセスはMegadevのINT2駆動コルーチンを使用します。
IRQと競合しないよう、ファイル名・バッファを書いてから最後に`access_op`を発行します。
Mainからの要求はノンブロッキングです。Subはディスク読み込み完了を待ちながら
PCMの状態監視を続け、ADPCM展開は256サンプルずつ処理します。

## メモリ配置

次の表は基本のメディアデモの配置です。ノベルと動画の追加領域は後述します。
音声ステージング、動画先読み、立ち絵の退避領域は同時使用するものではありません。

| CPU / 装置 | 範囲 | 用途 |
|---|---|---|
| Main Work RAM | `FF0000–FFBFFF` | アプリケーションコード・定数（上限48 KiB） |
| Main Work RAM | `FFC000–FFDFFF` | `.bss` / `.data`（上限8 KiB） |
| Main Work RAM | `FFF000–FFF017` | サンプルの検証用テレメトリ24バイト |
| Main Work RAM | `FFF700`以降 | BIOS・割り込みベクタ・スタック用に予約 |
| Sub PRG RAM | `006000–00BFFF` | SP・常駐サービス・CDコルーチン・ディレクトリキャッシュ（24 KiB） |
| Sub PRG RAM | `020000–02FFFF` | 圧縮音声のステージング（64 KiB） |
| Word RAM 2M | Main `200000–23FFFF` / Sub `080000–0BFFFF` | ファイル受け渡し用（256 KiB） |
| PCM Wave RAM | `0000–FFFF` | モノラル音声と無音ループ末尾 |
| VRAM | `0020–8C1F` | 背景画像1120タイル |
| VRAM | `9000–9BFF` | 自作フォント96タイル |
| VRAM | `C000` / `E000` | Plane Aの文字 / Plane Bの画像 |

## IPCの契約

キューは1要求分です。処理中の追加要求は`false`を返します。
`MCD_update()`は**1フレームにつき1回**呼びます。通常は`SYS_doVBlankProcess()`が呼び出します。

| レジスタ | 書き手 | 内容 |
|---|---|---|
| COMCMD0 | Main | コマンド。パラメータを書いた後に最後に発行する |
| COMCMD1–5 | Main | コマンド別のアセット番号、オフセット、バイト数、転送先等 |
| COMSTAT0 | Sub | 完了したコマンド。MainのCOMCMD0=0を確認して0に戻す |
| COMSTAT1 | Sub | エラーコード |
| COMSTAT2–3 | Sub | 読み込みバイト数、または動画PCMの再生サンプル数 |
| COMSTAT4 | Sub | PCM準備／再生・CD-DA要求・動画音声・動画ソースの予約状態 |
| COMSTAT5 | Sub | INT2カウンタ |
| COMSTAT6–7 | Sub | ABI版`0102`・起動完了マジック`4D43` |

Subはファイル転送の終了前にWord RAMを返しません。
ファイルサイズと2048バイト単位の書き込み範囲を転送前に検査します。
Mainは要求完了と所有権の返却を確認してから`MCD_getWordRAM()`の有効なポインタを取得します。
SubにWord RAMを渡している間は、別の窓を含めてMainから参照しません。
動画PCMのCLOCK要求はWord RAMを渡さず、画面転送と並行して処理できます。
動画プレイヤーはMainが所有している間に限りPCM一括補充の記述子を書き込みます。

Mainは1800フレーム、Subの読み込みは1200 INT2を超えるとタイムアウトします。
タイムアウトでは転送先を再利用せず、再起動が必要な状態にします。
電源投入直後のBIOS自体のドライブ初期化はBIOSの動作に従います。

## SGDK風APIの対応範囲

`make libs`で`build/libmcd_main.a`と`build/libmcd_sub.a`を生成します。
サンプルもこの2つの静的ライブラリをリンクしています。
アプリケーションは`include/mcd/bridge.h`を取り込み、Main側ライブラリをリンクします。
Sub側は常駐サービスとディスクのアセットIDテーブルを構成するためのライブラリです。
SP起動コード・MegadevのCDコルーチン・リンカスクリプトは併せて必要です。
独立した既存SGDK ROMへそのままリンクする用途ではありません。
通常のGCC M68k ABI（32ビットの`int`・引数スロット）を使用します。
BIOS呼び出しラッパーのスタック配置が変わるため、`-mshort`は使用しないでください。

| API | 現在の機能 |
|---|---|
| `SYS_doVBlankProcess()` | VBlank待ち、パッド更新、MCD要求と範囲パレットフェードの進行 |
| `JOY_readJoypad(JOY_1)` | 1Pの3ボタンパッド入力 |
| `PAL_setPalette()` | パレット0–3、16色の即時設定 |
| `VDP_drawText()` | 8×8フォント、設定したPlane A/B、40×28セルの文字描画 |
| `VDP_drawImage()` | 独自MIMG形式、320×224・16色・Plane A/B |
| `MCD_readFileAsync()` | アセットIDによるCD→Word RAM読み込み |
| `MCD_prepareADPCMAsync()` | CD→Sub PRG RAM→ソフト展開→PCM Wave RAM |
| `MCD_playADPCM()` / `MCD_stopADPCM()` | 読み込み済み音声の再生・停止 |
| `MCD_playCDDA(2, repeat)` | トラック2の再生 |
| `MCD_pauseCDDA()` / `MCD_resumeCDDA()` / `MCD_stopCDDA()` | BIOSによる音声トラック制御 |

タイル転送、矩形タイルマップ、スクロール、入力エッジ等の追加APIは
[SGDK対応表](sgdk-compatibility.md)にまとめています。
SGDKの`Image`構造体、ResComp出力、DMAキュー、スプライトエンジン、XGM/Z80音源ドライバとの
互換性はありません。上表のAPI名は移植時の扱いやすさを意図したものです。

CD-DAの状態フラグは**BIOSへ要求した状態**であり、物理ドライブのTOC／再生位置を
連続取得した状態ではありません。再生確認はエミュレータの音声出力で行っています。

## 音声とディスクの制限

メガCDのRF5C164はPCM音源です。ADPCMハードウェアデコーダーを想定せず、
IMA/DVI 4ビットADPCMをSub CPUで展開しています。

- 独自コンテナ`MIMA`、バージョン1、モノラル22050 Hzに対応。
- 最大65534サンプル。2秒のサンプルは44100サンプル、圧縮ペイロード22050バイト。
- RF5C164の符号・絶対値形式へ変換し、ループ記号`FF`との衝突を回避。
- 基本のADPCMデモはWave RAMへ事前展開する。ノベルの2系統IMAリング補充と、動画のCD先読み＋PCM補充は別サービス。
- 読み込み済みADPCMはCD-DAと同時再生できます。
- CDのデータ読み込みとCD-DAの継続再生は光学ドライブを共有するため、データ読み込み時にCD-DAを停止します。
- CDはISO9660 Level 1、ルートのみ、1ディレクトリセクタまで。アセットはSubのテーブルに登録します。
- サンプルは日本・NTSC専用。その他のリージョン・PAL・別BIOSの確認は未実施です。

## 次の拡張単位

汎用の任意ファイル名API、TOC検証・実ドライブ状態取得、バックアップRAM、
VRAM DMAキュー、SGDKの汎用スプライト管理・ResComp互換を
個別に追加できます。BIOS・Subサービス・Main APIの境界を維持して進めます。

基盤資料: [Megadev CDアクセス](https://github.com/drojaazu/megadev/blob/v1.2.0/docs/cdrom.md)、
[ディスク構成](https://github.com/drojaazu/megadev/blob/v1.2.0/docs/disc.md)、
[PCMレジスタ](https://github.com/drojaazu/megadev/blob/v1.2.0/lib/sub/pcm.def.h)。


## 動画・エディター拡張（2026-09-07）

GCC 13の`-O2`で隣接した1バイトのフラグをまとめる最適化が、奇数アドレスへの
`CLR.W`を生成し、68000のアドレス例外になる事例を動画の再開経路で確認した。
再生状態のフラグをワード境界へ置き、共通CFLAGSで`-fno-store-merging`を指定する。
Main/Subとも同じ設定で再ビルドする。ビルド成功だけではこの例外を検出できず、
音声付き動画をキャッシュ境界まで実行する検査が必要となる。

SGDK風APIの対応表と追加サンプルは [sgdk-compatibility.md](sgdk-compatibility.md)。
MD Novelの共通プロジェクトは `tools/build_editor_novel.py` が読み、作品の
`out/mcd/` 配下に ISO/CUE/音声トラックを出力する。MDの生成Cや原本JSONを上書きしない。

IPC ABI 0102 は動画ソース、PCM一括補充、立ち絵作業領域の保存／復元を含む。
Main/Subを必ず同時に再ビルドする。動画中は既存IMAストリームをリセットし、
Word RAM所有権を転送・供給・保存／復元の完了まで戻さない。
PCMの枯渇時は古いリングを繰り返さず停止する。
SP領域は固定Megadevが用意する `SP_LENGTH` で24KiBとした（boot上限28KiB以内）。
依存ライブラリのリンカスクリプト自体は変更しない。

| コマンド | 番号 | COMCMDの引数／完了条件 |
|---|---:|---|
| VIDEO_AUDIO_BEGIN / FEED / PLAY / STOP / CLOCK | 13–17 | 単一補充と16kHz動画PCM。詳細は[動画PCM](video-pcm.md) |
| VIDEO_SOURCE_OPEN | 18 | CMD1=0、CMD2–3=NOVEL.PAK内絶対オフセット、CMD4–5=長さ。予約と最初の先読み発行で完了 |
| VIDEO_SOURCE_READ | 19 | CMD1=Word転送先セクタ、CMD2–3=動画先頭からの相対オフセット、CMD4–5=長さ。実コピー完了後にWordを返却 |
| VIDEO_SOURCE_CLOSE | 20 | 引数なし。進行中のCD要求が終わってから先読み予約を解除 |
| VIDEO_AUDIO_FEED_BATCH | 21 | CMD1–2=Word内記述子オフセット、CMD3=件数。全記述子を検査してからPCMへ供給 |
| VIDEO_WORKSPACE_SAVE / RESTORE | 22–23 | 引数なし。Word内の立ち絵64KiBを退避／復元してから所有権を返却 |

READは2048バイト境界・最大64KiBで、要求開始位置の逆行を拒否する。
前回の終端を含む重複読込や192KiBのバンク境界をまたぐコピーは許可する。
古いPRGバンクは、次の要求開始位置がその終端以降へ進むまで再利用しない。
先読みエラーはREADへ引き継ぎ、CLOSEが排出完了まで予約を保つ。
タイムアウトではコルーチンの`access_op`を消さず隔離し、別用途へバッファを返さない。

| 動画中の領域 | 範囲（Wordは先頭からのオフセット） | 用途 |
|---|---|---|
| Sub PRG | `0x10000..0x3FFFF` / `0x40000..0x6FFFF` | 各192KiBの非同期CD先読みバンク |
| Sub PRG | `0x70000..0x7DFFF` / `0xE000..0xFFFF` | 立ち絵64KiBの退避先（56KiB＋8KiB） |
| Word RAM 2M | `0x00000..0x17FFF` / `0x18000..0x1FFFF` | ノベルのスクリプト96KiB／フォント32KiBを保持 |
| Word RAM 2M | `0x20800..0x2FFFF` / `0x30800..0x3FFFF` | 映像データの62KiB窓を2面 |
| Word RAM 2M | `0x20000..0x207FF` / `0x30000..0x307FF` | 各窓の予約セクタ。現在のPCM記述子は`0x30000`を使用 |

通常の立ち絵はWord RAM `0x20000..0x2FFFF`に4×16KiBの画素を置き、メタデータはMainに保持する。
動画開始前にこの64KiBを退避して窓を増やし、EOF／スキップ後に元の位置へ復元する。
退避中はSOURCE_CLOSE後も通常のCD／IMA命令を拒否し、BGMキャッシュが退避データを上書きするのを防ぐ。
SAVEとRESTOREは動画PCMが未開始またはSTOP済みのときだけ受け付け、既存のCD先読みとは重ならない領域を使う。
保存・復元・PRGからWordへのコピーはいずれも2KiBずつ処理し、SubループでPCM更新を継続する。

ノベルのスクリプト・フォントを保持したまま2M Word RAMの所有権を受け渡すため、1M交換は使用しない。
光学先読みはMainがWordを所有している間もPRGへ進み、次の窓の音声を前倒しで供給する。
性能と再バッファの実測は[動画ライブラリ](video.md)に記録する。設定FPSの保証とは区別する。
退避・先読み・排出・タイムアウトのホスト検査は`tests/test_video_source.py`で実行できる。
