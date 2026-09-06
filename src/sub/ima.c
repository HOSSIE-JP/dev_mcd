#include <mcd/ima.h>
static const int steps[89] = {
  7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,
  60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,
  307,337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,
  1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,
  4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,
  12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767
};
static const int changes[8] = {-1,-1,-1,-1,2,4,6,8};
int MCD_imaDecodeNibble(MCD_IMAState *s, unsigned code)
{
  int step = steps[s->index], delta = step >> 3;
  if (code & 1) delta += step >> 2;
  if (code & 2) delta += step >> 1;
  if (code & 4) delta += step;
  s->predictor += (code & 8) ? -delta : delta;
  if (s->predictor > 32767) s->predictor = 32767;
  if (s->predictor < -32768) s->predictor = -32768;
  s->index += changes[code & 7];
  if (s->index < 0) s->index = 0;
  if (s->index > 88) s->index = 88;
  return s->predictor;
}
unsigned char MCD_pcmSignMagnitude(int sample)
{
  unsigned magnitude = (sample < 0 ? -sample : sample) >> 8;
  if (magnitude > 126) magnitude = 126; /* 0xFF is the RF5C164 loop marker. */
  return (unsigned char)(sample < 0 ? magnitude : (magnitude | 0x80));
}
