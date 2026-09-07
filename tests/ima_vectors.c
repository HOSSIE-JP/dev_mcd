#include <assert.h>
#include <stdio.h>
#include <mcd/ima.h>
int main(void)
{
  /* IMA WAV block 00000000 10325476, decoded independently by FFmpeg.
     The block's initial zero predictor is omitted from these eight results. */
  const int golden[8] = {0,1,4,8,15,27,47,88};
  MCD_IMAState s = {0,0};
  for (unsigned n=0;n<8;n++) assert(MCD_imaDecodeNibble(&s,n)==golden[n]);
  s.predictor=32760; s.index=88;
  assert(MCD_imaDecodeNibble(&s,7)==32767 && s.index==88);
  s.predictor=-32760; s.index=88;
  assert(MCD_imaDecodeNibble(&s,15)==-32768 && s.index==88);
  s.predictor=0; s.index=0;
  assert(MCD_imaDecodeNibble(&s,0)==0 && s.index==0);
  assert(MCD_pcmSignMagnitude(0)==0x80);
  assert(MCD_pcmSignMagnitude(256)==0x81);
  assert(MCD_pcmSignMagnitude(-256)==1);
  for (int sample=-32768;sample<=32767;sample++) assert(MCD_pcmSignMagnitude(sample)!=0xFF);
  puts("IMA golden vector, predictor/index saturation, RF5C164 marker avoidance: PASS");
  return 0;
}
