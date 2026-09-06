# 再構築とローカル設定

## Windows

`tools/setup.ps1`が専用のMSYS2を`.deps/msys64`に展開します。
Windows 10/11 x64の標準PowerShellとGitが前提です。
初期セットアップにネットワークが必要です。管理者権限、Docker、WSLは使いません。
既存のMSYS2やシステムのPATHは書き換えません。

MSYS2/GNU configureの制約から、チェックアウト先はASCII文字・空白なしのパスを使います。
`D:\homebrew\dev_mcd`等を推奨します。

初回はMSYS2の完全更新を実行してからUCRT64のネイティブC/C++コンパイラと開発ライブラリを導入し、
M68000向けGCC 14.2.0 / binutils 2.44をソースから構築します。
配布アーカイブはSHA-256、MegadevはコミットIDで固定します。
MSYS2の展開は公式CIと同じ自己展開パッケージを使い、リポジトリ内で完結します。
一時フォルダへの展開に成功してから`.deps/msys64`へ配置します。
MSYS2のホストパッケージはローリング更新です。完全なバイナリ同一性までは保証せず、
導入一覧を`.deps/logs/msys2-packages.txt`に残します。

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup.ps1
.\mcd.cmd build
.\mcd.cmd test
.\mcd.cmd doctor
.\mcd.cmd shell
```

導入の工程と時刻は`.deps/logs/bootstrap.log`、コンパイラ構築の詳細は
`.deps/logs/binutils.log`と`gcc.log`にあります。失敗した場合は原因を修正して再実行できます。
Windows PowerShell 5.1のダウンロードは`-UseBasicParsing`と300秒のタイムアウトを使用します。
HTMLの解析やスクリプト実行を伴わず、無人セットアップで確認待ちが発生しない方式です
（[Microsoftの説明](https://support.microsoft.com/en-us/servicing/os/windows/2025/12/powershell-5-1-invoke-webrequest-preventing-script-execution-from-web-content)）。
MSYS2初回起動の任意のキーサーバー問い合わせは60秒で打ち切ります。
これは[MSYS2公式CIも対処している工程](https://github.com/msys2/setup-msys2/blob/main/main.js)です。
同梱キーの登録、pacmanのパッケージ署名検証、通常のパッケージ更新は実行します。
MSYS2更新で再起動を求められた場合は、そのMSYS2のシェルを閉じてセットアップを再実行します。
コンパイラの正常インストール完了後にのみ完了マーカーを作るため、途中失敗を成功扱いしません。
別の場所へ移動した後にクロスコンパイラを再構築する場合は、古いconfigureの絶対パスが残る
`.deps/toolchain-build`を退避してから再構築してください。

別PCではリポジトリをチェックアウトして同じセットアップを実行します。
ビルド済みツールやBIOSはGit経由で共有しません。

## BIOSとエミュレータ

手元で吸い出した日本版BIOSを`.local/bios/`へ置くか、リポジトリ外のパスを指定します。
BIOSの自動ダウンロードは実装していません。BIOSなしでもビルドとホストテストは可能です。

Genesis Plus GX / RetroArchでは、手元の日本版BIOSをシステムディレクトリの
`bios_CD_J.bin`として設定し、`dist/mcd_demo.cue`を読み込みます。
エミュレータの入力設定でメガドライブのA/B/C/STARTを割り当ててください。
初回の日本版BIOS画面で起動操作が必要な場合はSTARTを押します。

エミュレータ本体はアプリケーションにリンクも同梱もしません。
自動検証用コアは`python3 tools/deps.py --emulator`で固定コミットを取得できます。
`tools/smoke.py`はLinux上の共有ライブラリを使用します。

`.gitignore`で`.local/`、`.deps/`、BIOS用ディレクトリ、すべての`.bin` / `.rom`、
ディスクイメージ、セーブデータ、セーブステートを除外しています。
`git add -f`で除外を解除しないでください。コミット前に`doctor`を実行します。

## ビルド内容

画像・フォント・ADPCM・CD-DAはPython標準ライブラリで生成します。
ISO9660もリポジトリ内のツールで生成するため、Java・SGDK・mkisofsは不要です。
配布するのは`dist`内のCUE / ISO / WAVの3点です。BIOSや`.local`は配布しません。

確認対象を増やす際も、GitHub ActionsへBIOSをコミット・アップロードしないでください。
CIは新しい環境でのビルドと、BIOSなしのホストテストを担当します。

参照: [MSYS2配布物](https://github.com/msys2/msys2-installer/releases/tag/2026-06-11)、
[GNU GCC](https://gcc.gnu.org/)、[GNU binutils](https://sourceware.org/binutils/)。
