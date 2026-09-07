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

| CPU / 装置 | 範囲 | 用途 |
|---|---|---|
| Main Work RAM | `FF0000–FFBFFF` | アプリケーションコード・定数（上限48 KiB） |
| Main Work RAM | `FFC000–FFDFFF` | `.bss` / `.data`（上限8 KiB） |
| Main Work RAM | `FFF000–FFF017` | サンプルの検証用テレメトリ24バイト |
| Main Work RAM | `FFF700`以降 | BIOS・割り込みベクタ・スタック用に予約 |
| Sub PRG RAM | `006000–009FFF` | SP・常駐サービス・CDコルーチン・ディレクトリキャッシュ |
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
| COMCMD1–2 | Main | アセット番号、トラック番号、リピート指定 |
| COMSTAT0 | Sub | 完了したコマンド。MainのCOMCMD0=0を確認して0に戻す |
| COMSTAT1 | Sub | エラーコード |
| COMSTAT2–3 | Sub | 読み込みバイト数 |
| COMSTAT4 | Sub | PCM準備済み・PCM再生中・CD-DA要求状態 |
| COMSTAT5 | Sub | INT2カウンタ |
| COMSTAT6–7 | Sub | ABI版`0100`・起動完了マジック`4D43` |

Subはファイル転送の終了前にWord RAMを返しません。
ファイルサイズと2048バイト単位の書き込み範囲を転送前に検査します。
Mainは要求完了の確認後にだけ`MCD_getWordRAM()`の有効なポインタを取得できます。
次の要求に進む前に画像等を消費してください。MainからのWord RAM直接書き込みはAPI外です。

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
| `SYS_doVBlankProcess()` | VBlank待ち、パッド更新、MCD要求の進行 |
| `JOY_readJoypad(JOY_1)` | 1Pの3ボタンパッド入力 |
| `PAL_setPalette()` | パレット0–3、16色の即時設定 |
| `VDP_drawText()` | 8×8フォント、Plane A、40×28セルの文字描画 |
| `VDP_drawImage()` | 独自MIMG形式、320×224・16色・Plane A/B |
| `MCD_readFileAsync()` | アセットIDによるCD→Word RAM読み込み |
| `MCD_prepareADPCMAsync()` | CD→Sub PRG RAM→ソフト展開→PCM Wave RAM |
| `MCD_playADPCM()` / `MCD_stopADPCM()` | 読み込み済み音声の再生・停止 |
| `MCD_playCDDA(2, repeat)` | トラック2の再生 |
| `MCD_pauseCDDA()` / `MCD_resumeCDDA()` / `MCD_stopCDDA()` | BIOSによる音声トラック制御 |

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
- Wave RAMに事前展開するため、再生中のCDストリーミングはまだありません。
- 読み込み済みADPCMはCD-DAと同時再生できます。
- CDのデータ読み込みとCD-DAの継続再生は光学ドライブを共有するため、データ読み込み時にCD-DAを停止します。
- CDはISO9660 Level 1、ルートのみ、1ディレクトリセクタまで。アセットはSubのテーブルに登録します。
- サンプルは日本・NTSC専用。その他のリージョン・PAL・別BIOSの確認は未実施です。

## 次の拡張単位

任意ファイル名対応とアセットパック、TOC検証・実ドライブ状態取得、複数PCMチャンネル、
ADPCMのリングバッファ展開、Word RAM 1M交換、VRAM DMAキュー、スプライト／マップ描画を
個別に追加できます。BIOS・Subサービス・Main APIの境界を維持して進めます。

基盤資料: [Megadev CDアクセス](https://github.com/drojaazu/megadev/blob/v1.2.0/docs/cdrom.md)、
[ディスク構成](https://github.com/drojaazu/megadev/blob/v1.2.0/docs/disc.md)、
[PCMレジスタ](https://github.com/drojaazu/megadev/blob/v1.2.0/lib/sub/pcm.def.h)。
