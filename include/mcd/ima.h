#ifndef MCD_IMA_H
#define MCD_IMA_H
/* Uses int rather than stdint so the exact decoder also builds on a host. */
typedef struct { int predictor; int index; } MCD_IMAState;
int MCD_imaDecodeNibble(MCD_IMAState *state, unsigned code);
unsigned char MCD_pcmSignMagnitude(int sample);
unsigned char MCD_imaDecodePCM(MCD_IMAState *state, unsigned code);
#endif
