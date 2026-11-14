#include "session_test_runtime.h"
#include <future>
#include <iostream>
#include <limits>

using gk3hd::standalone::openxr::PackedSession;
using namespace gk3hd::standalone::openxr::testing;
namespace {
void requestedExtent() {
  Fake fake;
  fake.limit = fake.graphicsLimit = 8192;
  rejects([&] { fake.make({3008, 0}); });
  rejects([&] { fake.make({3201, 3264}); });
  rejects([&] { fake.make({3008, 3501}); });
  fake.limit = 6015;
  rejects([&] { fake.make({3008, 3264}); });
  fake.limit = 8192;
  fake.graphicsLimit = 6015;
  rejects([&] { fake.make({3008, 3264}); });
  require(fake.creates == 0, "Unsupported eye extent allocated a session");
  fake.graphicsLimit = 8192;
  fake.expectedExtent = {3008, 3264};
  auto session = fake.make(fake.expectedExtent);
  require(session.eyeWidth() == 3008 && session.eyeHeight() == 3264,
          "Native session lost the requested eye extent");
  ready(fake);
  const auto sample = *session.begin();
  session.acquire(0);
  session.release();
  require(session.endRendered(sample.serial), "Requested-size eye layers were not submitted");
  require(fake.projected[0].fov.angleLeft == sample.eyes[0].fov.angleLeft &&
              fake.projected[1].pose.position.x == sample.eyes[1].pose.position.x,
          "Requested extent changed runtime optics");
  session.close();
}

void supplementalRetention() {
  Fake fake;auto session=fake.make();ready(fake);
  const auto anchor=*session.begin();session.end(nullptr);
  const auto display=*session.begin();
  auto located=anchor;located.serial=0;located.time+=1'000'000;
  for(unsigned i=0;i<2;++i) {
    const float yaw=i==0?.08f:-.05f;
    located.eyes[i].pose.orientation={0,std::sin(yaw/2),0,std::cos(yaw/2)};
    located.eyes[i].pose.position.x+=float(i+1)*.007f;
    located.eyes[i].fov.angleLeft-=float(i+1)*.03f;
    located.eyes[i].fov.angleUp-=float(i+1)*.02f;
  }
  const auto expected=located;
  const auto beforeFrames=fake.frames,beforeAcquire=fake.acquires,beforeWait=fake.waits;
  auto retained=session.retainLocated(anchor.serial,located);
  require(retained&&retained->serial!=anchor.serial&&retained->serial!=display.serial&&
          retained->time==located.time&&retained->epoch==located.epoch,
          "Supplemental retention reused a frame identity or changed prediction time");
  require(fake.frames==beforeFrames&&fake.acquires==beforeAcquire&&fake.waits==beforeWait,
          "Retaining a pose performed frame pacing or image acquisition");
  located.eyes[0].pose.position.x+=20;
  auto worker=std::async(std::launch::async,[&] {
    rejects([&]{session.retainLocated(anchor.serial,expected);});
  });worker.get();
  auto invalid=expected;invalid.time=display.time+1;
  require(!session.retainLocated(anchor.serial,invalid),"Future projection target accepted");
  invalid=expected;invalid.flags=0;
  require(!session.retainLocated(anchor.serial,invalid),"Unavailable tracking retained");
  invalid=expected;invalid.eyes[1].pose.orientation.w=0;
  require(!session.retainLocated(anchor.serial,invalid),"Malformed supplemental eye retained");
  invalid=expected;invalid.epoch++;
  require(!session.retainLocated(anchor.serial,invalid),"Wrong coordinate epoch retained");
  invalid=expected;invalid.period++;
  require(!session.retainLocated(anchor.serial,invalid),"Unknown prediction anchor period accepted");
  invalid=expected;invalid.serial=anchor.serial;
  rejects([&]{session.retainLocated(anchor.serial,invalid);});
  rejects([&]{session.retainLocated(std::numeric_limits<uint64_t>::max(),expected);});
  auto unshown=expected;unshown.time++;
  const auto unseen=*session.retainLocated(anchor.serial,unshown);
  session.acquire(0);session.release();
  require(session.endRendered(retained->serial),"Supplemental native layer not submitted");
  for(unsigned i=0;i<2;++i) {
    const auto &p=fake.projected[i].pose,&q=expected.eyes[i].pose;
    const auto &f=fake.projected[i].fov,&g=expected.eyes[i].fov;
    require(p.position.x==q.position.x&&p.position.y==q.position.y&&p.position.z==q.position.z&&
            p.orientation.x==q.orientation.x&&p.orientation.y==q.orientation.y&&
            p.orientation.z==q.orientation.z&&p.orientation.w==q.orientation.w&&
            f.angleLeft==g.angleLeft&&f.angleRight==g.angleRight&&
            f.angleUp==g.angleUp&&f.angleDown==g.angleDown,
            "Native projection changed the exact original supplemental eye/FOV");
  }
  require(fake.lastDisplay==display.time,"Supplemental prediction replaced native display timing");
  rejects([&]{session.retainLocated(anchor.serial,expected);});
  // Leave a newer ordinary frame at the deque front, with an expired unseen
  // supplemental sample behind it. First-use expiry must not depend on order.
  fake.time=unseen.time+250'000'001-11'111'111;
  session.begin();session.acquire(0);session.release();
  require(!session.endRendered(unseen.serial),"Unseen expired supplemental image was presented");
  session.begin();session.acquire(0);session.release();
  require(session.endRendered(retained->serial),"Already presented exact pose was not retained");
  session.begin();require(!session.retainLocated(anchor.serial,expected),"Expired anchor reimported");
  session.end(nullptr);
  const auto beforeFocus=*session.begin();session.end(nullptr);
  auto oldFocus=beforeFocus;oldFocus.serial=0;oldFocus.time+=1'000'000;
  fake.events.push_back(XR_SESSION_STATE_VISIBLE);
  session.begin();session.end(nullptr);fake.events.push_back(XR_SESSION_STATE_FOCUSED);
  const auto fresh=*session.begin();
  auto newSample=fresh;newSample.serial=0;
  require(!session.retainLocated(beforeFocus.serial,oldFocus),"Withdrawn native anchor revived");
  require(session.retainLocated(fresh.serial,newSample).has_value(),"Current native anchor did not recover");
  session.end(nullptr);session.close();
}
void supplementalWithdrawal() {
  for(unsigned mode=0;mode<5;++mode) {
    Fake fake;auto session=fake.make();ready(fake);
    const auto before=*session.begin();auto located=before;located.serial=0;
    const auto generation=session.inputGeneration();
    session.end(nullptr);
    if(mode==0) {
      fake.flags=0;session.begin();session.end(nullptr);fake.flags=15;
    } else if(mode==1) {
      fake.render=false;session.begin();session.end(nullptr);fake.render=true;
    } else if(mode==2) {
      recenter(fake,fake.time+11'111'111);
    } else if(mode==3) {
      session.resumed(false);session.resumed(true);
    } else fake.eventsLost=true;
    const auto after=*session.begin();
    require(session.inputGeneration()!=generation,"Native withdrawal retained the old input generation");
    require(!session.retainLocated(before.serial,located),
            "Tracking/render/reference/pause/event withdrawal revived an old anchor");
    located=after;located.serial=0;
    require(session.retainLocated(after.serial,located).has_value(),
            "Fresh native anchor did not recover after withdrawal");
    session.end(nullptr);session.close();
  }
}
} // namespace
int main() {
  try {
    requestedExtent();
    supplementalRetention();
    supplementalWithdrawal();
    {
      Fake fake;auto session = fake.make();ready(fake);
      const auto before = *session.begin();session.acquire(0);session.release();session.end(&before);
      recenter(fake, fake.time + 2 * 11'111'111);
      const auto inFlight = *session.begin();
      require(inFlight.epoch == before.epoch, "Future recenter discarded images too early");
      require(session.referenceDeadline()==fake.time+11'111'111,
              "Earliest native reference deadline was not available to sampling");
      session.acquire(0);session.release();session.end(&before);
      const auto changed = *session.begin();
      require(!session.referenceDeadline(),"Applied reference deadline was not retired");
      require(changed.epoch != before.epoch, "Recenter boundary retained the old coordinate basis");
      session.acquire(0);session.release();rejects([&] {session.end(&before);});
      session.endRendered(changed.serial);
      recenter(fake, fake.time, XR_REFERENCE_SPACE_TYPE_STAGE);
      recenter(fake, fake.time, XR_REFERENCE_SPACE_TYPE_LOCAL, handle<XrSession>(99));
      const auto unaffected = *session.begin();
      require(unaffected.epoch == changed.epoch, "Unrelated reference-space event changed native LOCAL");
      session.acquire(0);session.release();session.end(&changed);
      fake.eventsLost = true;
      const auto recovered = *session.begin();
      require(recovered.epoch != changed.epoch, "Lost events retained an unproven coordinate basis");
      session.acquire(0);session.release();rejects([&] {session.end(&changed);});
      session.endRendered(recovered.serial);
      recenter(fake, fake.time + 3 * 11'111'111);
      recenter(fake, fake.time + 11'111'111);
      const auto firstChange = *session.begin();
      require(firstChange.epoch != recovered.epoch, "Out-of-order reference changes were not time ordered");
      session.end(nullptr);
      const auto between = *session.begin();
      require(between.epoch == firstChange.epoch, "Reference basis changed before the second boundary");
      session.end(nullptr);
      const auto finalChange = *session.begin();
      require(finalChange.epoch != between.epoch, "Later reference-space boundary was lost");
      session.acquire(0);session.release();session.endRendered(finalChange.serial);session.close();
    }
    {
      Fake fake;
      auto session = fake.make();
      require(!session.begin(), "Unready session rendered");
      ready(fake);
      auto first = *session.begin();
      require(first.focused && first.flags == 15, "Actual focus/validity lost");
      require(session.eyeWidth() == 120 && session.eyeHeight() == 120 &&
                  session.imageCount() == 3,
              "Runtime recommendations lost");
      require(session.acquire(0) == 1u, "Wrong owned image");
      session.release();
      session.endRendered(first.serial);
      auto second = *session.begin();
      require(second.time > first.time, "Native time did not advance");
      session.acquire(0);
      session.release();
      session.end(&first);
      require(fake.renderedX == first.eyes[0].pose.position.x &&
                  fake.lastDisplay == second.time,
              "Old pixels relabelled as latest view");
      auto third = *session.begin();
      session.acquire(0);
      session.release();
      third.eyes[0].pose.position.x += 1;
      rejects([&] { session.end(&third); });
      session.end(nullptr);
      session.close();
      require(fake.retirement == std::vector<int>({1, 2, 3, 4}),
              "Native retirement order incorrect");
    }
    {
      Fake fake;
      auto session = fake.make();
      ready(fake);
      session.begin();
      fake.timeout = true;
      require(!session.acquire(), "Timed-out image became writable");
      require(fake.lastImageTimeout == 5'000'000'000, "Native image wait was not bounded");
      rejects([&] { session.release(); });
      session.end(nullptr);
      require(fake.acquires == 1 && fake.releases == 0 && fake.layers == 0,
              "Timeout surrendered or reacquired an unwaited image");
      auto sample = *session.begin();
      fake.timeout = false;
      require(session.acquire() == 1u && fake.acquires == 1,
              "Pending image identity was lost");
      session.release();
      session.end(&sample);
      session.close();
    }
    {
      Fake fake;
      auto session = fake.make();
      ready(fake);
      session.begin();
      fake.timeout = true;
      require(!session.acquire(), "Unavailable native image became writable");
      session.close();
      require(fake.releases == 0 && fake.layers == 0 &&
                  fake.retirement == std::vector<int>({1, 2, 3, 4}),
              "Shutdown released or presented an unwaited image");
    }
    {
      Fake fake;
      auto session = fake.make();
      session.resumed(false);
      fake.events = {XR_SESSION_STATE_READY};
      require(!session.begin() && fake.begins == 0,
              "Paused READY started a session");
      session.resumed(true);
      require(fake.begins == 1, "Consumed READY was lost across resume");
      fake.flags = 0;
      auto sample = *session.begin();
      require(sample.flags == 0, "Missing head tracking promoted");
      rejects([&] { session.acquire(0); });
      session.end(nullptr);
      fake.flags = 3;
      fake.render = false;
      sample = *session.begin();
      require(sample.flags == 3 && !sample.shouldRender,
              "Runtime validity/render decision changed");
      rejects([&] { session.acquire(0); });
      session.end(nullptr);
      fake.events = {XR_SESSION_STATE_STOPPING};
      require(!session.begin() && fake.ends == 1,
              "Native STOPPING not honored");
      session.close();
    }
    {
      Fake fake;
      auto session = fake.make();
      ready(fake);
      auto old = *session.begin();
      session.end(nullptr);
      session.resumed(false);
      session.resumed(true);
      session.begin();
      session.acquire(0);
      session.release();
      rejects([&] { session.end(&old); });
      session.end(nullptr);
      fake.loss = true;
      require(!session.begin() &&
                  session.endReason() == PackedSession::EndReason::InstanceLost,
              "Instance loss still rendered or looked like a normal exit");
      session.close();
    }
    for (const auto &terminal : {
             std::pair{XR_SESSION_STATE_EXITING, PackedSession::EndReason::Exit},
             std::pair{XR_SESSION_STATE_LOSS_PENDING, PackedSession::EndReason::SessionLost}}) {
      Fake fake;
      auto session = fake.make();
      ready(fake);
      require(bool(session.begin()), "Session did not start");
      session.end(nullptr);
      fake.events = {terminal.first, XR_SESSION_STATE_READY};
      require(!session.begin() && !session.begin() && session.endReason() == terminal.second,
              "Terminal XR state was overridden or not reported");
      require(fake.begins == 1, "Terminal XR session restarted");
      session.close();
    }
    for (const auto &boundary : {
             std::pair{&Fake::waitFrameResult, 0u},
             std::pair{&Fake::beginFrameResult, 1u},
             std::pair{&Fake::locateResult, 1u}}) {
      for (const auto &loss : {
               std::pair{XR_SESSION_LOSS_PENDING, PackedSession::EndReason::SessionLost},
               std::pair{XR_ERROR_SESSION_LOST, PackedSession::EndReason::SessionLost},
               std::pair{XR_ERROR_INSTANCE_LOST, PackedSession::EndReason::InstanceLost}}) {
        Fake fake;
        auto session = fake.make();
        ready(fake);
        fake.*boundary.first = loss.first;
        require(!session.begin() && session.endReason() == loss.second,
                "A frame call reporting runtime loss published stereo pose data");
        require(fake.frames == (XR_SUCCEEDED(loss.first) ? boundary.second : 0u) && !fake.layers,
                "Loss did not retire only the begun frame without layers");
        session.close();
      }
    }
    {
      Fake fake;
      auto session = fake.make();
      ready(fake);
      const auto frame = *session.begin();
      session.acquire(0);
      session.release();
      fake.endResult = XR_SESSION_LOSS_PENDING;
      require(!session.endRendered(frame.serial) && fake.frames == 1 && !session.begin() &&
                  session.endReason() == PackedSession::EndReason::SessionLost,
              "Session loss during frame submission was counted as a delivered image");
      session.close();
    }
    {
      Fake fake;
      fake.limit = 200;
      rejects([&] { auto session = fake.make(); });
      require(fake.creates == 0,
              "Unsupported packed extent silently reduced quality");
    }
    {
      Fake fake;
      auto session = fake.make();
      ready(fake);
      auto old = *session.begin();
      session.end(nullptr);
      fake.time += 300'000'000;
      session.begin();
      session.acquire(0);
      session.release();
      rejects([&] { session.end(&old); });
      session.end(nullptr);
      fake.flags = 0;
      session.begin();
      session.end(nullptr);
      fake.flags = 15;
      session.begin();
      session.acquire(0);
      session.release();
      rejects([&] { session.end(&old); });
      session.end(nullptr);
      session.close();
    }
    {
      Fake fake;auto session=fake.make();ready(fake);
      const auto old=*session.begin();session.end(nullptr);
      fake.time+=300'000'000;
      auto fresh=*session.begin();session.acquire(0);session.release();
      require(!session.endRendered(old.serial),"Expired pixels were counted as a stereo submission");
      require(fake.layers==0,"Expired native image was presented with new eyes");
      fresh=*session.begin();session.acquire(0);session.release();
      require(session.endRendered(fresh.serial),"Accepted stereo layer was not reported");
      require(fake.layers==1,"Fresh image did not recover after retiring stale pixels");
      fresh=*session.begin();session.acquire(0);session.release();
      rejects([&] {session.endRendered(fresh.serial+1);});session.end(nullptr);
      session.begin();
      require(!session.endRendered(0),"An empty frame was counted as stereo");
      session.close();
    }
    {
      Fake fake;
      auto session = fake.make();
      ready(fake);
      session.begin();
      session.acquire(0);
      session.close();
      require(fake.releases == 1 && fake.layers == 0 && fake.frames == 1,
              "Closing a writable image did not retire the unfinished frame");
    }
    {
      Fake fake;auto session=fake.make();ready(fake);
      const auto original=*session.begin();session.acquire(0);session.release();
      require(session.endRendered(original.serial),"Initial immutable image was not submitted");
      fake.time+=1'000'000'000;
      const auto later=*session.begin();session.acquire(0);session.release();
      require(session.endRendered(original.serial),"Known image lost its pose after history expiry");
      require(fake.renderedX==original.eyes[0].pose.position.x&&fake.lastDisplay==later.time,
              "Held image was relabelled with current eyes or time");
      auto corrupt=original;corrupt.eyes[1].fov.angleRight+=0.1f;
      session.begin();session.acquire(0);session.release();
      rejects([&]{session.end(&corrupt);});session.end(nullptr);
      fake.events.push_back(XR_SESSION_STATE_VISIBLE);
      session.begin();session.acquire(0);session.release();
      require(!session.endRendered(original.serial),"Focus change retained old image ownership");
      fake.events.push_back(XR_SESSION_STATE_FOCUSED);
      const auto recovered=*session.begin();session.acquire(0);session.release();
      require(session.endRendered(recovered.serial),"Fresh image did not recover after focus change");
      fake.flags=0;session.begin();session.end(nullptr);fake.flags=15;
      session.begin();session.acquire(0);session.release();
      require(!session.endRendered(recovered.serial),"Tracking loss retained a pinned sample");
      const auto next=*session.begin();session.acquire(0);session.release();session.endRendered(next.serial);
      fake.render=false;session.begin();session.end(nullptr);fake.render=true;
      session.begin();session.acquire(0);session.release();
      require(!session.endRendered(next.serial),"Suppressed native render retained a pinned sample");
      session.close();
    }
    {
      Fake fake;
      auto session = fake.make();
      ready(fake);
      const auto submitFresh = [&] {
        const auto sample = *session.begin();
        session.acquire(0);
        session.release();
        require(session.endRendered(sample.serial), "Fresh image did not submit");
        return sample;
      };
      const auto first = *session.begin();
      require(!session.reusableSerial(), "First frame advertised a released image");
      rejects([&] { session.endRendered(first.serial, true); });
      session.acquire(0);
      session.release();
      require(session.endRendered(first.serial), "First image did not submit");
      for (unsigned i = 0; i < 300; ++i) {
        const auto now = *session.begin();
        require(session.reusableSerial() == first.serial, "Released image identity changed");
        require(session.endRendered(first.serial, true), "Known released pixels did not repeat");
        require(fake.renderedX == first.eyes[0].pose.position.x && fake.lastDisplay == now.time,
                "Repeated pixels changed pose or display time");
      }
      require(fake.acquires == 1 && fake.waits == 1 && fake.releases == 1 && fake.flushes == 1,
              "Repeating unchanged content issued GPU ownership or flush work");
      const auto next = *session.begin();
      rejects([&] { session.endRendered(next.serial, true); });
      auto changed = first;
      changed.eyes[1].fov.angleLeft -= 0.01f;
      rejects([&] { session.end(&changed, true); });
      require(session.endRendered(first.serial, true), "Rejected relabeling damaged owned content");
      session.begin();
      session.acquire(0);
      require(!session.reusableSerial(), "Acquisition left previous pixels reusable");
      rejects([&] { session.endRendered(first.serial, true); });
      session.release();
      rejects([&] { session.endRendered(first.serial, true); });
      session.endRendered(next.serial);
      session.begin();
      session.end(nullptr);
      session.begin();
      rejects([&] { session.endRendered(next.serial, true); });
      session.end(nullptr);

      const auto held = submitFresh();
      fake.events.push_back(XR_SESSION_STATE_VISIBLE);
      fake.events.push_back(XR_SESSION_STATE_FOCUSED);
      const auto resumed = *session.begin();
      require(resumed.focused && resumed.epoch == held.epoch && !session.reusableSerial(),
              "Focus round trip left released pixels reusable in the same epoch");
      session.acquire(0);
      session.release();
      require(session.endRendered(resumed.serial), "Focus round trip prevented fresh output");

      const auto recovered = submitFresh();
      fake.events.push_back(XR_SESSION_STATE_VISIBLE);
      session.begin();
      require(!session.endRendered(recovered.serial, true), "Focus loss repeated stale pixels");
      fake.events.push_back(XR_SESSION_STATE_FOCUSED);
      const auto focused = submitFresh();
      recenter(fake, fake.time);
      session.begin();
      require(!session.endRendered(focused.serial, true), "Reference change repeated old coordinates");
      const auto rebased = submitFresh();
      fake.flags = 0;
      session.begin();
      session.end(nullptr);
      fake.flags = 15;
      session.begin();
      require(!session.endRendered(rebased.serial, true), "Tracking loss revived released pixels");
      const auto tracked = submitFresh();
      fake.render = false;
      session.begin();
      session.end(nullptr);
      fake.render = true;
      session.begin();
      require(!session.endRendered(tracked.serial, true), "Suppressed render revived released pixels");
      const auto late = submitFresh();
      fake.timeout = true;
      session.begin();
      require(!session.acquire(0), "Timeout became writable");
      rejects([&] { session.endRendered(late.serial, true); });
      session.end(nullptr);
      fake.timeout = false;
      submitFresh();
      session.close();
      require(fake.retirement == std::vector<int>({1, 2, 3, 4}), "Repeat content changed retirement order");

      Fake failed;
      auto retry = failed.make();
      ready(failed);
      const auto owned = *retry.begin();
      retry.acquire(0);
      retry.release();
      require(retry.endRendered(owned.serial), "Runtime failure control did not submit");
      retry.begin();
      failed.failEnd = true;
      bool apiFailed = false;
      try {
        retry.endRendered(owned.serial, true);
      } catch (const std::runtime_error &) {
        apiFailed = true;
      }
      require(apiFailed, "Runtime submission error was hidden");
      failed.failEnd = false;
      retry.begin();
      rejects([&] { retry.endRendered(owned.serial, true); });
      retry.end(nullptr);
      retry.close();
    }
    std::cout
        << "Native session: recommendations, packed ownership, timeout "
           "retention, truthful old-view submission, pause/READY, "
           "tracking/focus/render withdrawal and ordered retirement passed\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
