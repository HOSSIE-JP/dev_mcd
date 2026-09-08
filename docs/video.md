# メガCD動画ライブラリとノベル連携

以前の「メガCD動画再生方式検討」で作成した MTV1 形式・Cパーサ・VDP転送プランを統合した。
通常のメガドライブ＋メガCDが対象。32Xは使用しない。形式は
[video-format.md](video-format.md) の既存仕様に従い、以前の medium12 / full6 等のMTVファイルを
再変換せず読める。復旧した6設定の既存MTVは新しいホスト検査でも全フレームを通過している。

## 対応範囲

- `video_format.h` / `src/common/video_format.c`: CRC、構造・境界、PTS、辞書番号、PCMマーカー、EOF、バックプレッシャーを検査する既存ポータブルコア。ホスト検査ではペイロードCRCを有効にする。ネイティブはヘッダCRCと構造検査を行い、毎フレームのペイロードCRCはCPU負荷を避けて無効としている。
- `video_upload.h` / `src/common/video_upload.c`: 非表示側のタイル辞書→配置表→パレットの転送計画。
- `video.h` / `src/main/video.c`: NOVEL.PAK内の動画を読むネイティブ再生アダプタ。
- `video_stream.h` / `src/sub/video_stream.c`: RF5C164用PCMリング。既存IMA再生状態と排他。
- `tools/video_convert.py`: ffmpeg/ffprobeで映像・音声を読み、既存MTV1へ変換する。NumPy/Pillowが必要。

動画変換と`tools/build_editor_novel.py`は`--ffprobe <実行ファイル>`を受け付ける。
省略時は指定ffmpegと同じディレクトリ、PATHの順に検索する。エディターの
`megaCd.ffprobePath`はこの指定へ引き継ぐ。カバー画像（attached_pic）は除外し、
選択した通常動画のstream indexをffmpegへ指定する。90度回転は表示寸法へ反映して
からletterbox寸法を計算し、ffmpegのautorotation後の画面比率と一致させる。
動画の長さはエディター取込・変換・MTV1検証のすべてで最長2時間とする。

ネイティブアダプタは **Sub PRG RAMの192 KiB×2先読み** と、**2M Word RAMの62 KiB×2窓** を使う。
SubはMainのVDP転送中にも次のPRGバンクへCDデータを読み進める。Mainは一方のWord窓にある
映像を消費したら、その窓へ先のレコードをコピーし、もう一方に残した映像・音声で時間を確保する。
窓の境界をまたぐレコードは、その先頭を含むセクタから次の窓へコピーする。
PCMは窓内の複数レコードをまとめて供給する。リング容量を超える分はWord窓へ残し、再生で空きができてから供給する。

ノベルの立ち絵64 KiBは動画開始前にSub PRGへ退避し、終了時に元のWord位置へ復元する。
スクリプトとフォントのある下位128 KiBは常駐したままなので、1M Word RAMモードへの変更は行わない。
Word RAMをSubへ渡したCDコピー・PCM補充・退避復元中、MainはWord RAMを参照しない。
VBlank/INT2とSubのPCM更新は継続する。

この先読み構成でも、素材の転送量や実装・機器の速度を無条件に保証するものではない。
指定FPSは目標値であり、下記の測定結果と区別する。

## プロファイル

| 設定 | 表示枠 | 目標FPS | 辞書上限 | 位置付け |
|---|---:|---:|---:|---|
| small15 | 160×112 | 15 | 96 | 動き優先 |
| medium12 | 224×160 | 12 | 128 | 初期標準候補 |
| balanced10 | 256×176 | 10 | 192 | 帯域確認後の候補 |
| full6 | 320×224 | 6 | 256 | 全画面の初期候補 |
| full75 | 320×224 | 7.5 | 256 | 実験 |
| full10 | 320×224 | 10 | 256 | 実験 |
| fullhq6 | 320×224 | 6 | 384 | 画質優先・実験 |

全設定は現アダプタで機能を検証する対象であり、性能保証済みという意味ではない。
元動画の尺を保持し、H40の公称ピクセル比14:15を考慮して元の縦横比を黒帯で保つ。
RGB333の15色＋黒をフレームごとに選び、タイル辞書を上限内へ近似する。
この近似は元の研究用エンコーダと同じファイル形式を生成するが、辞書選択アルゴリズムや画質が同一とは限らない。
フレームのレコードは2バイト境界で詰め、最終ファイルだけを2048バイト境界に揃える。

```sh
python tools/video_convert.py --source input.mp4 --output movie.mtv --profile medium12
python tools/video_convert.py --source input.mp4 --output movie-full.mtv --profile full6
python tools/video_convert.py --demo --output movie-demo.mtv --profile medium12
```

ffmpegと同じディレクトリのffprobeを優先し、存在しなければPATHを使用する。
動画の音声は16kHz・モノラル・RF5C164用PCM8へ変換する。無音素材にも同じ時間長の無音PCMを入れる。
出力は一時ファイルを完成させてから置換する。変換失敗時に既存出力を途中状態で上書きしない。

## ネイティブAPIと資源

```c
MCDVideoStatus status;
u16 result = MCD_playVideo(pack_offset, resource_bytes, true, &status);
/* 診断用の無音経路 */
result = MCD_playVideoEx(pack_offset, resource_bytes, true, false, &status);
```

呼出し側から見るとブロッキングだが、内部では `SYS_doVBlankProcess` を呼び続ける。
B/C/Startの新しい押下でスキップする。再生開始時から押されたままの入力はスキップとして扱わない。
スキップ時も進行中のCD/PCM要求を完了させ、Word RAM所有権を回収してから戻る。
タイムアウトはブリッジのラッチを維持し、所有者不明のバッファを再利用しない。

- Word RAM: 映像データ窓 `0x20800..0x2ffff` / `0x30800..0x3ffff`。PCM記述子は`0x30000`の予約セクタ。
- Word RAM `0x20000..0x2ffff` の立ち絵データは、Sub PRG `0x70000..0x7dfff`（56 KiB）と`0xe000..0xffff`（8 KiB）へ退避する。
- Sub PRG: CD先読みバンク `0x10000..0x3ffff` / `0x40000..0x6ffff`。退避中は従来IMA処理と排他し、復元まで予約を保持する。
- VRAM: タイルバンク `0x0020 / 0x4020`、Plane B配置表 `0xa000 / 0xe000`、パレット0/1。
- Plane A / SAT / scrollは開始時に初期化。呼出し側が自分の画面を再構築する。
- 非表示側へ1 VBlankあたり最大2 KiBのCPU転送を行い、PTSに達したVBlankでPlane Bを切り替える。
- `VDP_drawImage`による毎フレームの画面消灯は行わない。転送の時間予算は今後測定する。

## 音声時計と再バッファ

動画開始時にCD-DAと既存PCM再生を停止する。PCMリングは動画が占有する。
キャッシュ内で完結したレコードの音声を先に補充し、音声の実再生サンプル数を映像PTSの時計とする。時計要求は非表示側VRAMの転送と重ね、その後の短い待ちはSubの60Hz tickで補間する。
映像準備が間に合わず、そのフレームの表示期間が過ぎていれば古い映像を落とす。

キャッシュ読込中に音声が尽きると、Subはリング末尾のガード領域を無音化して再生を停止する。
返す再生位置は最後に供給したサンプル数へ固定される。Mainはその一致を確認し、STOP→BEGIN→FEED→PLAYで
未再生部分から再開する。古いリング内容を繰り返して時間を埋めない。これにより無音の待ち時間が生じる場合がある。
この実装は再バッファが起きない連続再生を保証するものではない。
診断用の無音経路は60Hzの時計を使用し、キャッシュ再読込時間を明示的に再生時間から除く。

`MCDVideoStatus` は表示数、期限切れで落とした数、キャッシュ読込回数、音声再バッファ回数、
音声再生サンプル数、スキップ有無を返す。ホスト検査とエミュレータ／実機の性能証拠は区別して記録する。

## ノベル

MNVNの追加コマンドはopcode 16、資源種別7。targetに動画資源ID、flags bit0にskipEnabledを格納する。
既存0～15のコマンド番号は変更しない。

再生中はシーン・PC・変数・オート送り・入力監視・立ち絵移動・口パク・文字点滅の進行を止める。
EOF／スキップ後は背景を読み直し、常駐立ち絵・パレット・必要な文字タイルを再構築する。
音声は直前に再生していたPCM BGM／CD-DAを先頭から再開する。曲の途中位置への復元ではない。
台詞／効果音は再開しない。終了時に保持中の入力を記録し、スキップ操作で次の台詞が進むことを防ぐ。
形式・I/Oエラー時は可能なら画面を戻してHALTへ移り、タイムアウト時はWord RAMへ触れずHALTする。

立ち絵は4スロット。各16 KiBのピクセルキャッシュを`0x20000..0x2ffff`へ配置し、
アニメーション情報・パレット番号等はMain側Actor構造体に保持する。VRAMタイル512～1023、
日本語文字タイル1024以降という既存配置に収める。
EOF後の復帰とスキップ後の復帰は、背景・4人の立ち絵・文字・BGMを含むシーンで検証する。
EOF音声の終端、再バッファ、長尺のリング周回についてはSubのホストテストも参照する。

## エミュレータで確認した結果

Genesis Plus GX固定版 `a7985a9c4278ac352f8ca7bb4d3cc6b36e9e3e7d` とユーザー提供BIOSで、実際の
メガCDディスクを起動して確認した。画像はホスト復元画像ではなく、エミュレータの実VDP出力である。
実機検証と、映像PTSに対する実画面出力遅延の測定は未実施。

以下はSub PRG先読み・2窓Word・PCM一括補充を入れた最終構成での結果。
再バッファ0をテストの必須条件にして実行した。

| 素材 | 元尺 | 要求からEOF※ | 最初の発音まで | 表示 / ドロップ | 再バッファ | 音声終端 |
|---|---:|---:|---:|---:|---:|---:|
| 手続き生成 medium12 / 音声 | 3.000秒 | 5.667秒 | 2.554秒 | 34 / 2 | 0 | 48,000サンプル一致 |
| 手続き生成 medium12 / 無音 | 3.000秒 | 5.217秒 | — | 36 / 0 | 0 | 無音 |
| 既存研究素材 medium12 | 15.083秒 | 17.817秒 | 2.640秒 | 106 / 75 | 0 | 241,333サンプル一致 |
| 既存研究素材 full6 | 15.083秒 | 18.033秒 | 2.690秒 | 48 / 43 | 0 | 241,333サンプル一致 |

※ 要求からEOFはNTSCのエミュレートフレーム数を60で割った概数。起動時のプリフィルと終了時の
立ち絵キャッシュ復元を含み、BIOS起動は含まない。発音時刻はエミュレータの実申告FPSを使う。
キャッシュ読込回数は手続き生成3回、medium12は21回、full6は23回。

既存研究素材2本は、どちらも896エミュレートフレームにわたり毎フレーム非ゼロ音声が出力され、
最初から最後の非ゼロ出力まで約14.945秒だった。音声先頭・末尾の無音を含む元尺とは区別する。
意図的な無音区間を欠落と判定しないため、無音の有無だけで任意の素材の連続性を保証しない。

**今回の試験では音声の再バッファを解消したが、映像の目標FPSは未達の素材がある。**
表示数を元尺で割った平均は、手続き生成で約11.33枚/秒、既存medium12で約7.03枚/秒、
既存full6で約3.18枚/秒。medium12 / full6という名前は変換時の12 / 6 fpsを表し、
実機でその全フレームを表示できるとの保証ではない。表示が遅れた分は音声時計を基準に落とす。
累積A/Vずれ40ms以内も未検証である。

手続き生成素材のスキップは、**実際に発音した後**45フレーム待ってStartを8フレーム保持し、
9フレーム表示・11,128サンプル時点で認識して復帰した。開始待ち中だけのスキップ試験ではない。
エディターから生成した別のノベルディスクでも、背景・4人の立ち絵・SpriteTextを含む画面で
EOF／スキップ後の全RGBバイトが再生前と一致した。Bを120フレーム保持しても次の台詞は進まない。

最終証跡: [手続き生成](evidence/video/prefetch-procedural-report.json)、
[medium12](evidence/video/prefetch-medium12-report.json)、[full6](evidence/video/prefetch-full6-report.json)。
画像: [medium12](evidence/video/prefetch-medium12-emulator.png)、[full6](evidence/video/prefetch-full6-emulator.png)。
JSONにはディスク・入力素材・ネイティブソースのSHA-256、終端カウンタ、音声出力時刻を記録した。

比較用として、改善前の単一64 KiB・直接CD読込版の測定も残す。
この旧構成ではmedium12が48.800秒／再バッファ20回、full6が49.950秒／22回だった。
これは現在の構成の測定値ではない。
旧証跡: [手続き生成](evidence/video/procedural-report.json)、[medium12](evidence/video/medium12-report.json)、
[full6](evidence/video/full6-report.json)。

```sh
make video-data video
python tools/video_smoke.py --bios /path/to/user-bios.bin --frames 3000 \
  --require-no-rebuffer --skip-after-audio --skip-after 45
# 既存MTVによる試験
python examples/video_demo/prepare.py --source /path/to/medium12.mtv
make video
python tools/video_smoke.py --bios /path/to/user-bios.bin --case audio_eof \
  --frames 4500 --require-no-rebuffer
```

実行時に発見したM68000固有問題として、GCC 13の隣接する `_Bool` 代入の結合が奇数アドレスへの `CLR.W` となり、
キャッシュ境界でアドレスエラーを起こすケースがあった。再生制御フラグを16bitへ変更し、ビルド側でも
`-fno-store-merging` を指定して修正した。またWord RAMを移譲しない時計要求で読込済みポインタの有効性が
消えていたブリッジも修正した。その後に上記EOF／スキップ検証を完了している。

## VBlank内の表示切替改善（2026-09-08）

`src/main/video.c` の表示切替は、非表示側のタイル・配置表・パレット転送とPTS待ちが
すべて完了した時点で、現在のVBlankを再利用できるようにした。H40 / NTSC / 224行専用で、
VDPのVBlank statusと垂直カウンターを確認し、次の有効表示まで16走査線以上の余裕がある
区間だけでPlane Bを切り替える。遅いVBlank・有効表示中は従来どおり次のVBlankを待つ。
1回のVDP転送上限2KiB、Word RAM所有権、音声時計、PCM補充・再バッファ処理は変えていない。
NTSCの262走査線と途中で繰り返す垂直カウンター範囲をホストテストで検査する。

固定版Genesis Plus GXをWindows/UCRT64で構築し、同じMTV1ファイルのまま変更前後を
比較した。今回の音声付き結果は以下。表示枚数/元尺の値は平均で、各フレームのPTS遅延とは異なる。

| 独自検査素材 | 元尺 / 入力枚数 | 表示枚数（前→後） | 平均表示枚数/秒（前→後） | 再バッファ（前/後） |
|---|---:|---:|---:|---:|
| 既存の手続き生成 medium12 | 3秒 / 36 | 33 → 33 | 11.00 → 11.00 | 0 / 0 |
| 辞書128タイルを使う移動ノイズ medium12 | 6秒 / 72 | 35 → 42 | 5.83 → 7.00 | 0 / 0 |

負荷の高い独自検査素材では表示枚数が20%増えた。音声終端はどちらも入力と一致し、
無音EOFと、実際の発音開始後にStartを押すスキップも正常に完了した。通常デモの
起動・ADPCM・CD-DA・一時停止/再開・操作も `tools/smoke.py` で再確認した。
`make all`、`make host-test`（74テスト、Windowsのシンボリックリンク権限による3サブケースのみ省略）、
`tools/doctor.py` が成功した。FFmpeg実変換のテストも実行している。

画面取得はエミュレーターの実VDP出力。実機・聴取・各フレームのA/V遅延は未検証であり、
目標12fpsを持続達成したという意味ではない。比較ディスク・素材・ネイティブソース・coreの
SHA-256と生のテレメトリは[今回の検証JSON](evidence/video/vblank-publish-report.json)に記録した。

## SDK v2: color quantization and ordered dithering

`options.dither` selects `none` (legacy default) or `ordered`; `ditherStrength`
ranges from 0 to 1 with default 0.5. A fixed 4x4 Bayer pattern trades spatial
noise for smoother gradients without changing the MTV1 format or playback cost.
Pixels are reassigned to the actual RGB333 palette after rounding. Strong
settings can worsen tile approximation; compare the decoded MTV1 preview.
The experimental medium15 (224x160, 15fps, 128 tiles) and mediumhq12
(224x160, 12fps, 192 tiles) profiles trade motion and detail. Rates are targets,
not guarantees. tools/video-capabilities.json advertises these additions to
editors so an older SDK cannot silently ignore a requested dither recipe.
