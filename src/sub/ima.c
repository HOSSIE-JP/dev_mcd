#include <mcd/ima.h>
#include "ima_table.h"
static inline int decode(MCD_IMAState *s,unsigned code)
{
  unsigned long value=ima_lookup[(s->index<<3)|(code&7)];
  int delta=value>>8;
  s->predictor+=(code&8)?-delta:delta;
  if(s->predictor>32767)s->predictor=32767;
  if(s->predictor<-32768)s->predictor=-32768;
  s->index=value&255;
  return s->predictor;
}
int MCD_imaDecodeNibble(MCD_IMAState *s,unsigned code) {return decode(s,code);}
unsigned char MCD_pcmSignMagnitude(int sample)
{
  unsigned magnitude = (sample < 0 ? -sample : sample) >> 8;
  if (magnitude > 126) magnitude = 126; /* 0xFF is the RF5C164 loop marker. */
  return (unsigned char)(sample < 0 ? magnitude : (magnitude | 0x80));
}

unsigned char MCD_imaDecodePCM(MCD_IMAState *s,unsigned code) {return MCD_pcmSignMagnitude(decode(s,code));}
