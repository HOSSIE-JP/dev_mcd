# MTV1動画サンプル

CD内の動画を少量ずつ読み、VDPのタイル更新とRF5C164の16kHzモノラルPCMを再生します。
初回はコードから3秒の動画と440Hzの検査音を生成します。外部の映像・音声素材は不要です。
NumPy/Pillowとクロスコンパイラは[セットアップ](../../README.md)で準備してください。

```powershell
.\mcd.cmd video
```

Linux / MSYS2内では`make video`です。
`dist/video_demo.cue`と`dist/video_demo.iso`を同じフォルダーに置き、
日本版メガCD対応エミュレーターでCUEを開きます。

| 操作 | 動作 |
|---|---|
| メニューのB / C / START | 動画内のPCM音声付きで再生 |
| メニューのA | 無音で再生する診断モード |
| 再生中の新しいB / C / START押下 | 動画をスキップ |
| 再生終了後のボタン | メニューへ戻る |

開始時から押し続けたボタンはスキップと扱いません。
CD処理がタイムアウトした場合は安全のため停止し、再起動が必要です。

## プロファイルと素材変更

既定の`medium12`は224×160・目標12fpsです。
全面向けの`full6`は320×224・目標6fpsです。
準備済みデータはビルド間で再利用されるため、プロファイルを変えるときは明示的に再生成します。

```powershell
.\mcd.cmd video-data VIDEO_PROFILE=full6
.\mcd.cmd video
```

Linuxでは`make video-data VIDEO_PROFILE=full6`、続けて`make video`を実行します。
`video-data`は準備済みの動画を手続き生成サンプルへ置き換えます。

自分の元動画を使う場合は、FFmpeg/ffprobeをPATHへ配置し、リポジトリのシェルで実行します。
Windowsでは先に`.\mcd.cmd shell`を開いてください。

```sh
python3 examples/video_demo/prepare.py --source "/path/to/opening.mp4" --profile medium12
make video
```

変換済みの`.mtv`も`--source`で指定できます。その場合は形式を検査してそのまま使い、
`--profile`では再変換しません。`build/video/manifest.json`で生成した動画の情報を確認できます。
別の動画やプロファイルを使うときは`prepare.py`をもう一度実行してください。

## 現在の制限

MTV1の再生は試作段階です。Sub PRG RAMの192KiB×2バッファへ先読みし、
2M Word RAMの62KiB×2窓へ必要な範囲をコピーします。各窓の予約セクタは2KiBです。
MainがWord RAMを使う間もSub側のCD読込とPCM更新が進みます。
立ち絵用のWord RAM64KiBはSub PRGの56KiB＋8KiBへ退避し、終了時に元へ戻します。
スクリプト・フォントは保持するため1M Word RAM交換は使用しません。
画面の遅れや音声の再バッファ待ちが生じる場合があります。
FPSは変換設定の目標で、実機での持続達成値ではありません。

音声付き経路はCD-DAと既存PCMを停止して動画内音声を専有します。
無音モードは表示とCD読込を確認する診断用で、音声付き性能を示しません。
他のプロファイル、再生状態、フレーム破棄・再バッファのカウンターは
[動画ライブラリ](../../docs/video.md)を参照してください。
