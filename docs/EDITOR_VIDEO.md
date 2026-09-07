# MD Game Editorの動画編集・Setup連携

`tools/setup.ps1`はエディターの管理フォルダーへSDKソースを取得した後にも使用する。portable MSYS2、UCRT64 Python/NumPy/Pillow、FFmpeg/ffprobe、m68k-elf GCCを`.deps`へ構築する。GNU configureのため英数字・空白なしの配置先が必要。BIOSは取得・コピーしない。

Linuxの`tools/setup-editor.sh`はホストのbuild prerequisitesを検査し、Python venvとcross compilerを`.deps`へ構築する。sudoやシステムPythonへのpip installは行わない。macOSはこのSetupの検証対象外。

## 加工設定

MDエディターの`assets/md-novel/video-assets.json`にある各entryの`options`を、`editor_project.py`が変換catalogの`options.processing`へ渡し、`novel_convert.py`から`video_convert.convert_video(..., options=...)`へ渡す。設定なしの従来projectは原本全範囲・pad・無加工で互換動作する。

- `trimStart` / `trimEnd`: 秒。`0 <= start < end <= 原本時間`。
- `crop`: autorotate後の原本座標。整数`x/y/width/height`。原本外・空範囲は拒否。
- `fit`: `pad`（全体を収める）または`crop`（viewportを埋める）。H40 pixel aspectは従来通り14:15で補正。
- `brightness`: -1..1、`contrast`: 0..2、`gamma`: 0.1..3、`saturation`: 0..3。
- `volume`: 0..2、`mute`: boolean。

映像と音声を同じtrimで切り、MTV1のフレーム数・PCMサンプル数・PTSを切取後の時間で作る。muteは無音PCMを出力する。加工結果は従来のRGB333/15色とtile codebookの変換を通し、runtime/ABIは変えない。

```sh
python3 tools/video_convert.py --source input.mp4 --output output.mtv --profile medium12 --options recipe.json
python3 tools/video_preview.py --source input.mp4 --output proof.webm --profile medium12 --options recipe.json
```

`video_preview.py`は実際にMTV1を生成・検証してからtile/palette/PCMを復号し、lossless VP9とOpusのbrowser確認用WebMへ出す。音声はブラウザー用の再圧縮を通す。ネイティブの処理落ち/CD待ち/実機出力を模擬するものではない。エディターはproofを先頭10秒へ制限し、process groupをキャンセルできる。full movieは本ビルド時に変換する。
