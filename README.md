# dev_mcd / MCD Bridge

メガCD専用の長期開発ブランチ `long-term/mcdk-native`。
Megadev v1.2.0のCDブートを基盤に、SGDK風Main APIとSub CPU常駐サービスを実装しています。

画像表示、IMA ADPCMのSub CPU展開→RF5C164再生、CD-DA再生に対応。
SGDK本体はリンクしていません。APIの対応範囲は限定されています。
`make libs`でMain / Sub用の静的ライブラリを生成でき、サンプル自身もこれらを使用します。

## Windowsで始める

Windows 10/11 x64、Git、PowerShellを使用します。
Docker・WSL・システムへのMSYS2インストールは不要です。
パスはASCII文字・空白なしにしてください（例: `D:\homebrew\dev_mcd`）。

```powershell
git clone --branch long-term/mcdk-native https://github.com/HOSSIE-JP/dev_mcd.git
cd dev_mcd
powershell -ExecutionPolicy Bypass -File tools\setup.ps1
.\mcd.cmd build
.\mcd.cmd doctor
.\mcd.cmd test
```

初回は`.deps/msys64`にポータブルMSYS2を展開し、GCC 14.2.0 / binutils 2.44の
M68000向けクロスコンパイラを`.deps/toolchain`にビルドします。
MSYS2配布物・GNUソースのSHA-256、Megadevのコミットを固定しています。
初回のコンパイラ構築には時間と数GBの空き容量が必要です。2回目以降は再利用します。
Windows CIでは新規導入からサンプル構築まで約36分で完了しています（環境により変動します）。
ホストMSYS2パッケージは更新されるため、導入バージョンを`.deps/logs/msys2-packages.txt`に記録します。

## Linux

```sh
sudo apt-get install git make python3 gcc gcc-m68k-linux-gnu binutils-m68k-linux-gnu
bash tools/setup-linux.sh
```

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

## 検証

提供された日本版BIOSでGenesis Plus GXを起動し、画像・音声出力、停止・一時停止・再開を確認しています。
Windows / LinuxのクリーンCIビルドも成功し、Windows生成物も同じBIOSで再生確認済みです。
詳細は[検証記録](docs/validation.md)を参照してください。実機での検証は別途必要です。

```sh
python3 tools/deps.py --emulator
make -C .deps/genesis-plus-gx -f Makefile.libretro -j2
python3 tools/smoke.py --bios /absolute/path/to/your-japanese-bios.bin
```

上記の自動エミュレータ検証はLinux向けです。画面・音声・結果JSONを`build/validation/`に出力します。
BIOSやセーブステートは結果に含めません。CIもBIOSを必要としないビルド・ホストテストのみ実行します。

## 設計・拡張

- [構成、API、メモリ配置、IPC](docs/architecture.md)
- [画像・ADPCM・CD-DA素材の形式と差し替え](docs/asset-formats.md)
- [ノベルエンジンとPCE第1話の取り込み](docs/novel.md)
- [他PCでの再構築・BIOSの扱い](docs/setup.md)
- [検証結果と制限](docs/validation.md)

Megadev由来コードの著作権表示は[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)にあります。
