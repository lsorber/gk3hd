#pragma once

#include <array>
#include <cstdint>
#include <cstddef>
#include <limits>
#include <optional>
#include <stdexcept>
#include <vector>

namespace gk3hd {

// Submission identities, not fence ownership. The caller retains every native
// completion wait and invalidates an image only after its previous work retires.
class ProducerAdmission {
    struct Submission {
        uint32_t image{};
        uint64_t serial{};
    };
    std::vector<uint64_t> current_;
    std::array<Submission, 2> recent_{};
    uint64_t serial_{};

public:
    void reset(std::size_t images) {
        current_.assign(images, 0);
        recent_ = {};
    }

    void retired(uint32_t image) {
        current_.at(image) = 0;
    }

    void submitted(uint32_t image) {
        auto& current = current_.at(image);
        if (serial_ == std::numeric_limits<uint64_t>::max())
            throw std::overflow_error("Producer submission identity exhausted");
        current = ++serial_;
        recent_[1] = recent_[0];
        recent_[0] = {image, current};
    }

    // A reused fence belongs to newer work. Its older submission has already
    // retired, so an old reference must never wait on that newer fence use.
    std::optional<uint32_t> pending(unsigned limit) const {
        if (!limit) return std::nullopt;
        if (limit > recent_.size())
            throw std::out_of_range("Unsupported producer history depth");
        const auto& previous = recent_[limit - 1];
        if (!previous.serial || current_.at(previous.image) != previous.serial)
            return std::nullopt;
        return previous.image;
    }
};

} // namespace gk3hd
