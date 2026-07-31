# Merge new built-in stations into existing installs

**Date:** 2026-07-31
**Status:** Approved

## Problem

Both platforms treat the built-in station list as a *seed*, not a source of
truth. `StationStore.load()` returns `Station.builtIn` only when no
`stations.json` exists; `load_stations()` writes `BUILTIN_STATIONS` only when
the file is missing. Once a user has run RadioBar even once, stations added to
the built-in list in a later release never reach them.

Adding WXPN (commit `c2a78a9`) surfaced this: the entries ship, but no existing
install shows them.

## Rule

On load, append every built-in whose **name** is not already in the saved list,
compared case-insensitively. Preserve the user's entries and their order; new
built-ins land at the end. Write the file back only if something was added.

### Match on name, not URL

`find_station` already treats name as the lookup key (`linux/radiobar`, using
`.lower()`), so `radiobar play "<name>"` returns the first name match. Matching
on `streamURL` instead would let a URL change upstream produce two stations
called "BBC Radio 6 Music" and silently break that lookup. Stream URLs do drift
— macOS and Linux currently carry different BBC 6 Music URLs — while names are
stable. So: name is identity.

### Deliberate consequences

- **A built-in removed by hand comes back.** Accepted. Neither platform has a
  delete affordance (macOS offers only "Add Station…"; Linux has no station
  commands), so a missing built-in is far more likely to be one that postdates
  the install than a deliberate removal. Avoiding this would require tracking
  which built-ins had already been offered; rejected as not worth the state.
- **Add-only, never edit.** A built-in whose URL changed upstream is *not*
  updated in a saved list. Users who fixed a URL locally keep their fix.
- **Corrupt files stay untouched.** A file that fails to parse, or parses to
  the wrong shape, still falls back to built-ins in memory and is left on disk
  as-is, exactly as today. Rewriting it would destroy something the user may
  want to repair.

## macOS — `Sources/Station.swift`

```swift
/// Built-ins whose name isn't already present, appended in built-in order.
/// Name-matched case-insensitively so a rename can't produce a duplicate.
static func merging(_ builtIn: [Station], into saved: [Station]) -> [Station] {
    let have = Set(saved.map { $0.name.lowercased() })
    return saved + builtIn.filter { !have.contains($0.name.lowercased()) }
}

static func load() -> [Station] {
    guard let url = storeURL else { return Station.builtIn }
    guard let data = try? Data(contentsOf: url),
          let saved = try? JSONDecoder().decode([Station].self, from: data)
    else { return Station.builtIn }          // corrupt: leave the file alone
    let merged = merging(Station.builtIn, into: saved)
    // Sound only because merge is append-only: if it ever edits in place,
    // count stops changing when content does and this silently stops writing.
    if merged.count != saved.count { save(merged) }
    return merged
}
```

`merging` is pure and disk-free — that is what makes it testable, and it keeps
`load()` a thin I/O wrapper. An empty `[]` file heals into the full built-in
list. `save()` already swallows write errors via `try?`, so an unwritable file
still yields the merged list in memory.

## Linux — `linux/radiobar`

Mirror the rule in `load_stations()`, using `.lower()` so the comparison
matches `find_station` exactly. Extract the decision as a pure
`merge_builtins(saved)` for the same testability reason. Wrap the write in
`try/except OSError` and report to stderr on failure, matching how the existing
seed path degrades.

## Testing

Tests first. Cases, applied to both platforms:

| Case | Expectation |
|------|-------------|
| Saved list missing a new built-in | Appended, at the end |
| Saved list already complete | Returned unchanged, file **not** rewritten |
| Built-in present under different case | Not duplicated |
| User's custom station present | Preserved, order intact |
| Empty `[]` file | Heals to the full built-in list |
| Unwritable file | Merged list still returned |
| Corrupt / wrong-shape file | Built-ins in memory, file unchanged on disk |

`linux/test_radiobar.py` `test_valid_file_is_loaded` asserts the saved file is
returned verbatim — the exact contract being replaced. Rewrite it as a merge
assertion rather than delete it.

macOS has no `Station` test binary. Add `Tests/StationMergeTests.swift` and a
`make test` line; `Station.swift` is Foundation-only, so it compiles standalone
without AppKit.

## Docs

Both READMEs gain a line noting that new built-ins arrive automatically.
`linux/README.md` currently implies `stations.json` is the user's alone; amend
it to say RadioBar appends new built-ins on load.

## Out of scope (YAGNI)

- Tracking which built-ins have already been offered, so hand-removals stick.
- Updating a saved station when its built-in URL changes.
- A delete-station affordance on either platform.
- Inserting new built-ins at their canonical position rather than appending.
