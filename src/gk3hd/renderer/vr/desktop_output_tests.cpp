#include "desktop_output.h"
#include <stdexcept>
#include <thread>
#include <iostream>

static void expect(bool value) {
  if (!value) throw std::runtime_error("desktop output ownership invariant failed");
}
int main() {
  using gk3hd::vr::DesktopOutput;
  DesktopOutput desktop, standalone(true), otherDevice(true);
  desktop.acceptedWorld(desktop.begin(), 7, true);
  expect(!desktop.consume(7, true));
  expect(!standalone.consume(7, true));
  for (unsigned i = 0; i < 10000; ++i) {
    auto ticket = standalone.begin();
    standalone.acceptedWorld(ticket, 7, true);
    expect(!otherDevice.consume(7, true));
    expect(!standalone.consume(8, true));
    expect(standalone.consume(7, true));
    expect(!standalone.consume(7, true));
    ticket = standalone.begin();
    standalone.acceptedWorld(ticket, 7, true);
    standalone.invalidate();
    expect(!standalone.consume(7, true));
    ticket = standalone.begin();
    standalone.acceptedWorld(ticket, 7, false);
    expect(!standalone.consume(7, true));
    standalone.acceptedWorld(ticket, 7, true);
    expect(!standalone.consume(7, false));
    expect(!standalone.consume(7, true));
  }
  const auto stale = standalone.begin();
  standalone.invalidate();
  standalone.acceptedWorld(stale, 7, true);
  expect(!standalone.consume(7, true));
  standalone.acceptedWorld(standalone.begin(), 7, true);
  bool consumed[2]{};
  std::thread a([&] { consumed[0] = standalone.consume(7, true); });
  std::thread b([&] { consumed[1] = standalone.consume(7, true); });
  a.join(); b.join();
  expect(consumed[0] != consumed[1]);
  std::cout << "Desktop/standalone fallback, device isolation and single-consumer ownership pass\n";
}
