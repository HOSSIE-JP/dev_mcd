#ifndef MCD_BRIDGE_HOST_H
#define MCD_BRIDGE_HOST_H
#include <types.h>
extern volatile u16 mcd_test_cmd[8], mcd_test_stat[8];
extern volatile u8 mcd_test_memmode, mcd_test_joy;
void mcd_test_control(u32 value);
void mcd_test_register(u16 value);
void mcd_test_data(u16 value);
#endif
