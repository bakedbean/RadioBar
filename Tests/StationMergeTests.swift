import Foundation

// Covers StationStore.merging — the pure decision behind merge-on-load.
// The file-level behaviour it gates (rewrite only when something was added,
// unwritable file, corrupt file) is exercised on the Linux side, where
// RADIOBAR_CONFIG_DIR lets a test redirect the store to a tmpdir. Doing the
// same here would mean writing to the real Application Support directory.
@main
struct StationMergeTests {
    static func main() {
        var failures = 0
        func check(_ name: String, _ got: [String], _ want: [String]) {
            let ok = got == want
            print(ok ? "✓ \(name)" : "✗ \(name): got \(got), want \(want)")
            if !ok { failures += 1 }
        }

        func station(_ name: String) -> Station {
            Station(name: name, streamURL: "https://example.test/\(name)",
                    genre: "Test", websiteURL: nil)
        }
        let builtIn = [station("Alpha"), station("Beta"), station("Gamma")]
        func names(_ stations: [Station]) -> [String] { stations.map { $0.name } }

        check("appends a built-in the saved list is missing",
              names(StationMergeTests.merged(builtIn, [station("Alpha"), station("Beta")])),
              ["Alpha", "Beta", "Gamma"])

        check("complete list is returned unchanged",
              names(StationMergeTests.merged(builtIn, builtIn)),
              ["Alpha", "Beta", "Gamma"])

        check("case-insensitive match does not duplicate",
              names(StationMergeTests.merged(builtIn, [station("alpha"), station("BETA"), station("GaMmA")])),
              ["alpha", "BETA", "GaMmA"])

        check("user's own stations and their order survive",
              names(StationMergeTests.merged(builtIn, [station("Mine"), station("Beta")])),
              ["Mine", "Beta", "Alpha", "Gamma"])

        check("empty saved list heals to the full built-in list",
              names(StationMergeTests.merged(builtIn, [])),
              ["Alpha", "Beta", "Gamma"])

        check("a renamed built-in is re-added under its canonical name",
              names(StationMergeTests.merged(builtIn, [station("Alpha But Renamed")])),
              ["Alpha But Renamed", "Alpha", "Beta", "Gamma"])

        // Guards the write-gate in load(): it writes iff the count grew, which
        // is only equivalent to "content changed" while merge is append-only.
        let unchanged = StationMergeTests.merged(builtIn, builtIn)
        let grew = StationMergeTests.merged(builtIn, [station("Alpha")])
        check("count is the write signal",
              ["\(unchanged.count == builtIn.count)", "\(grew.count > 1)"],
              ["true", "true"])

        print(failures == 0 ? "\nAll tests passed" : "\n\(failures) test(s) failed")
        exit(failures == 0 ? 0 : 1)
    }

    static func merged(_ builtIn: [Station], _ saved: [Station]) -> [Station] {
        StationStore.merging(builtIn, into: saved)
    }
}
