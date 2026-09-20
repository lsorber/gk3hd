# Patch architecture

Every registry-visible patch owns one player-facing engine policy. A public
patch may coordinate multiple internal feature compilers when GK3 exposes only
one safe hook, but sharing a hook is not permission to combine unrelated
behavior in one compiler.

## Module boundaries

- A module at `gk3hd.patch.definitions` owns an independently selectable engine policy,
  its injected runtime section, and every hook used only by that policy.
- `runtime2d` is the internal implementation of `scale_fixed_interfaces`. Its
  feature compilers own one visual domain each. The facade is the sole writer
  of shared final-blitter, pointer, cursor, and lifetime hooks; it contains no
  screen-specific rendering strategy itself.
- Cross-patch runtime communication uses a typed, immutable ABI. A consumer
  never reconstructs another patch's address from a section name plus a
  private numeric offset.
- A shared low-level engine hook has one dispatcher. Feature policies register
  with that dispatcher instead of stacking redirects at the same address.
- Diagnostics are bounded state published by the behavior that owns it. A
  temporary RCA probe must not become a permanent rendering dependency.

## Compiler docstring contract

Every public compiler and internal feature compiler uses these sections in
this order:

1. **Outcome** — one sentence describing the player-visible result.
2. **Before** — the concrete stock failure or legacy assumption.
3. **After** — the invariant provided by the patch.
4. **Strategy** — the hooks, coordinate domains, lifetime, and failure policy
   needed to understand the implementation.
5. **Boundaries** — behavior deliberately left unchanged and the owner of any
   adjacent policy.

The sections describe observable behavior and ownership, not implementation
history. Output-resolution examples may illustrate an affine, but control flow
must be expressed in live dimensions or authored resource dimensions rather
than named HD/UHD modes.

## Verification contract

Each binary compiler must:

1. recognize every pristine mutation site before writing;
2. build deterministic payloads from the selected executable profile;
3. reject overlapping or oversized payloads before installation;
4. verify all redirects, exported ABI state, and payload bytes afterward; and
5. restore the original executable exactly through the operation manifest.

Structural refactors preserve emitted bytes until a deliberate behavior change
has its own focused runtime evidence. This lets source ownership improve
without silently invalidating the visual baseline.
