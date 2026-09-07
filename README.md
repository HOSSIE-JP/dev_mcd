# dev_mcd / MCD Bridge

メガCD専用の開発環境です。開発・統合先は `main` です。
Megadev v1.2.0のCDブートを基盤に、SGDK風Main APIとSub CPU常駐サービスを実装しています。

画像表示、IMA ADPCMのSub CPU展開→RF5C164再生、CD-DA再生に対応。
タイルマップ、スクロール、範囲パレットフェード、入力エッジの基礎APIと、
CDからMTV1動画を読む試作ライブラリを追加しています。
SGDK本体はリンクしていません。汎用`SPR_*`、DMAキュー、ResComp構造体、
XGM2/Z80ドライバー、バックアップRAM等は未対応です。
[SGDK機能との対応表と残項目](docs/sgdk-compatibility.md)を確認してください。
`make libs`でMain / Sub用の静的ライブラリを生成でき、サンプル自身もこれらを使用します。

## Windowsで始める

Windows 10/11 x64、Git、PowerShellを使用します。
Docker・WSL・システムへのMSYS2インストールは不要です。
パスはASCII文字・空白なしにしてください（例: `D:\homebrew\dev_mcd`）。

```powershell
git clone --branch main https://github.com/HOSSIE-JP/dev_mcd.git
cd dev_mcd
powershell -ExecutionPolicy Bypass -File tools\setup.ps1
.\mcd.cmd build
.\mcd.cmd doctor
.\mcd.cmd test
```

初回は`.deps/msys64`にポータブルMSYS2を展開し、GCC 14.2.0 / binutils 2.44の
M68000向けクロスコンパイラを`.deps/toolchain`にビルドします。
動画変換・ノベル取り込み用にUCRT64版PythonとNumPy/Pillowも準備します。
MSYS2配布物・GNUソースのSHA-256、Megadevのコミットを固定しています。
初回のコンパイラ構築には時間と数GBの空き容量が必要です。2回目以降は再利用します。
Windows CIでは新規導入からサンプル構築まで約36分で完了しています（環境により変動します）。
ホストMSYS2パッケージは更新されるため、導入バージョンを`.deps/logs/msys2-packages.txt`に記録します。

## Linux

```sh
sudo apt-get install git make python3 python3-venv gcc gcc-m68k-linux-gnu binutils-m68k-linux-gnu
python3 -m venv .deps/python
. .deps/python/bin/activate
python3 -m pip install -r tools/requirements-novel.txt
bash tools/setup-linux.sh
```

通常のメディアデモと変換済み第1話のビルドはPython標準ライブラリだけでも実行できます。
動画サンプル・動画変換・エディター連携のノベル変換にはNumPy/Pillowを使用します。
元動画や音声素材を変換する場合はFFmpeg/ffprobeもPATHへ配置してください。

## サンプルとライブラリの入口

| 内容 | Windows | Linux / MSYS2内 | 出力・説明 |
|---|---|---|---|
| 画像・ADPCM・CD-DA | `.\mcd.cmd build` | `make all` | `dist/mcd_demo.cue`＋ISO＋WAV |
| 追加ブリッジAPI | `.\mcd.cmd bridge` | `make bridge` | `dist/bridge_demo.cue`＋ISO。[操作](examples/bridge_demo/README.md) |
| MTV1動画・音声 | `.\mcd.cmd video` | `make video` | `dist/video_demo.cue`＋ISO。[素材変更と操作](examples/video_demo/README.md) |
| 第1話ノベル | `.\mcd.cmd novel` | `make novel` | `dist/ishinoura_ep01/ishinoura_ep01.cue`と同フォルダーのISO/WAV |
| Main/Subライブラリ | `.\mcd.cmd libs` | `make libs` | `build/libmcd_main.a`、`build/libmcd_sub.a` |
| ホスト回帰 | `.\mcd.cmd test` | `make host-test` | 形式・境界・所有権・PCMリング等の検査 |

ノベル用の`build/libmcd_novel.a`は`make novel`で生成します。
通常のメガドライブ＋メガCD、JP/NTSCが対象です。32Xは使用しません。

## サンプルを動かす

ビルド結果は`dist/mcd_demo.cue`、`mcd_demo.iso`、`track02.wav`です。
**3ファイルを同じ場所に置き、CUEをエミュレータで開いてください。**
ISO単体にはCD-DAがありません。音源・画像はツールが生成するオリジナルの検査用素材です。

| メガドライブのボタン | 動作 |
|---|---|
| A | 読み込み済みADPCMを再生（約2秒） |
| B | CD-DAトラック2を繰り返し再生 |
| C | 両方の音声を停止 |
| 上 / 下 | CD-DAを一時停止 / 再開 |
| START | CDから画像を再読み込み（CD-DAを停止） |

日本向けBIOS・NTSCのメガCDを対象にしています。BIOSは同梱しません。
手元で吸い出したBIOSは`.local/`などGit管理外の場所に置いてください。
ビルド自体にBIOSは必要ありません。

## ノベルゲーム「いしのうらにいる！？」第1話

MD Game Editorのノベル実行モデルをメガCDへ移植し、PCE版の第1話を取り込みました。
18シーン・275会話、立ち絵の表情と移動、2か所の選択肢、台詞音声とBGM、CD-DAを含みます。

Windowsは `.\mcd.cmd novel`、Linuxは `make novel` でビルドし、
`dist/ishinoura_ep01/ishinoura_ep01.cue` を開いてください。
通常のビルドはコミット済みの変換データを使うため、元エディターや追加Pythonパッケージは不要です。
操作・変換方法・対応範囲は [ノベルエンジンの説明](docs/novel.md) を参照してください。
[実行画面と全4ルートの検証結果](docs/novel-validation.md) も掲載しています。

## 動画サンプル

初回の`make video`は、オリジナルの3秒動画と検査音を`medium12`で生成します。
`medium12`は224×160・目標12fps、`full6`は320×224・目標6fpsです。
設定を変えるときは素材を再生成してからビルドします。

```powershell
.\mcd.cmd video-data VIDEO_PROFILE=full6
.\mcd.cmd video
```

Linuxでは順に`make video-data VIDEO_PROFILE=full6`、`make video`を実行します。
再生画面のB/C/STARTは音声付き再生、Aは無音の診断経路です。
再生中は新しいB/C/START押下でスキップできます。

MTV1は動画内の16kHzモノラルPCMを使い、動画中はCD-DAと既存PCMを停止します。
Sub PRG RAMの**192KiB×2バッファへ非同期に先読み**し、再生に必要な範囲を
2M Word RAMの**62KiB×2窓**へコピーします。各窓には2KiBの予約セクタがあり、PCM補充要求にも使います。
動画中だけ立ち絵64KiBをSub PRGへ56KiB＋8KiBに分けて退避し、終了時に復元します。
スクリプト・フォントはWord RAMに保持し、1M Word RAM交換は使用しません。
再生は試作段階で、表示の遅れや音声の再バッファ待ちは引き続き検証対象です。
設定のFPSは目標値で、実機での連続達成値を示しません。
方式と状態カウンターは[動画ライブラリ](docs/video.md)に記載しています。
IPC ABIは`0102`です。先読み・PCM一括補充・作業領域保存／復元を含むため、Main/Subを両方再ビルドしてください。

## MD Game Editorから同じノベルを両媒体へビルド

対応版[MD Game Editor](https://github.com/HOSSIE-JP/md-game-editor)のNovel → Systemで
「ビルド媒体」をMega Drive ROM / Mega CDへ切り替えます。
同じ`assets/pce-vn-scenes.json`とアセット登録を使い、
メガCDでは本リポジトリの`tools/build_editor_novel.py`がISO/CUEを生成します。
エディターの「Mega CDビルド環境」に、このチェックアウトの場所と変換ツールを設定してください。

動画はアセットとして取り込み、`video`命令で再生します。
MD ROMでは命令を保存したまま警告付きNOP、メガCDでは1回再生して次命令へ戻ります。
任意のSGDKコードを自動変換する機能ではなく、ノベルプロジェクトの対応範囲を検査する方式です。
メガCDは同梱エミュレーターのTest Playに対応しません。対応する外部エミュレーターでCUEを開きます。
設定・CLI・出力・対応差分は[エディター連携](docs/editor-novel.md)を参照してください。

## 検証

既存のメディアデモと第1話には、提供された日本版BIOSを用いたGenesis Plus GXの
画像・音声・入力検証と、Windows / LinuxのCIビルド記録があります。
詳細は[検証記録](docs/validation.md)と[ノベル検証](docs/novel-validation.md)を参照してください。
これらの過去の記録を、新しいブリッジAPIや動画の性能検証として扱わないでください。
ホストテスト、現在のターゲットビルド、エミュレーター動作、実機の持続性能は別々に確認します。
追加ブリッジには`tools/bridge_smoke.py`を用意し、Genesis Plus GXで
スクロール・フェード・入力・並行CD読込を確認しています。[再現手順](examples/bridge_demo/README.md)を参照してください。

```sh
python3 tools/deps.py --emulator
make -C .deps/genesis-plus-gx -f Makefile.libretro -j2
python3 tools/smoke.py --bios /absolute/path/to/your-japanese-bios.bin
```

上記の自動エミュレータ検証はLinux向けです。画面・音声・結果JSONを`build/validation/`に出力します。
BIOSやセーブステートは結果に含めません。CIもBIOSを必要としないビルド・ホストテストのみ実行します。

## 設計・拡張

- [構成、API、メモリ配置、IPC](docs/architecture.md)
- [SGDKとの対応表・追加API・残る不足](docs/sgdk-compatibility.md)
- [動画ライブラリ・プロファイル・再バッファ](docs/video.md)
- [MTV1ファイル形式](docs/video-format.md) / [動画PCMサービス](docs/video-pcm.md)
- [MD Game Editorの同一ノベル／媒体別ビルド](docs/editor-novel.md)
- [画像・ADPCM・CD-DA素材の形式と差し替え](docs/asset-formats.md)
- [ノベルエンジンとPCE第1話の取り込み](docs/novel.md)
- [他PCでの再構築・BIOSの扱い](docs/setup.md)
- [検証結果と制限](docs/validation.md)

Megadev由来コードの著作権表示は[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)にあります。
