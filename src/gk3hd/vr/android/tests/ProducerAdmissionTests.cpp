#include "ProducerAdmission.h"
#include <cstdio>
#include <stdexcept>

static unsigned checks;
static void require(bool condition, const char* message) {
    ++checks;
    if (!condition) throw std::runtime_error(message);
}

int main() {
    try {
        gk3hd::ProducerAdmission queue;
        queue.reset(4);
        require(!queue.pending(1) && !queue.pending(2), "Fresh session has no earlier work");
        queue.submitted(0);
        require(queue.pending(1) == 0u && !queue.pending(2), "First submission has no predecessor");
        queue.submitted(1);
        require(queue.pending(1) == 1u && queue.pending(2) == 0u, "Admission follows submission order");
        require(!queue.pending(0), "Disabled admission does not select a fence");
        require(queue.pending(2) == 0u, "Querying does not release or acknowledge work");
        queue.retired(0);
        require(!queue.pending(2), "Retired predecessor cannot block admission");
        queue.submitted(0);
        require(queue.pending(1) == 0u && queue.pending(2) == 1u, "Reused image has a new identity");
        queue.retired(1);
        require(!queue.pending(2), "Retirement never selects a newer fence use");
        queue.submitted(0);
        require(!queue.pending(2) && queue.pending(1) == 0u,
                "Consecutive reuse does not wait on the newest work as its own predecessor");

        queue.reset(1);
        require(!queue.pending(1) && !queue.pending(2), "Recreation discards old image references");
        queue.submitted(0);
        require(queue.pending(1) == 0u && !queue.pending(2), "New device starts a separate history");
        bool rejected = false;
        try { queue.submitted(1); } catch (const std::out_of_range&) { rejected = true; }
        require(rejected && queue.pending(1) == 0u, "Invalid image cannot corrupt valid history");
        rejected = false;
        try { queue.pending(99); } catch (const std::out_of_range&) { rejected = true; }
        require(rejected, "Unbounded history request is rejected");
        queue.reset(0);
        require(!queue.pending(1), "Retired device has no fence to wait on");

        for (unsigned capacity : {3u, 4u, 6u}) {
            queue.reset(capacity);
            for (unsigned frame = 0; frame < capacity * 3; ++frame) {
                unsigned image = frame % capacity;
                queue.retired(image);
                queue.submitted(image);
                require(queue.pending(1) == image, "Newest successful submission stays identifiable");
                if (frame) require(queue.pending(2) == (frame - 1) % capacity,
                                   "Older submission survives unrelated image reuse");
            }
            queue.reset(capacity);
            require(!queue.pending(1) && !queue.pending(2), "Resize invalidates all prior submissions");
        }
        std::printf("Producer admission: %u behavior checks passed\n", checks);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Producer admission: %s\n", error.what());
        return 1;
    }
}
