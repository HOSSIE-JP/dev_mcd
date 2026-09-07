/* Freestanding M68000 arithmetic for compilers whose host-target libgcc was
 * built for a later CPU. All operations here use shifts/additions only. */
unsigned long __mulsi3(unsigned long a,unsigned long b) {
  unsigned long r=0;while(b) {if(b&1)r+=a;a<<=1;b>>=1;}return r;
}
unsigned long __udivsi3(unsigned long n,unsigned long d) {
  unsigned long q=0,bit=1;
  if(!d)return 0;
  while(d<n && !(d&0x80000000UL)) {d<<=1;bit<<=1;}
  while(bit) {if(n>=d) {n-=d;q|=bit;}bit>>=1;d>>=1;}return q;
}
unsigned long __umodsi3(unsigned long n,unsigned long d) {
  return n-__mulsi3(__udivsi3(n,d),d);
}
long __divsi3(long n,long d) {
  unsigned long a=n<0?0UL-(unsigned long)n:(unsigned long)n;
  unsigned long b=d<0?0UL-(unsigned long)d:(unsigned long)d;
  unsigned long q=__udivsi3(a,b);return (n<0)!=(d<0)?(long)(0UL-q):(long)q;
}
long __modsi3(long n,long d) {return n-(long)__mulsi3((unsigned long)__divsi3(n,d),(unsigned long)d);}
void *memset(void *dest,int value,unsigned long count) {
  unsigned char *p=dest;while(count--)*p++=(unsigned char)value;return dest;
}
