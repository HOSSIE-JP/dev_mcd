# SGDK機能との差分とメガCD向けライブラリの範囲

調査基準: dev_mcd `4ad481abace1b5ad3b9d134397c1036c55c20859`、
MD Game Editor `26f0cda3d9869acd3c44961d89e42e102af6381d` の
`plugins/md-novel-builder/template/`。この文書の「追加」は、同文書と
同時に入るブリッジ拡張を指します。

現状には不足があります。ブリッジはSGDK風の一部関数とCD/PCMサービスを
提供しますが、SGDKのヘッダー・ResComp出力・ROM用ランタイムをそのまま
リンクできる互換ライブラリではありません。同一ノベルプロジェクトから
MD版とメガCD版を生成するには、プロジェクト／命令モデルを共有し、
素材変換・配置・ビルド・実行エンジンをターゲット別に選ぶ構成が必要です。

## ノベルプラグインから見た対応表

| SGDK側で使用する機能 | ブリッジ／メガCD側の対応 | 制約と追加方針 |
|---|---|---|
| `SYS_doVBlankProcess`, `JOY_readJoypad` | 既存。フレーム数、協調待機、押下／解放エッジを追加 | 1Pの3ボタン。2P、6ボタン、マルチタップ、SGDKコールバックは未対応 |
| `VDP_setScreenWidth320`, `VDP_setScreenHeight224`, `VDP_setPlaneSize` | 320×224、64×32セルの固定プロファイル | 可変解像度／可変プレーン寸法APIは未対応。初期化で共有レイアウトを設定 |
| `PAL_setPalette`, `PAL_setColors` | 即時CPU転送。単色・範囲・読取キャッシュを追加 | SGDKの転送方法引数は受けない。DMAキューではない |
| `PAL_fadeInAll`, `PAL_fadeOutAll`, `PAL_fadeToAll`, `PAL_isDoingFade` | `MCD_fadePaletteTo` と `PAL_isDoingFade` を追加 | 指定範囲を1本だけ非同期フェード。VBlank処理で進行。SGDKのfade関数群そのものは未対応 |
| `VDP_loadTileData`, `VDP_setTileMapXY`, タイル属性 | `MCD_loadTiles`、`VDP_setTileMapXY`、矩形転送／塗り潰し、`TILE_ATTR*` を追加 | CPU転送のみ。予約領域と矩形境界を検査。ResComp圧縮の展開は未対応 |
| `VDP_clearPlane`, `VDP_drawImageEx` | `MCD_clearPlane`、既存の独自MIMG画像描画 | WINDOW、SGDK `Image`、`TileSet`、`TileMap` は未対応 |
| テキスト表示 | 既存ASCII描画へ描画面・色・優先度・部分消去を追加 | ブリッジ標準フォントは8×8診断用。日本語文字表示はノベルライブラリが担当 |
| `VDP_setHorizontalScroll` | 全画面水平／垂直スクロールを追加 | ライン／セル単位スクロールは未対応 |
| `SPR_*` の立ち絵・文字スプライト | ノベル専用描画は既存 `libmcd_novel.a` に実装 | SGDKの汎用スプライトエンジン、動的VRAM確保、定義／アニメーション構造体との互換APIは未対応 |
| H/V割り込みコールバック、ハイライト／シャドウ | ノベル専用UIで描画を代替 | SGDKのHInt/VIntコールバックは未対応。VBlank→Sub INT2を置換しない設計が必要 |
| `MEM_alloc`, `MEM_free` | ノベル専用領域の固定割当で実装 | 汎用ヒープ／VRAMアロケーターは未対応。Main RAM容量を前提に別途設計 |
| `Z80_loadDriver`、XGM系再生 | CD-DA、Sub CPUのIMA復号＋RF5C164 PCMに置換 | XGM2やSGDK Z80ドライバをそのまま再生する互換性はない |
| 背景・立ち絵・音声のROM参照 | CDパックの範囲読み込みと各キャッシュ | Word RAMの所有権・セクター丸め・音声メモリー容量を検査 |
| 動画 | 同一作業の動画ライブラリ／ノベル命令で別途統合 | SGDKの標準互換性とは独立。変換済みデータをCDから読み、音声と帯域を共有 |

ノベル用に最初から汎用 `SPR_*` やSGDKの全DMA機構を再実装する必要はありません。
既存のノベル専用描画・PCMサービスをターゲット別ランタイムとして使い、
追加した基礎APIを他サンプルにも利用できる公開ライブラリにします。
任意のMDプロジェクトで完全同一の表示・演出が得られるという保証ではなく、
変換時にメガCDプロファイルから外れる寸法・素材・命令を明示的に検査します。

## 今回追加する公開API

| 用途 | API |
|---|---|
| フレーム／入力 | `MCD_getFrameCount`, `MCD_waitFrames`, `MCD_readJoypadPressed`, `MCD_readJoypadReleased` |
| パレット | `PAL_setColors`, `PAL_setColor`, `PAL_getColor`, `MCD_fadePaletteTo`, `PAL_isDoingFade`, `MCD_cancelPaletteFade` |
| 文字 | `VDP_setTextPlane`, `VDP_setTextPalette`, `VDP_setTextPriority`, `VDP_drawTextBG`, `VDP_clearText` |
| タイル／マップ | `MCD_loadTiles`, `VDP_setTileMapXY`, `VDP_fillTileMapRect`, `MCD_setTileMapRect`, `MCD_clearPlane` |
| スクロール | `VDP_setHorizontalScroll`, `VDP_setVerticalScroll` |

既存の `PAL_setPalette(bank, colors)` は2引数のままです。
例えばSGDKコードの `PAL_setColors(0, colors, 64, DMA_QUEUE_COPY)` は
`PAL_setColors(0, colors, 64)` へ移植します。この変更は即時転送になるため、
転送を行うフレーム位置とCPU時間も確認してください。
`VDP_loadTileData` と同名の未実装DMA受け口は用意せず、
`MCD_loadTiles` でCPU転送と戻り値を明示します。

```c
MCD_init();
PAL_setPalette(PAL1, colors);
if (MCD_loadTiles(tilePixels, 1, 2) != MCD_OK) return;
VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL1, false, false, false, 1), 0, 0, 40, 28);
MCD_fadePaletteTo(16, black, 16, 45);
while (PAL_isDoingFade()) SYS_doVBlankProcess();
```

## メモリー・割り込みの契約

- 基礎APIのVRAM割当はタイル0が透明、タイル1–1151が利用者用、
  1152–1247が診断フォント、Plane A=`C000`、Plane B=`E000`、HScroll=`FC00`。
  ノベルの日本語・立ち絵描画は専用VRAM割当なので、その実行中に任意の
  基礎APIタイル転送を混在させないでください。
- `MCD_loadTiles` の送信元はワード境界にあり、`count × 32` バイト以上必要です。
  配列の生存期間は呼び出し終了までで足ります。タイル0・フォント・テーブルに
  越境する指定はエラーになります。大量転送が1回のVBlankに収まる保証はありません。
- タイルマップ矩形は64×32を越えると全体を拒否します。
  `MCD_setTileMapRect` は `sourceCells` と `stride` から送信元終端も検査します。
  テキストだけは40×28の表示領域で右端をクリップします。
- タイル転送は1タイル、マップ転送は1行単位だけ割り込みをマスクします。
  待機は `SYS_doVBlankProcess` を通し、CD要求とSub INT2の進行を維持します。
  SGDKの `SYS_disableInts()` を長いCD処理の前後へそのまま移植しないでください。
- パレットフェードは呼び出し時点のキャッシュから開始し、送信先色をコピーします。
  次の `PAL_set*` で停止します。`PAL_getColor` はキャッシュの値です。
  CRAMへ直接書いた値はキャッシュに反映されません。外部レンダラーから引き継ぐ
  場合は最初に `PAL_setColors` で既知の状態へ揃えてください。
- `MCD_init` は最初のネイティブCD起動後に1回呼びます。
  タイムアウトしたCD要求のリセット／バッファ回収の代用にはなりません。
- 通常GCC ABI、M68000命令のみ。`-mshort`、ホストlibc、BIOS同梱は使用しません。

## ノベル以外へ広げるときの残項目

| 優先度 | 不足する機能 | 実装を分ける理由／受け入れ条件 |
|---|---|---|
| 次段階 | 汎用スプライト、VRAM確保、SAT更新 | ノベル専用機構から共通部分を抽出。各走査線のハードウェア制限、確保失敗、アニメーション転送量を検査するサンプルが必要 |
| 次段階 | VBlank転送キュー／DMA | コピー所有権・Work RAM予算・Word RAM返却順を設計。CD読み込み中と音声同時再生中に検証 |
| 次段階 | MD音源を保持するPSG/FM再生 | XGM2/Z80とBIOS処理の併存、サンプル音声所在、バス競合の検証。PCMへの事前変換は完全音色互換ではない |
| 用途次第 | バックアップRAM、外部バックアップ、セーブ形式 | SGDKのカートリッジSRAMとは別媒体。BIOSサービス、残量、破損／電源断耐性を含めて設計 |
| 用途次第 | 2P/6ボタン、マウス、マルチタップ | BIOS入力と共存させる周辺機器ごとの検証 |
| 用途次第 | MAP/BMP、圧縮リソース、数学・衝突・タイマーAPI | 利用ゲームの要求が決まってから移植。SGDK全体のAPI面を実装済みとは表記しない |
| 用途次第 | PAL/他リージョン、H32、240ライン、HInt効果 | 起動、BIOS、フレーム時間、CD帯域、VRAMレイアウトを別プロファイルとして検証 |

## 検証とサンプル

`make bridge` が追加APIの操作サンプルを生成します。
[操作と受け入れ項目](../examples/bridge_demo/README.md)を参照してください。
`make host-test` には `tests/test_bridge.py` が加わり、実装本体を
ホストのVDPポートモデルへ接続して、予約タイルへの越境、矩形の端・送信元不足、
パレット範囲、フェードの終了／中断、入力エッジ、フレーム処理中のIPC完了を検査します。
これはM68000実行・実機のVDPタイミング・光学ドライブの証拠ではありません。
ターゲットビルド、既存サンプル回帰、BIOSを用いた実行証拠は別途記録します。

比較資料: [SGDKのタイルAPI宣言](https://github.com/Stephane-D/SGDK/blob/master/inc/vdp_tile.h)、
[MD Game Editorのノベルランタイム](https://github.com/HOSSIE-JP/md-game-editor/blob/26f0cda3d9869acd3c44961d89e42e102af6381d/plugins/md-novel-builder/template/src/novel_runtime/novel_runtime.c)、
[既存ノベル描画・音声の制約](novel.md)。
