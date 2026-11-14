#ifndef GK3HD_PACKET_WRITER_H
#define GK3HD_PACKET_WRITER_H

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "ring_buffer.h"

#define GK3HD_PACKET_HEADER_SIZE 8u
#if defined(HEADER_SIZE) && HEADER_SIZE != GK3HD_PACKET_HEADER_SIZE
#error "Vortek packet header size changed"
#endif

/* Vortek serializes producers already. Keep the established SPSC ring and
 * wire encoding, but expose a small request only after its whole body exists.
 * The caller retains the original split/socket path for oversized packets. */
static inline void gk3hdCopyPacketBytes(RingBuffer* ring, uint32_t tail,
                                       const void* data, uint32_t size) {
    uint32_t offset = tail & (ring->bufferSize - 1);
    uint32_t first = ring->bufferSize - offset;
    if (first > size) first = size;
    if (first) memcpy((char*)ring->buffer + offset, data, first);
    if (size > first) memcpy(ring->buffer, (const char*)data + first, size - first);
}

static inline bool gk3hdWritePacket(RingBuffer* ring, const void* header,
                                   const void* data, uint32_t size) {
    if (ring->bufferSize < GK3HD_PACKET_HEADER_SIZE ||
        size > ring->bufferSize - GK3HD_PACKET_HEADER_SIZE ||
        (size && !data)) return false;
    if (!RingBuffer_waitForWrite(ring, GK3HD_PACKET_HEADER_SIZE + size)) return false;
    uint32_t tail = RingBuffer_getTail(ring);
    gk3hdCopyPacketBytes(ring, tail, header, GK3HD_PACKET_HEADER_SIZE);
    if (size) gk3hdCopyPacketBytes(ring, tail + GK3HD_PACKET_HEADER_SIZE, data, size);
    RingBuffer_setTail(ring, tail + GK3HD_PACKET_HEADER_SIZE + size);
    return true;
}

#endif
