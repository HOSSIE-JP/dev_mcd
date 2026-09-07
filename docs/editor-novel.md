# MD Game Editorの同一ノベルをMega Drive / Mega CDへ出力

対応版[MD Game Editor](https://github.com/HOSSIE-JP/md-game-editor)のNovel → Systemで
「ビルド媒体」をMega Drive ROMまたはMega CDへ切り替えます。
正本は両方とも`assets/pce-vn-scenes.json`と`assets/pce-assets.json`です。
`project.json.targetMedia`だけを`rom` / `cd`へ変更し、省略時は従来の`rom`として扱います。
coreは`mega-drive`、builderは`md-novel-builder`を維持します。

## 台本の互換性

エディター用adapterは、立ち絵のパレット「Auto」をbindingの`legacyPalette`／`palette`から解決し、
選択肢の省略値にはMDと同じ0始まりの番号を設定します。通常変数の最初の`define`値は実行開始前に初期化し、
台本中の各`define`もMDと同じ代入として実行します。必要な初期化は専用の内部シーンで1回だけ行い、
元の開始シーンへの再ジャンプでは繰り返しません。元の正本JSONは変更しません。

`AUTO_ENABLE`・`MSG_SPEED`を直接扱う変数命令・条件分岐・選択肢は、現在のCD runtimeではMDの制御効果を
再現できないため、変換時に明示的なエラーとします。システム設定の`messageAdvanceMode`と
`messageSpeedFrames`は使用できます。`skip`／`skipped`／`debugSkip`で除外された命令はこの制限の対象外です。
この正規化はエディターからの変換経路に限定し、既存の単独ノベルconverterの動作は変更しません。

## 環境設定

まず本リポジトリの[セットアップ](../README.md)を完了してください。
「Mega CDビルド環境」で`dev_mcdフォルダー`にこのチェックアウトの絶対パスを指定します。
Windowsのポータブル構成なら、例えば次の設定になります。
既存の`project.json`全体を置き換えず、エディターから設定してください。

```json
{
  "targetMedia": "cd",
  "megaCd": {
    "devMcdPath": "D:\\homebrew\\dev_mcd",
    "msys2BashPath": "D:\\homebrew\\dev_mcd\\.deps\\msys64\\usr\\bin\\bash.exe",
    "pythonPath": "D:\\homebrew\\dev_mcd\\.deps\\msys64\\ucrt64\\bin\\python.exe",
    "ffmpegPath": "D:\\tools\\ffmpeg\\bin\\ffmpeg.exe",
    "ffprobePath": "D:\\tools\\ffmpeg\\bin\\ffprobe.exe"
  }
}
```

PythonにはNumPy/Pillowが必要です。WindowsセットアップはUCRT64版を導入します。
Linuxでは`msys2BashPath`を空にし、`pythonPath`にセットアップで作成した
`.deps/python/bin/python3`の絶対パスを指定できます。
FFmpeg/ffprobeは元動画の取り込み・変換に使います。エディターには同梱していません。
クロスコンパイラはSDK内の`.deps/toolchain/bin/m68k-elf-`を優先し、
なければPATHの`m68k-linux-gnu-`を使います。必要なら`megaCd.cross`で接頭辞を指定できます。

| 媒体 | 生成処理 | 成果物 |
|---|---|---|
| Mega Drive ROM | 既存のSGDKビルド | `out/rom.bin` |
| Mega CD | 本SDKによる変換・Main/Subビルド・ディスク作成 | `out/mcd/build-<id>/novel.cue`、`novel.iso`、必要なWAVトラック |

CD向け変換は独立した作業場所で行い、プロジェクトのMD用`src/`・`res/`を生成し直しません。
同じ素材と命令を使いますが、レンダラーの出力は完全同一ではありません。
立ち絵は4スロット・各64×128まで・2アニメーション各2フレームという制約があります。
未対応命令や容量超過など、CD側で表現できない設定は理由付きのビルドエラーになります。
任意のSGDKソースや全てのMDプロジェクトを自動移植するツールではありません。
変換結果の`conversion.json`とBuild Logで対応差分を確認してください。

## 動画アセットと命令

Novelの動画アセット取り込みから元動画を登録します。原本はSHA-256に基づくファイル名で保持し、
安定した`assetId`、動画情報、変換プロファイルを管理します。
エディターのプレビューは元動画の確認用で、メガCDで変換した画質や再生速度を再現するものではありません。
Saturn版と同じ命令形式を使用します。

```json
{ "type": "video", "assetId": "opening", "skippable": true }
```

Mega Drive ROMでは警告を出してこの命令をNOPにし、正本からは削除しません。
Mega CDではMTV1へ変換し、1回再生した後で次の命令へ戻ります。
`skippable: true`なら再生中の新しいB/C/START押下でスキップできます。
動画中はノベルの進行を止め、動画内の16kHzモノラルPCMを使います。
終了後は背景と立ち絵を戻し、再生していたBGMは先頭から再開します。

まず`medium12`（224×160・目標12fps）または`full6`（320×224・目標6fps）で試せます。
Sub PRG RAMの192KiB×2バッファへCDデータを先読みし、2M Word RAMの62KiB×2窓へ転送します。
各窓の予約セクタ2KiBはPCM補充要求にも使います。
立ち絵64KiBはSub PRGの56KiB＋8KiB領域へ一時退避して終了時に復元し、スクリプトとフォントは保持します。
1M Word RAMへの切り替えは使用しません。再バッファ待ちが生じる場合がある試作実装です。
FPSは設定上の目標で、連続再生の性能保証ではありません。[動画ライブラリ](video.md)を参照してください。

## CLIと成果物

エディターと同じビルドを直接呼び出す場合は、未使用または空の出力ディレクトリを
プロジェクトの`out/`以下に指定します。フォントはプロジェクトの設定に合うTTFを指定します。

```sh
python3 tools/build_editor_novel.py \
  --project /path/to/my-novel \
  --output /path/to/my-novel/out/mcd/manual-001 \
  --font /path/to/JF-Dot-Shinonome16.ttf
```

Windowsでは`.\mcd.cmd editor-novel --project ... --output ... --font ...`も使用できます。
オプションの`--ffmpeg`と`--ffprobe`は実行ファイル、`--cross`はクロスコンパイラの接頭辞です。
直接CLIで呼び出す場合も、Novelを保存して有効な`transaction.json`と画像変換を確定しておきます。
正本・変換画像の保存時ハッシュと元画像の変換入力ハッシュを検証し、ビルド中の変更も公開前に再検査します。
通常はPythonだけで検証できます。パレットグループの特殊な文字順を照合できない場合だけ、
エディターと同じ`localeCompare`順で照合するためPATH上のNode.jsが必要になります。
成功時だけ`artifacts.json`を最後に出力し、ISO/CUEと各トラックのサイズ・SHA-256を記録します。
動画ソース・PCM一括補充・作業領域保存／復元を含むIPC ABI`0102`のMain/Subを、同じSDKからビルドします。
エディターは毎回別の出力先を使い、欠けたトラックや前回のROMを成功成果物として流用しません。

CDビルド後の「ROMエクスポート」はCUE・ISO・必要なトラックを新規フォルダーへまとめて保存します。
同梱のWASM/APIエミュレーターとHTMLエクスポートはCD非対応です。
CDのTest Playは案内を表示するため、対応外部エミュレーターでCUEを手動で開いてください。
BIOSは利用者が用意します。
ビルド成功、エミュレーターでの動作、実機の動画性能はそれぞれ別の検証です。
