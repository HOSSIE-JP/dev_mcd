#!/usr/bin/env python3
"""Original deterministic diagnostic assets; Python standard library only."""
import math
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Original 5x7 diagnostic font, one hex row per line of a glyph.
GLYPHS = {
 'A':'0E11111F111111','B':'1E11111E11111E','C':'0F10101010100F',
 'D':'1E11111111111E','E':'1F10101E10101F','F':'1F10101E101010',
 'G':'0F10101711110F','H':'1111111F111111','I':'0E04040404040E',
 'J':'0702020212120C','K':'11121418141211','L':'1010101010101F',
 'M':'111B1515111111','N':'11191513111111','O':'0E11111111110E',
 'P':'1E11111E101010','Q':'0E11111115120D','R':'1E11111E141211',
 'S':'0F10100E01011E','T':'1F040404040404','U':'1111111111110E',
 'V':'11111111110A04','W':'11111115151B11','X':'11110A040A1111',
 'Y':'11110A04040404','Z':'1F01020408101F',
 '0':'0E11131519110E','1':'040C040404040E','2':'0E11010204081F',
 '3':'1E01010E01011E','4':'02060A121F0202','5':'1F10101E01011E',
 '6':'0E10101E11110E','7':'1F010204080808','8':'0E11110E11110E',
 '9':'0E11110F01010E','-':'0000001F000000',':':'00040000040000',
 '>':'10080402040810','/':'01010204081010','.':'00000000000606',
 '?':'0E110102040004',' ':'00000000000000'
}
STEPS = [7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,
 60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,
 408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,
 1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,
 7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,
 22385,24623,27086,29794,32767]
CHANGES = [-1,-1,-1,-1,2,4,6,8]

def ima_encode(samples):
    predictor = index = 0
    codes = []
    for sample in samples:
        diff = sample-predictor
        code = 8 if diff < 0 else 0
        diff = abs(diff)
        step = STEPS[index]
        delta = step >> 3
        for mask, fraction in ((4,step),(2,step>>1),(1,step>>2)):
            if diff >= fraction:
                code |= mask
                diff -= fraction
                delta += fraction
        predictor = max(-32768,min(32767,predictor + (-delta if code&8 else delta)))
        index = max(0,min(88,index+CHANGES[code&7]))
        codes.append(code)
    return bytes(codes[i] | (codes[i+1]<<4 if i+1<len(codes) else 0) for i in range(0,len(codes),2))

def tile_bytes(pixels):
    return bytes((pixels[i]<<4)|pixels[i+1] for i in range(0,64,2))

def generate():
    out = ROOT/'build/disc'
    out.mkdir(parents=True,exist_ok=True)
    (ROOT/'dist').mkdir(exist_ok=True)
    font = bytearray()
    for code in range(32,128):
        rows = bytes.fromhex(GLYPHS.get(chr(code),GLYPHS['?'])) + b'\0'
        font.extend(tile_bytes([int(bool(rows[y] & (1<<(5-x)))) if 1<=x<=5 else 0 for y in range(8) for x in range(8)]))
    words = struct.unpack('>1536H',font)
    (ROOT/'build/font.h').write_text('static const unsigned short mcd_font[] = {\n' +
        ',\n'.join(','.join(f'0x{v:04X}' for v in words[i:i+16]) for i in range(0,len(words),16))+'\n};\n')
    palette = [0x000,0x200,0x420,0x840,0xA60,0xCA0,0xEE0,0xEEE,
               0x00E,0x08E,0x0CE,0x0E8,0x0E0,0xE06,0xE0E,0x888]
    pixels = [[0]*320 for _ in range(224)]
    for y in range(48,144):
        for x in range(320):
            color = 1 if y<112 else (2 if (x+y)//8%2 else 3)
            if ((x*37+y*19)%211==0) and y<108: color=7
            if (x-160)**2+(y-92)**2 < 33**2: color = 4 + min(3,(x-127)//18)
            if y>113 and (x%32==0 or (y-114)%12==0): color=5
            if 30<x<291 and 134<=y<140: color=8+((x-31)//22)%8
            pixels[y][x]=color
    tiles=bytearray()
    for ty in range(28):
        for tx in range(40):
            tiles.extend(tile_bytes([pixels[ty*8+y][tx*8+x] for y in range(8) for x in range(8)]))
    image = b'MIMG'+struct.pack('>4H',40,28,1120,0)+struct.pack('>16H',*palette)+tiles+struct.pack('>1120H',*range(1120))
    (out/'IMAGE.MIM').write_bytes(image)
    samples=[]
    for n in range(44100):
        # Two distinct half-second notes alternating, with short fades.
        note=(440,660,880,660)[n//11025]
        local=n%11025
        env=min(1,local/220,(11024-local)/440)
        samples.append(round(17000*env*math.sin(2*math.pi*note*n/22050)))
    encoded=ima_encode(samples)
    (out/'SOUND.IMA').write_bytes(b'MIMA'+struct.pack('>HHIhBB',1,22050,len(samples),0,0,0)+encoded)
    with wave.open(str(ROOT/'dist/track02.wav'),'wb') as wav:
        wav.setparams((2,2,44100,0,'NONE','not compressed'))
        # Explicit two-second pregap followed by 8 s of stereo tones.
        data=bytearray(2*44100*4)
        for n in range(8*44100):
            env=min(1,n/441,(8*44100-1-n)/441)
            data.extend(struct.pack('<hh',round(11000*env*math.sin(2*math.pi*330*n/44100)),
                                    round(11000*env*math.sin(2*math.pi*550*n/44100))))
        wav.writeframes(data)
    print(f'Assets: image {len(image)} bytes, IMA ADPCM {len(encoded)} payload bytes, CD-DA 8 s + 2 s pregap')

if __name__=='__main__': generate()
