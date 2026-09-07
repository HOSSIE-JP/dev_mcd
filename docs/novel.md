# メガCD版ノベルエンジンと第1話サンプル

MD Game Editorのノベルプラグインが生成する `NovelScene` / `NovelCommand`
モデルを参考に、メガCDのネイティブCD起動用エンジンを実装した。
エディター本体と元のPCEプロジェクトは変更していない。
SGDKのROM用実行ファイルをそのまま起動する方式ではない。

## チェックアウト後の実行

既存の [環境構築手順](setup.md) でポータブルMSYS2またはLinuxネイティブ環境を構築する。
Docker、WSL、追加のPythonパッケージは通常のビルドには不要。

Windowsでは `mcd.cmd novel`、Linuxでは `make novel` を実行する。
出力は `dist/ishinoura_ep01/`。`ishinoura_ep01.cue` を日本版メガCDに対応した
エミュレーターで開く。ISOと3個のWAVは同じフォルダーに置く。
BIOSは各利用者が自分のものを別途設定する。リポジトリやCIには含めない。

| 操作 | 動作 |
|---|---|
| B / C / START | タイトル開始、文字の即時表示、次のページ、選択決定 |
| 上 / 下 | 選択肢の変更 |
| A | 自動送りの切り替え |

自動送りは台詞の再生終了を待つ。ボタンで先へ進めた場合は台詞を停止する。
ロゴ表示とタイトル待機のスキップも元シナリオの入力監視命令に従う。

## 取り込んだデータ

対象は「いしのうらにいる！？ / 01_部室の白い箱」。18シーン、275会話、
2か所の選択肢、275個の音声を取り込み、501個の実行命令へ変換した。
コメント・ラベルは変換時に解決し、`skip: true` は実行対象から外す。
選択による台詞と合流先、エンディングからロゴへの復帰を保持する。

`examples/ishinoura_ep01/data/` の内容:

- `scenario.json`: 元のシナリオ。日本語台詞と安定したシーンIDを保持する。
- `novel.pak`: 実行命令、フォント、背景、立ち絵、IMA音声をまとめたCDデータ。
- `cdda/*.pcmz`: 元のCD-DA PCMを可逆圧縮したもの。ビルド時にWAVへ戻す。
- `manifest.json`: 素材対応表、オフセット・容量・SHA-256、CDトラック割り当て。

CD-DAは第2トラックが `cdda_eye_catch_all`、第3が `cdda_eyecatch`、
第4が `cdda_title`。元PCEのトラック番号は変換時に解決する。
各音声トラックには2秒のプリギャップを設け、短い曲は4秒まで末尾を無音で埋める。

## 命令と表示

| 元プラグインの機能 | メガCD版 |
|---|---|
| background / fade | CDから読み込んだ16色背景、フェード |
| sprite / spritemove | 立ち絵3スロット、反転、表情、瞬き、口パク、同期・非同期移動 |
| message | 話者名、文字色、16ドット日本語、19字×4行、改ページ、自動送り |
| choice / jump | 選択結果の変数、シーン分岐と合流 |
| label / goto / inputcheck | ラベル解決、入力待ち・非同期入力監視 |
| variable / if / switch | 符号付き16ビット変数32個、比較、条件分岐 |
| wait / shake | フレーム待機、画面の揺れ |
| audio / voiceAssetId | CD-DAと、BGM・台詞/SFX用の独立したPCMチャンネル |
| cache | 変換時にヒントとして受け取り、実行命令はNOP |

今回の描画プロファイルはPCEの256ピクセル座標を320×224画面の中央へ配置する。
通常の背景は224×136、全画面画像は256×224。
立ち絵は64×128、1行2コマまでの2行構成。
部長・チカは共有15色、レンは別の15色へ量子化し、UI用のパレットを確保する。
元PCEの12ドットフォントから、MDプラグインにも含まれる東雲16ドットへ変更する。
このプロファイルを超える素材や未知の命令は変換時にエラーにする。
任意のMD Game Editorプロジェクトとの完全互換を保証するものではない。
SRAM保存・バックログ・動画は実装していない。

## 音声とメモリー

光学ドライブはデータの読み込みとCD-DA再生を同時に行えない。
そのため元のPSG曲は6チャンネルのイベントを合成し、8 kHz・モノラルの
IMA ADPCMとしてPRG RAMへ読み込む。波形IDは近似波形へ置き換えており、
PCE音源やMD版のFM変換と同一の音色ではない。
台詞は11.025 kHz、短い効果音は16 kHz・モノラルのIMAへ変換し、長さを切り詰めない。
長い音声を2本同時に復号する場合は合計19025サンプル/秒を上限として、超過する再生要求を拒否する。
元のCD-DA曲はステレオPCMを保持する。

Sub CPUは圧縮音声をメモリーから復号し、RF5C164の2個の32 KiBリングへ補充する。
ループマーカーを除いた各リングの有効長は32767サンプル。
BGMはPRG RAM `0x40000..0x7DFFF`、台詞は `0x20000..0x3FFFF` に分離する。
この範囲を超える音声は変換時・実行時の両方で拒否する。
次の台詞をCDから読む間もBGMの圧縮データと再生状態を保持する。
CD-DA再生中にデータを読むとCD-DAは停止する。任意の音声付き会話に
CD-DAを途切れず重ねる機能は、この版にはない。

Main CPUのWord RAMは次のように使う。

| オフセット | 用途 |
|---|---|
| `0x00000..0x17FFF` | シナリオと素材インデックス、最大96 KiB |
| `0x18000..0x1FFFF` | 日本語フォント、最大32 KiB |
| `0x20000..0x2C2FF` | 立ち絵3個のアニメーションキャッシュ |
| `0x30000..0x3FFFF` | CD転送用の64 KiB作業領域 |

`MCD_readRangeAsync()` は `NOVEL.PAK` 内のセクター境界から必要な範囲だけ読む。
丸めた長さ、パックの終端、転送先の容量をSub側でも検査する。
Word RAMの所有権がSubにある間はMainからキャッシュを読まない。
待機中もVBlankとINT2を維持する。ハングした転送のバッファは再利用しない。

## 元データから再変換する

通常のビルドには不要。素材を更新する場合だけ、Python 3.12以上の環境で
`python -m pip install -r tools/requirements-novel.txt` を実行する。
元のPCEプロジェクトとMD Game Editorのフォントを手元に置き、次を実行する。

```sh
python tools/novel_convert.py --source /path/to/01_project \
  --font /path/to/JF-Dot-Shinonome16.ttf \
  --output examples/ishinoura_ep01/data
make novel
make host-test
```

参照元を固定したコミット:

- MD Game Editor: `26f0cda3d9869acd3c44961d89e42e102af6381d`
  (`plugins/shared/md-vn/compiler.js`, `scene-schema.js`,
  `plugins/md-novel-builder/template/src/novel_runtime/novel_runtime.c`,
  `plugins/md-novel-editor/pce-import.js`, `novel-convert.js`)
- PCEプロジェクト: `6e0ff601e7ac2af69ce39677b623781ff01f1e0c`

実行検証は `python tools/novel_smoke.py --bios /path/to/your_bios.bin --route 0,0 --listen`。
保存するのはゲーム画面・出力音声・ゲーム自身の40バイトのテレメトリーに基づく
結果だけで、セーブステートやBIOSを含むメモリーダンプは作らない。
実機での検証とは区別する。

実行画面と全ルートの結果は [第1話の検証記録](novel-validation.md) を参照。
