#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <mcd/protocol.h>
#include <mcd/video_source.h>
#include "video_source_host.h"

#define SECTOR 2048UL
#define BANK_BYTES (192UL * 1024)
#define READ_BYTES 65536UL
#define FILE_SECTOR 193UL
#define FILE_OFFSET (5UL * SECTOR)
#define MOVIE_BYTES (5UL * BANK_BYTES + 123)

static _Alignas(2) u8 banks[2][BANK_BYTES];
static _Alignas(2) u8 backup_large[56UL * 1024];
static _Alignas(2) u8 backup_small[8UL * 1024];
static _Alignas(2) u8 actors[READ_BYTES + 4];
static _Alignas(2) u8 output[READ_BYTES + 4];
static u32 optical_sector, optical_count;
static u8 *optical_destination;
static unsigned requests;
volatile u16 access_op, access_op_result, sub_ticks;

u8 *mcd_video_source_test_buffer(u16 bank)
{
    assert(bank < 2);
    return banks[bank];
}

u8 *mcd_video_source_test_backup(u16 segment)
{
    assert(segment < 2);
    return segment ? backup_small : backup_large;
}

/* A delayed drive: only complete_optical() is allowed to write the destination
 * or publish completion. No transfer may target the simulated Main Word RAM. */
void mcd_read_range(u32 sector, u32 count, u8 *destination)
{
    assert(!access_op);
    assert(count && count <= BANK_BYTES / SECTOR);
    assert(destination == banks[0] || destination == banks[1]);
    optical_sector = sector;
    optical_count = count;
    optical_destination = destination;
    ++requests;
    access_op_result = 0;
    access_op = 1;
}

static u8 byte_at(u32 sector, u32 offset)
{
    /* Distinguish bank, sector, and byte boundaries (a repeated fill byte could
     * let a stale bank or an off-by-one copy pass). */
    return (u8)((sector * 73UL) ^ (sector >> 3) ^ offset ^ (offset >> 8));
}

static void complete_optical(u16 result)
{
    assert(access_op && optical_destination);
    if (result == CDROM_RESULT_OK) {
        for (u32 i = 0; i < optical_count * SECTOR; ++i)
            optical_destination[i] = byte_at(optical_sector + i / SECTOR,
                                              i % SECTOR);
    }
    access_op_result = result;
    access_op = 0;
}

static void update(void)
{
    ++sub_ticks;
    mcd_video_source_update();
}

static void await_command(void)
{
    for (unsigned i = 0; i < 40 && mcd_video_source_pending(); ++i) {
        update();
        if (mcd_video_source_pending() && access_op)
            complete_optical(CDROM_RESULT_OK);
    }
    assert(!mcd_video_source_pending());
    assert(mcd_video_source_result() == MCD_OK);
}

static void start_open(u32 bytes)
{
    u32 rounded = (bytes + SECTOR - 1) & ~(SECTOR - 1);
    assert(mcd_video_source_open(FILE_SECTOR, FILE_OFFSET + rounded,
                                 FILE_OFFSET, bytes) == MCD_OK);
    assert(mcd_video_source_active());
    assert(!mcd_video_source_pending());
    assert(mcd_video_source_loaded() == 0);
    update();
    assert(access_op);
    assert(optical_sector == FILE_SECTOR + FILE_OFFSET / SECTOR);
    assert(optical_count == (bytes < BANK_BYTES ? (bytes + SECTOR - 1) / SECTOR
                                              : BANK_BYTES / SECTOR));
}

static void ready_first(void)
{
    start_open(MOVIE_BYTES);
    complete_optical(CDROM_RESULT_OK);
    for (unsigned i = 0; i < 4; ++i) update();
    assert(!mcd_video_source_pending());
    assert(mcd_video_source_result() == MCD_OK);
    assert(mcd_video_source_active());
}

static void close_source(void)
{
    assert(mcd_video_source_close() == MCD_OK);
    await_command();
    assert(!mcd_video_source_active());
    assert(mcd_video_source_loaded() == 0);
    assert(!access_op);
}

static void check_output(u32 offset, u32 bytes)
{
    assert(output[0] == 0xA5 && output[1] == 0xA5);
    assert(output[bytes + 2] == 0xA5 && output[bytes + 3] == 0xA5);
    for (u32 i = 0; i < bytes; ++i) {
        u32 absolute = FILE_OFFSET + offset + i;
        assert(output[i + 2] == byte_at(FILE_SECTOR + absolute / SECTOR,
                                       absolute % SECTOR));
    }
    assert(mcd_video_source_loaded() == bytes);
}

static void read_at(u32 offset, u32 bytes)
{
    memset(output, 0xA5, sizeof(output));
    assert(mcd_video_source_read(offset, bytes, output + 2) == MCD_OK);
    await_command();
    check_output(offset, bytes);
}

static void test_open_prefetch(void)
{
    start_open(MOVIE_BYTES);
    unsigned before = requests;
    for (unsigned i = 0; i < 12; ++i) update();
    assert(!mcd_video_source_pending() && requests == before && access_op);
    memset(output, 0xA5, sizeof(output));
    assert(mcd_video_source_read(0, READ_BYTES, output + 2) == MCD_OK);
    for (unsigned i = 0; i < 12; ++i) update();
    assert(mcd_video_source_pending() && requests == before && access_op);
    for (u32 i = 0; i < sizeof(output); ++i) assert(output[i] == 0xA5);
    complete_optical(CDROM_RESULT_OK);
    for (unsigned i = 0; i < 40 && mcd_video_source_pending(); ++i) update();
    assert(!mcd_video_source_pending() && mcd_video_source_active());
    assert(mcd_video_source_result() == MCD_OK);
    /* Main may consume the completed Word RAM window while bank 1 is filling. */
    assert(requests == before + 1 && access_op);
    assert(optical_sector == FILE_SECTOR + FILE_OFFSET / SECTOR + BANK_BYTES / SECTOR);
    check_output(0, READ_BYTES);
    memset(output, 0xA5, sizeof(output));
    assert(mcd_video_source_read(0, READ_BYTES, output + 2) == MCD_OK);
    for (unsigned i = 0; i < 40 && mcd_video_source_pending(); ++i) update();
    assert(!mcd_video_source_pending() && access_op && requests == before + 1);
    check_output(0, READ_BYTES);
    close_source();
}

static void test_cross_bank(void)
{
    ready_first();
    assert(access_op);
    complete_optical(CDROM_RESULT_OK);
    update();
    read_at(BANK_BYTES - READ_BYTES / 2, READ_BYTES);
    close_source();
}

static void test_overlap_eviction(void)
{
    ready_first();
    u32 rounded = (MOVIE_BYTES + SECTOR - 1) & ~(SECTOR - 1);
    u32 last = 0;
    for (u32 offset = 0; offset + READ_BYTES <= rounded; offset += READ_BYTES - SECTOR) {
        read_at(offset, READ_BYTES);
        last = offset;
    }
    if (last != rounded - READ_BYTES) read_at(rounded - READ_BYTES, READ_BYTES);
    assert(requests >= 6); /* Several safe evictions, including the partial tail. */
    close_source();
}

static void rejected_open(u32 sector, u32 file_bytes, u32 offset, u32 bytes)
{
    unsigned before = requests;
    assert(mcd_video_source_open(sector, file_bytes, offset, bytes) != MCD_OK);
    assert(!mcd_video_source_active() && !mcd_video_source_pending());
    assert(!access_op && requests == before);
}

static void rejected_read(u32 offset, u32 bytes, u8 *destination)
{
    unsigned before = requests;
    assert(mcd_video_source_read(offset, bytes, destination) != MCD_OK);
    assert(mcd_video_source_active() && !mcd_video_source_pending());
    assert(requests == before);
}

static void test_validation(void)
{
    assert(mcd_video_source_read(0, SECTOR, output + 2) != MCD_OK);
    rejected_open(FILE_SECTOR, MOVIE_BYTES, 1, SECTOR);
    rejected_open(FILE_SECTOR, MOVIE_BYTES, 0, 0);
    rejected_open(FILE_SECTOR, MOVIE_BYTES, 6 * BANK_BYTES, SECTOR);
    rejected_open(FILE_SECTOR, MOVIE_BYTES, 0, MOVIE_BYTES + 1);
    rejected_open(FILE_SECTOR, UINT32_MAX, 0, UINT32_MAX);
    rejected_open(UINT32_MAX, 2 * SECTOR, 0, 2 * SECTOR);
    ready_first();
    assert(mcd_video_source_open(FILE_SECTOR, MOVIE_BYTES, 0, SECTOR) == MCD_ERR_BUSY);
    rejected_read(1, SECTOR, output + 2);
    rejected_read(0, 1, output + 2);
    rejected_read(0, 0, output + 2);
    rejected_read(0, READ_BYTES + SECTOR, output + 2);
    rejected_read(0, SECTOR, 0);
    rejected_read(0, SECTOR, output + 1);
    rejected_read(0xFFFFF800UL, SECTOR, output + 2);
    rejected_read(0, 0xFFFFF800UL, output + 2);
    rejected_read(6 * BANK_BYTES, SECTOR, output + 2);
    read_at(SECTOR, READ_BYTES);
    rejected_read(0, SECTOR, output + 2); /* A backward start could reference an evicted bank. */
    read_at(SECTOR, READ_BYTES); /* Equal starts and overlapping windows remain valid. */
    read_at(2 * SECTOR, READ_BYTES);
    close_source();
}

static void test_rounded_tail(void)
{
    start_open(2 * SECTOR + 123);
    await_command();
    read_at(0, 3 * SECTOR); /* Last sector padding is inside the reserved interval. */
    rejected_read(3 * SECTOR, SECTOR, output + 2);
    close_source();
}

static void test_close_prefetch(void)
{
    ready_first();
    assert(access_op);
    u8 *reserved = optical_destination;
    unsigned before = requests;
    assert(mcd_video_source_close() == MCD_OK);
    assert(mcd_video_source_pending() && mcd_video_source_active());
    for (unsigned i = 0; i < 12; ++i) update();
    assert(access_op && optical_destination == reserved && requests == before);
    assert(mcd_video_source_pending() && mcd_video_source_active());
    assert(mcd_video_source_open(FILE_SECTOR, MOVIE_BYTES, 0, SECTOR) == MCD_ERR_BUSY);
    assert(mcd_video_source_read(0, SECTOR, output + 2) == MCD_ERR_BUSY);
    complete_optical(CDROM_RESULT_OK);
    await_command();
    assert(!mcd_video_source_active() && !access_op && requests == before);
    start_open(SECTOR);
    await_command();
    close_source();
}

static void test_open_error(void)
{
    start_open(MOVIE_BYTES);
    assert(mcd_video_source_read(0, SECTOR, output + 2) == MCD_OK);
    complete_optical(1);
    update();
    assert(!mcd_video_source_pending() && mcd_video_source_active());
    assert(mcd_video_source_result() == MCD_ERR_READ);
    assert(mcd_video_source_read(0, SECTOR, output + 2) == MCD_ERR_READ);
    for (unsigned i = 0; i < 4; ++i) update();
    assert(mcd_video_source_result() == MCD_ERR_READ && requests == 1);
    close_source();
    start_open(SECTOR);
    await_command();
    close_source();
}

static void test_prefetch_error(void)
{
    ready_first();
    assert(access_op);
    complete_optical(1);
    update();
    unsigned before = requests;
    assert(!mcd_video_source_pending() && mcd_video_source_active());
    assert(mcd_video_source_read(0, SECTOR, output + 2) == MCD_ERR_READ);
    assert(mcd_video_source_open(FILE_SECTOR, MOVIE_BYTES, 0, SECTOR) == MCD_ERR_BUSY);
    for (unsigned i = 0; i < 4; ++i) update();
    assert(mcd_video_source_read(0, SECTOR, output + 2) == MCD_ERR_READ);
    assert(requests == before && !access_op);
    close_source();
}

static void test_timeout_wrap(void)
{
    sub_ticks = 65000;
    start_open(MOVIE_BYTES);
    u8 *reserved = optical_destination;
    unsigned before = requests;
    sub_ticks = (u16)(65000U + 1202U);
    mcd_video_source_update();
    assert(mcd_video_source_result() == MCD_ERR_TIMEOUT);
    assert(mcd_video_source_quarantined() && mcd_video_source_active());
    assert(access_op && optical_destination == reserved && requests == before);
    assert(mcd_video_source_open(FILE_SECTOR, MOVIE_BYTES, 0, SECTOR) != MCD_OK);
    assert(mcd_video_source_read(0, SECTOR, output + 2) != MCD_OK);
    assert(mcd_video_source_close() != MCD_OK);
    assert(mcd_video_workspace_save(actors + 2) == MCD_ERR_TIMEOUT);
    assert(mcd_video_workspace_restore(actors + 2) == MCD_ERR_TIMEOUT);
    for (unsigned i = 0; i < 8; ++i) update();
    assert(mcd_video_source_result() == MCD_ERR_TIMEOUT);
    assert(mcd_video_source_quarantined() && mcd_video_source_active());
    assert(access_op && optical_destination == reserved && requests == before);
    /* Even a late completion cannot turn the quarantined reservation into a
     * reusable source, nor launch another transfer behind the caller's back. */
    complete_optical(CDROM_RESULT_OK);
    update();
    assert(mcd_video_source_quarantined() && mcd_video_source_active());
    assert(mcd_video_source_result() == MCD_ERR_TIMEOUT && requests == before);
}

static u8 actor_byte(u32 offset)
{
    return (u8)((offset * 31UL) ^ (offset >> 7) ^ (offset >> 12) ^ 0x59);
}

static void fill_actors(void)
{
    memset(actors, 0xC3, sizeof(actors));
    for (u32 i = 0; i < READ_BYTES; ++i) actors[i + 2] = actor_byte(i);
}

static void check_actors(void)
{
    assert(actors[0] == 0xC3 && actors[1] == 0xC3);
    assert(actors[READ_BYTES + 2] == 0xC3 && actors[READ_BYTES + 3] == 0xC3);
    for (u32 i = 0; i < READ_BYTES; ++i) assert(actors[i + 2] == actor_byte(i));
}

static void check_backup(void)
{
    for (u32 i = 0; i < sizeof(backup_large); ++i) assert(backup_large[i] == actor_byte(i));
    for (u32 i = 0; i < sizeof(backup_small); ++i)
        assert(backup_small[i] == actor_byte(sizeof(backup_large) + i));
}

static void check_bank_fill(u8 value)
{
    for (u16 bank = 0; bank < 2; ++bank)
        for (u32 i = 0; i < BANK_BYTES; ++i) assert(banks[bank][i] == value);
}

/* No optical completion is supplied while copying the actor workspace. The
 * caller checks that prefetch keeps its reservation and remains independent. */
static void finish_workspace(bool saved)
{
    assert(mcd_video_source_pending());
    for (u32 done = SECTOR; done <= READ_BYTES; done += SECTOR) {
        update();
        assert(mcd_video_source_loaded() == done);
        assert(mcd_video_source_pending() == (done < READ_BYTES));
        if (done < READ_BYTES) assert(mcd_video_workspace_saved() != saved);
    }
    assert(mcd_video_source_result() == MCD_OK);
    assert(mcd_video_workspace_saved() == saved);
}

static void test_workspace_cycle(void)
{
    fill_actors();
    memset(banks, 0x6B, sizeof(banks));
    assert(!mcd_video_workspace_saved());
    assert(mcd_video_workspace_save(actors + 2) == MCD_OK);
    assert(mcd_video_source_open(FILE_SECTOR, SECTOR, 0, SECTOR) == MCD_ERR_BUSY);
    finish_workspace(true);
    assert(!mcd_video_source_active() && !access_op && requests == 0);
    check_backup();
    check_bank_fill(0x6B);
    check_actors();
    assert(mcd_video_workspace_save(actors + 2) == MCD_ERR_BUSY);

    /* Saved data survives OPEN, every bank eviction, and CLOSE. Simulate the
     * Main renderer replacing the entire actor workspace with video data. */
    memset(actors + 2, 0x17, READ_BYTES);
    ready_first();
    assert(mcd_video_workspace_saved());
    u32 rounded = (MOVIE_BYTES + SECTOR - 1) & ~(SECTOR - 1);
    u32 last = 0;
    for (u32 offset = 0; offset + READ_BYTES <= rounded; offset += READ_BYTES - SECTOR) {
        read_at(offset, READ_BYTES);
        check_backup();
        last = offset;
    }
    if (last != rounded - READ_BYTES) read_at(rounded - READ_BYTES, READ_BYTES);
    assert(requests >= 6);
    close_source();
    assert(mcd_video_workspace_saved());
    check_backup();
    memset(banks, 0xB6, sizeof(banks));
    assert(mcd_video_workspace_restore(actors + 2) == MCD_OK);
    assert(mcd_video_source_open(FILE_SECTOR, SECTOR, 0, SECTOR) == MCD_ERR_BUSY);
    finish_workspace(false);
    check_actors();
    check_bank_fill(0xB6);
    assert(mcd_video_workspace_restore(actors + 2) == MCD_ERR_NOT_READY);
}

static void check_first_ready_bank(void)
{
    for (u32 i = 0; i < BANK_BYTES; ++i)
        assert(banks[0][i] == byte_at(FILE_SECTOR + FILE_OFFSET / SECTOR + i / SECTOR,
                                    i % SECTOR));
    for (u32 i = 0; i < BANK_BYTES; ++i) assert(banks[1][i] == 0xD4);
}

static void test_workspace_prefetch(void)
{
    memset(banks, 0xD4, sizeof(banks));
    fill_actors();
    ready_first();
    assert(access_op && optical_destination == banks[1]);
    unsigned before = requests;
    assert(mcd_video_workspace_save(actors + 2) == MCD_OK);
    assert(mcd_video_source_read(0, SECTOR, output + 2) == MCD_ERR_BUSY);
    assert(mcd_video_source_close() == MCD_ERR_BUSY);
    finish_workspace(true);
    assert(access_op && optical_destination == banks[1] && requests == before);
    assert(mcd_video_source_active());
    check_backup();
    check_first_ready_bank();

    memset(actors + 2, 0x72, READ_BYTES);
    assert(mcd_video_workspace_restore(actors + 2) == MCD_OK);
    finish_workspace(false);
    assert(access_op && optical_destination == banks[1] && requests == before);
    assert(mcd_video_source_active());
    check_actors();
    check_first_ready_bank();
    complete_optical(CDROM_RESULT_OK);
    read_at(BANK_BYTES - READ_BYTES / 2, READ_BYTES);
    close_source();
}

static void test_workspace_validation(void)
{
    fill_actors();
    assert(mcd_video_workspace_restore(actors + 2) == MCD_ERR_NOT_READY);
    assert(mcd_video_workspace_save(0) == MCD_ERR_ARGUMENT);
    assert(mcd_video_workspace_save(actors + 1) == MCD_ERR_ARGUMENT);
    assert(!mcd_video_source_pending() && !mcd_video_workspace_saved());
    /* A legacy optical operation cannot be displaced by SAVE/RESTORE. */
    access_op = 1;
    assert(mcd_video_workspace_save(actors + 2) == MCD_ERR_BUSY);
    assert(mcd_video_workspace_restore(actors + 2) == MCD_ERR_BUSY);
    assert(access_op == 1 && requests == 0);
    access_op = 0;
    assert(mcd_video_workspace_save(actors + 2) == MCD_OK);
    assert(mcd_video_workspace_save(actors + 2) == MCD_ERR_BUSY);
    assert(mcd_video_workspace_restore(actors + 2) == MCD_ERR_BUSY);
    finish_workspace(true);
    assert(mcd_video_workspace_restore(0) == MCD_ERR_ARGUMENT);
    assert(mcd_video_workspace_restore(actors + 1) == MCD_ERR_ARGUMENT);
    assert(!mcd_video_source_pending() && mcd_video_workspace_saved());
    check_backup();
    assert(mcd_video_workspace_restore(actors + 2) == MCD_OK);
    assert(mcd_video_workspace_save(actors + 2) == MCD_ERR_BUSY);
    assert(mcd_video_workspace_restore(actors + 2) == MCD_ERR_BUSY);
    finish_workspace(false);
    check_actors();
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "open-prefetch")) test_open_prefetch();
    else if (!strcmp(argv[1], "cross-bank")) test_cross_bank();
    else if (!strcmp(argv[1], "overlap-eviction")) test_overlap_eviction();
    else if (!strcmp(argv[1], "validation")) test_validation();
    else if (!strcmp(argv[1], "rounded-tail")) test_rounded_tail();
    else if (!strcmp(argv[1], "close-prefetch")) test_close_prefetch();
    else if (!strcmp(argv[1], "open-error")) test_open_error();
    else if (!strcmp(argv[1], "prefetch-error")) test_prefetch_error();
    else if (!strcmp(argv[1], "timeout-wrap")) test_timeout_wrap();
    else if (!strcmp(argv[1], "workspace-cycle")) test_workspace_cycle();
    else if (!strcmp(argv[1], "workspace-prefetch")) test_workspace_prefetch();
    else if (!strcmp(argv[1], "workspace-validation")) test_workspace_validation();
    else assert(!"unknown scenario");
    printf("video source: %s passed\n", argv[1]);
    return 0;
}
