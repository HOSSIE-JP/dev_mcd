# 検証記録

## 2026-09-07 メガCDノベル／動画統合

2026-09-07にLinux環境で検証。エミュレーターは固定版Genesis Plus GX
`a7985a9c4278ac352f8ca7bb4d3cc6b36e9e3e7d`、Megadevは
`7a7246c14b845ad2f1bd3c7d73afb04cf67d83ef`。
GCC 13.3.0、binutils 2.42で両CPUをM68000／通常32bit引数ABIとしてビルドした。
利用者所有の日本版BIOSはローカル検証だけに使用し、配布物には含めない。

| 検証 | 結果 |
|---|---|
| `make all bridge novel video` | ネイティブISO/CUE生成成功 |
| `make host-test` | 65件成功。ブリッジ境界、MTV1形式、PCM、先読み、画面退避、エディター変換・素材整合を検証 |
| `tools/doctor.py` | 固定依存・ツールチェーン・配布対象の検査成功 |
| 基礎ブリッジの実行 | タイル／スクロール／フェード／入力／CD読込同時処理の7項目成功 |
| 既存メディアサンプル | 画像、ADPCM、CD-DA、同時再生、停止・再開・再読込成功 |
| 既存ノベルのルート `0,0 --listen` | 65,156フレーム、16シーン、254メッセージ、2分岐、257音声、エンディングから先頭復帰。エラー／音声underrunとも0 |
| 調査スレッドのMTV1互換 | 6種類の元データ、計879フレームをC/Pythonで検査 |
| 動画のネイティブ実行 | 音声ありEOF、無音EOF、音声開始後の入力スキップ成功。性能は[動画の実測表](video.md)参照 |
| エディター標準ノベルのCD化 | 正本とMD用ソースを保持してISO/CUE生成。メッセージ・選択肢・シーン遷移を実行 |
| エディターの動画サンプル | 背景＋4立ち絵＋SpriteTextをEOF／スキップ後に全画素一致で復元。スキップボタン押し続けによる次メッセージの誤送りなし |

エディター側の全体テストは402件中393成功、8失敗、1スキップ。
8件は変更前にも存在したBulletMLテンプレートの素材／proof欠落に起因する。
今回のMD/CDビルド、成果物保存、動画取込・プレビューの追加テストは成功している。
同一正本のMDコンパイラー出力では動画が警告付きNOPとなることを確認した。
この環境ではSGDKによるMD実ROMの再ビルド、ElectronのGUI操作、Windows/MSYS2の
実行、実機・実光学ドライブでの再生速度は未検証。CIのWindowsビルド手順は更新した。

再現コマンドと対応範囲:
[ブリッジ](../examples/bridge_demo/README.md)、
[動画](../examples/video_demo/README.md)、
[エディターからのビルド](editor-novel.md)、
[SGDK機能差分](sgdk-compatibility.md)。
動画の指定FPSは変換時の時間軸であり、全フレームの表示保証ではない。
EOFまでの音声サンプル数、描画枚数、読み込み待ち、再バッファ回数を分けて記録する。

## 初期検証

- ビルド: Linux x86_64、m68k-linux-gnu GCC 13.3.0 / binutils 2.42、`-m68000`。
- 基盤: Megadev v1.2.0、コミット`7a7246c14b845ad2f1bd3c7d73afb04cf67d83ef`。
- エミュレータ: 改変していないGenesis Plus GX libretro、コミット`a7985a9c4278ac352f8ca7bb4d3cc6b36e9e3e7d`。
- BIOS: ユーザー提供の日本版Mega CD 1。ローカル専用として使用。
- BIOS本体、セーブステート、BIOSを含むメモリダンプはGitにもCIにも保存していません。

| 検査 | 結果 |
|---|---|
| 日本版BIOSからCUEによるCD起動 | PASS |
| CDから320×224・16色の画像を読み込み・表示 | PASS（目視確認も実施） |
| 圧縮IMA ADPCMをCDからロードしSub CPUで展開 | PASS |
| PCM音源からADPCM音声を出力 | PASS（両ch RMS 約5458） |
| ADPCM約2秒再生後の無音 | PASS |
| CD-DAトラック2のステレオ音声出力 | PASS（左右ch RMS 約7777） |
| CD-DA一時停止・再開 | PASS（無音／音声の切り替わり） |
| CD-DA未再生時の一時停止・再開 | PASS（NOT_READY、画面更新継続） |
| 読み込み済みADPCMとCD-DAの同時出力 | PASS（440 Hz / 330 Hz / 550 Hzを同じ出力で検出） |
| 両方の音声停止 | PASS |
| CDから画像を再ロード | PASS |
| ADPCM再生中にMainフレームカウンタが進む | PASS |
| IMA既知ベクトル・飽和・PCMループ記号回避 | PASS |
| ISOディレクトリ・extent・ファイル内容 | PASS |
| CD-DAの音声形式・2秒プリギャップ | PASS |
| アセット再生成でSHA-256一致 | PASS |
| 存在しない画像ファイル | PASS（NOT_FOUND、画面更新継続） |
| 256 KiBを超える画像ファイルの申告サイズ | PASS（SIZEエラー、転送開始前に拒否） |
| ADPCMヘッダの不正なステップインデックス | PASS（FORMATエラー、画面更新継続） |

`tools/smoke.py`はコントローラ入力を送り、実際のエミュレータ画面・音声を取得して検査します。
テレメトリはサンプルが予約した24バイトのみ読みます。
起動・画面のソースコード検査だけを実行確認と扱っていません。

![日本版BIOSから起動したサンプル画面](evidence/native-cd.png)

実行時の数値は[正常系JSON](evidence/emulator-report.json)と
[異常系JSON](evidence/error-report.json)に保存しています。
ディスクのSHA-256、サンプル専用テレメトリ、音声の測定結果を含みます。

Linuxの[クリーンCIビルド](https://github.com/HOSSIE-JP/dev_mcd/actions/runs/34057673873)も成功しました。
コミット`c5e9007`のCIで生成したCUE / ISO / WAVを取得し、提供BIOSで検証済みの
ローカルビルドと3ファイルがバイト単位で一致することを確認しています。

加えて、Linux上でソースから構築した`m68k-elf-gcc 14.2.0`とbinutils 2.42でも、
分離したチェックアウトからサンプルを生成して同じBIOS検証を通しました。
画像表示・ADPCM・CD-DA・同時再生・停止・再開の全項目がPASSです。
数値は[GCC 14の正常系JSON](evidence/gcc14-emulator-report.json)に保存しています。

## Windowsのクリーン構築と生成物

同じ[CI実行](https://github.com/HOSSIE-JP/dev_mcd/actions/runs/34057673873)のWindows Server 2022で、
MSYS2の新規展開からGCC 14.2.0 / binutils 2.44の構築、サンプル生成まで成功しました。
`mcd.cmd build`、`mcd.cmd doctor`、`mcd.cmd test`の3コマンドも実際に実行して成功しています。
BIOSを使用しないホストテスト4件もPASSです。

初回の参考時間は、ホスト準備97秒、クロスコンパイラとサンプルの構築2071秒、合計約36分です。
CIの並列数は4で、PCの性能や回線によって時間は変わります。
通常のサンプル編集では構築済みコンパイラを再利用します。

WindowsのCIが生成したCUE / ISO / WAVをローカルへ取得し、提供BIOSと同じGenesis Plus GXで
起動・画像表示・ADPCM・CD-DA・同時再生・停止・一時停止・再開・画像再読み込みを確認しました。
全項目PASSで、画面の目視確認も実施しています。これはWindowsで生成したディスクを
Linux上のエミュレータで検査した結果です。

[Windows生成物の正常系JSON](evidence/windows-emulator-report.json)と
[CI・ツール版・生成物SHA-256の記録](evidence/ci-build.json)を保存しています。
Linux版とWindows版はコンパイラ・リンカの版が異なり、ISOのSHA-256も異なります。
CUEとCD-DAのWAVは一致しています。

実機での確認は未実施です。WindowsのGUIエミュレータ、別BIOS、PALでの確認も未実施です。

## 再実行

```sh
make all host-test
python3 tools/deps.py --emulator
make -C .deps/genesis-plus-gx -f Makefile.libretro -j2
python3 tools/smoke.py --bios /path/to/your-japanese-bios.bin
python3 tools/error_smoke.py --bios /path/to/your-japanese-bios.bin
```

`build/validation/report.json`が集計、同じ場所のPNG / WAVがエミュレータ出力です。
BIOSは`.local/smoke/system/`にだけ配置します。検証出力は通常Git管理外です。

## 実機での確認項目

CUE / ISO / WAVを混在モードCDとして書き込み、日本版メガCDで起動し、
A/B/C・上/下・STARTの各操作を確認してください。CD-DAはデータトラックにWAVを
コピーする方式ではなく、トラック2として書き込む必要があります。
光学ドライブのシーク・読み取りエラー・連続動作と、異なるBIOSの挙動は今後の確認対象です。
