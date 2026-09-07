/* Sequential optical source cache, independent of Word RAM ownership.
 * One pinned Megadev CDC operation fills a PRG bank while Main consumes Word
 * RAM and the Sub loop services PCM. A bank is evicted only after a newer read
 * starts at or beyond its end; overlapping Main cache windows remain valid. */
#include <mcd/video_source.h>
#include <mcd/protocol.h>
#ifdef MCD_VIDEO_SOURCE_HOST_TEST
#include "video_source_host.h"
#else
#include <sub/cdrom.def.h>
#endif

extern volatile u16 access_op, access_op_result, sub_ticks;
extern void mcd_read_range(u32 sector, u32 count, u8 *destination);

typedef struct { u32 offset, bytes; u16 state; } SourceBank;
static SourceBank banks[2];
/* State words also avoid adjacent byte stores being merged at odd addresses. */
static u16 active, pending, quarantined, fault, result, operation, loading=2, start_tick;
static u16 have_read, workspace_saved;
static u32 sector, limit, next_offset, read_floor, read_offset, read_bytes, copied;
static u8 *read_destination;
enum { EMPTY, LOADING, READY };
enum { OPEN=1, READ, CLOSE, SAVE, RESTORE };

static u8 *bank_buffer(u16 index)
{
#ifdef MCD_VIDEO_SOURCE_HOST_TEST
  return mcd_video_source_test_buffer(index);
#else
  return (u8 *)(index ? 0x40000UL : 0x10000UL);
#endif
}

static void complete(u16 error)
{
  result=error;
  pending=0;
}

static void copy_sector_run(u8 *destination,const u8 *source,u32 bytes)
{
#ifdef MCD_VIDEO_SOURCE_HOST_TEST
  u16 *to=(u16 *)destination;
  const u16 *from=(const u16 *)source;
  for(u16 count=(u16)(bytes>>1);count;--count)*to++=*from++;
#else
  /* Every run is sector-aligned and even-addressed. Eight long moves avoid a
   * per-word C loop consuming most of a video-frame interval for a 62 KiB
   * window. Keep each call at 2 KiB so the outer Sub loop still services PCM.
   * MOVE.L needs only even alignment on the original M68000. */
  u16 count=(u16)((bytes>>5)-1);
  asm volatile(
    "1:\n\t"
    "move.l (%1)+,(%0)+\n\t"
    "move.l (%1)+,(%0)+\n\t"
    "move.l (%1)+,(%0)+\n\t"
    "move.l (%1)+,(%0)+\n\t"
    "move.l (%1)+,(%0)+\n\t"
    "move.l (%1)+,(%0)+\n\t"
    "move.l (%1)+,(%0)+\n\t"
    "move.l (%1)+,(%0)+\n\t"
    "dbra %2,1b"
    : "+a"(destination), "+a"(source), "+d"(count) : : "memory","cc");
#endif
}

static u8 *workspace_buffer(u32 offset)
{
  u16 segment=offset>=0xE000UL;
#ifdef MCD_VIDEO_SOURCE_HOST_TEST
  return mcd_video_source_test_backup(segment)+(segment?offset-0xE000UL:offset);
#else
  /* The SP linker region ends at 0xc000. Keep 0xc000..0xdfff free, and keep
   * the legacy upper 8 KiB exclusion at 0x7e000..0x7ffff unchanged. */
  return segment?(u8 *)(0xE000UL+offset-0xE000UL):(u8 *)(0x70000UL+offset);
#endif
}

static void prefetch(void)
{
  u16 slot=2;
  if(!active || fault || operation==CLOSE || loading<2 || next_offset==limit)return;
  for(u16 i=0;i<2;++i) {
    if(banks[i].state==EMPTY ||
       (banks[i].state==READY && banks[i].offset+banks[i].bytes<=read_floor)) {
      slot=i;break;
    }
  }
  if(slot==2)return;
  banks[slot].offset=next_offset;
  banks[slot].bytes=limit-next_offset;
  if(banks[slot].bytes>MCD_VIDEO_SOURCE_BANK_BYTES)banks[slot].bytes=MCD_VIDEO_SOURCE_BANK_BYTES;
  banks[slot].state=LOADING;
  next_offset+=banks[slot].bytes;
  loading=slot;start_tick=sub_ticks;
  /* mcd_read_range atomically publishes the coroutine parameters/access_op. */
  mcd_read_range(sector+(banks[slot].offset>>11),banks[slot].bytes>>11,bank_buffer(slot));
}

u16 mcd_video_source_open(u32 file_sector,u32 file_bytes,u32 offset,u32 bytes)
{
  u32 rounded,first;
  if(active || pending || access_op)return MCD_ERR_BUSY;
  if(!bytes || (offset&2047))return MCD_ERR_ARGUMENT;
  if(bytes>0xFFFFF800UL)return MCD_ERR_SIZE;
  rounded=(bytes+2047UL)&~2047UL;
  if(offset>file_bytes || rounded>file_bytes-offset)return MCD_ERR_SIZE;
  if(file_sector>0xFFFFFFFFUL-(offset>>11))return MCD_ERR_SIZE;
  first=file_sector+(offset>>11);
  if(first>0xFFFFFFFFUL-((rounded>>11)-1))return MCD_ERR_SIZE;
  sector=first;limit=rounded;next_offset=read_floor=0;have_read=0;
  for(u16 i=0;i<2;++i)banks[i].state=EMPTY;
  loading=2;fault=result=quarantined=pending=0;active=1;operation=OPEN;
  read_offset=read_bytes=copied=0;read_destination=0;
  prefetch();
  return MCD_OK;
}

u16 mcd_video_source_read(u32 offset,u32 bytes,u8 *destination)
{
  if(!active)return MCD_ERR_NOT_READY;
  if(quarantined)return MCD_ERR_TIMEOUT;
  if(pending)return MCD_ERR_BUSY;
  if(fault)return fault;
  if(!destination || ((__UINTPTR_TYPE__)destination&1) || !bytes || bytes>65536UL ||
     ((offset|bytes)&2047))return MCD_ERR_ARGUMENT;
  if(offset>limit || bytes>limit-offset)return MCD_ERR_SIZE;
  if(have_read && offset<read_floor)return MCD_ERR_ARGUMENT;
  read_floor=offset;have_read=1;
  read_offset=offset;read_bytes=bytes;read_destination=destination;copied=0;
  pending=1;operation=READ;result=MCD_OK;
  return MCD_OK;
}

u16 mcd_video_source_close(void)
{
  if(!active)return MCD_ERR_NOT_READY;
  if(quarantined)return MCD_ERR_TIMEOUT;
  if(pending)return MCD_ERR_BUSY;
  operation=CLOSE;pending=1;result=MCD_OK;copied=0;
  return MCD_OK;
}

u16 mcd_video_workspace_save(u8 *word_actors)
{
  if(quarantined)return MCD_ERR_TIMEOUT;
  if(pending || workspace_saved || (access_op && !active))return MCD_ERR_BUSY;
  if(!word_actors || ((__UINTPTR_TYPE__)word_actors&1))return MCD_ERR_ARGUMENT;
  read_destination=word_actors;copied=0;operation=SAVE;pending=1;result=MCD_OK;
  return MCD_OK;
}

u16 mcd_video_workspace_restore(u8 *word_actors)
{
  if(quarantined)return MCD_ERR_TIMEOUT;
  if(pending || (access_op && !active))return MCD_ERR_BUSY;
  if(!workspace_saved)return MCD_ERR_NOT_READY;
  if(!word_actors || ((__UINTPTR_TYPE__)word_actors&1))return MCD_ERR_ARGUMENT;
  read_destination=word_actors;copied=0;operation=RESTORE;pending=1;result=MCD_OK;
  return MCD_OK;
}

void mcd_video_source_update(void)
{
  if(quarantined)return;
  if(pending && (operation==SAVE || operation==RESTORE)) {
    u8 *backup=workspace_buffer(copied);
    if(operation==SAVE)copy_sector_run(backup,read_destination+copied,2048);
    else copy_sector_run(read_destination+copied,backup,2048);
    copied+=2048;
    if(copied==65536UL) {
      workspace_saved=operation==SAVE;
      complete(MCD_OK);
    }
    /* Existing prefetch can complete via INT2 during this bounded copy. Its
     * completion is collected on the next ordinary update; no buffer overlaps. */
    return;
  }
  if(!active)return;
  if(loading<2) {
    if(!access_op) {
      asm volatile("" ::: "memory"); /* CDC writes completed before publication. */
      if(access_op_result!=CDROM_RESULT_OK) {
        banks[loading].state=EMPTY;fault=MCD_ERR_READ;
      } else banks[loading].state=READY;
      loading=2;
    } else if((u16)(sub_ticks-start_tick)>1200) {
      /* Keep the reservation and access_op unchanged. The kernel quarantines
       * the command instead of acknowledging a transfer that is still live. */
      fault=result=MCD_ERR_TIMEOUT;quarantined=1;return;
    }
  }
  if(pending && operation==CLOSE) {
    if(loading<2)return;
    active=0;fault=0;
    for(u16 i=0;i<2;++i)banks[i].state=EMPTY;
    complete(MCD_OK);return;
  }
  if(fault) {
    if(pending)complete(fault);
    return;
  }
  if(pending && operation==READ) {
    u32 cursor=read_offset+copied;
    for(u16 i=0;i<2;++i) {
      if(banks[i].state==READY && cursor>=banks[i].offset && cursor-banks[i].offset<banks[i].bytes) {
        u32 available=banks[i].bytes-(cursor-banks[i].offset);
        u32 run=read_bytes-copied;
        if(run>available)run=available;
        if(run>2048)run=2048; /* Return to PCM servicing between bounded copies. */
        copy_sector_run(read_destination+copied,bank_buffer(i)+cursor-banks[i].offset,run);
        copied+=run;
        if(copied==read_bytes)complete(MCD_OK);
        break;
      }
    }
  }
  prefetch();
}

bool mcd_video_source_active(void) { return active!=0; }
bool mcd_video_source_pending(void) { return pending!=0; }
bool mcd_video_source_quarantined(void) { return quarantined!=0; }
u16 mcd_video_source_result(void) { return result; }
u32 mcd_video_source_loaded(void) { return copied; }
bool mcd_video_workspace_saved(void) { return workspace_saved!=0; }
