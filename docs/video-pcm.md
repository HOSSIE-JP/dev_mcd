# MTV1動画用PCMサービス

`src/sub/video_stream.c` はMTV1の16 kHz・モノラル・符号絶対値PCM8を
RF5C164のWave RAMへ送る専用サービスです。圧縮IMAを常駐させる既存
`stream.c` とは別の経路で、動画音声の再生中はWave RAMを占有します。
コードは `libmcd_sub.a` に入り、Mainからは `mcd/bridge.h` を使用します。

## 呼び出し順

1. 既存のCD要求の完了を待つ。
2. `MCD_videoAudioBeginAsync(totalSamples)` を発行して完了を待つ。
   SubはCD-DAを停止し、既存IMAの再生・準備中・準備済み状態を無効化する。
3. Word RAMにロードしたレコードのPCM範囲について、
   `MCD_videoAudioFeedAsync(wordByteOffset, count)`、または複数レコードをまとめる
   `MCD_videoAudioFeedBatchAsync(descriptorOffset, descriptorCount)` を発行する。
   オフセットはMainアドレス`200000`からのバイト数。CD位置ではない。
4. 十分な先読み後に `MCD_videoAudioPlayAsync()` を発行する。
5. フレームを送りながらFEEDを継続し、`MCD_videoAudioClockAsync()` の完了後に
   `MCD_getVideoAudioClock()` を取得する。映像PTSとこのサンプル数を比較する。
6. 終了・スキップ・エラーでは `MCD_videoAudioStopAsync()` の完了を待つ。
   ノベルのBGMを再開する場合は、元の圧縮素材から再準備する。

各非同期関数の戻り値は要求を受理できたかどうかです。
`MCD_isBusy()==false` になった時点の `MCD_getResult()` が実行結果になります。
動画PCMが有効な間、通常の音声・画像ファイル要求はSub側でBUSYを返します。
動画ソースを開いている間は `MCD_videoSourceReadAsync()` で先読み済みPRG RAMから
Word RAMへコピーします。通常の `MCD_readRangeAsync()` はソース予約がない場合だけ受理します。

## 容量と音声時計

- Wave RAMの`0000..FFFE`が65535サンプルのリング、`FFFF`が固定のFFループマーカー。
  PCM本文のFFは全体検査してから拒否します。入力不正時に一部だけ書き込みません。
- FEEDは1–32768サンプル、リング内の未再生分の上限は65279サンプルです。
  残り256サンプルを無音の保護領域として確保します。容量不足はBUSYを返します。
- 再生した領域も無音へ戻し、空き領域から古い周回の音声が鳴ることを防ぎます。
  カーネルはハードウェア位置をリング1周（約4.09秒）より短い間隔で読む必要があります。
- 分周値は1007。実際のハードウェア再生位置を上位／下位／上位で整合して読み、
  周回を加算した32ビットのサンプル数を時計にします。
  映像を別の60 Hzカウンタだけで進めて分周丸め誤差を累積させません。
- EOFは宣言した総サンプル数で停止します。取り込みは総数を越えるとSIZEエラー。
- 不足時はPCMを停止し、`MCD_ERR_AUDIO_UNDERRUN` とフラグを残します。
  時計は実際に投入済みのサンプル数へ制限します。再開にはSTOP→BEGIN→先読み→PLAYが
  必要です。BEGINへ残りサンプル数を渡し、Mainがそれまでの時計を加算すれば、
  キャッシュ境界の再バッファ待機でも音声を飛ばさずに続行できます。

短い先読みでPLAYすること自体は可能ですが、再生継続を保証するものではありません。
動画プレイヤーは別サービスの192 KiB×2 PRG先読みを組み合わせます。
PCMサービス単体の容量検査と、CD・描画を合わせた連続再生の性能測定は分けて確認します。

## ABIと所有権

Main/Sub ABIを`0102`へ更新しました。同じビルドのMainとSubを使用してください。
既存のSTAT5（Sub tick）、STAT6（ABI）、STAT7（起動完了）を時計へ転用しません。

| コマンド番号 | 命令 | CMD1 / CMD2 / CMD3 | 完了ペイロードSTAT2:3 |
|---:|---|---|---|
| 13 | BEGIN | 総サンプル数上位 / 下位 / 未使用 | 0 |
| 14 | FEED | Word RAMオフセット上位 / 下位 / サンプル数 | 再生済みサンプル数 |
| 15 | PLAY | 未使用 | 再生済みサンプル数 |
| 16 | STOP | 未使用 | 最終再生済みサンプル数 |
| 17 | CLOCK | 未使用 | 再生済みサンプル数 |
| 21 | FEED_BATCH | Word記述子表オフセット上位 / 下位 / 記述子数 | 再生済みサンプル数 |

FEED_BATCHは1〜64件の8バイト記述子を使います。各記述子はビッグエンディアンの
`offset:u32, samples:u16, reserved:u16=0`。全件の範囲・PCM・合計容量を検査してから
書き込み、後半の不正な記述子で先頭部分だけを書き換えません。1要求の合計は残りの
リング容量以内に制限されます。成功なら全サンプルが投入済みで、コピー中の実際の
音声不足は音声フラグ／時計で別に通知します。

FEED／FEED_BATCHはMainから2M Word RAMをSubへ渡します。Subは範囲を検査してPCMをコピーし、
Word RAMを返してから完了を公開します。MainはACKだけでなく所有権が戻るまで待つため、
VDP転送とSubの読み込みを重ねて同じWord RAMを競合させません。
タイムアウトした要求を解除してバッファを再利用することはありません。

STAT4の追加フラグはREADY=`0400`、PLAYING=`0800`、UNDERRUN=`1000`、ENDED=`2000`。
READYはサービスが確保済みである意味であり、所定の秒数を先読み済みという意味ではありません。

## 検証

`python3 -m unittest discover -s tests -p test_video_pcm.py -v` が実際のSub側コードを
ホストのPCMポートへ接続し、64 KiBバンク・リング周回、容量、FF混入、末尾、
不足時の停止とサンプル時計、明示的な再準備を検査します。
`test_bridge.py` はFEEDのACK後も所有権返却前にはWord RAMを再利用しないことを検査します。
ホスト試験でM68000上のCD供給帯域やVDP転送時間を検証したとは扱いません。
