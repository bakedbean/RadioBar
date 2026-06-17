import Foundation

// Reuses the app's real MetadataParser (Foundation-only) to dump live ICY
// StreamTitle values with timestamps, so we can see exactly what WERS sends
// for songs vs. taglines and how often real songs arrive.
@main
struct CaptureMetadata {
    static func main() {
        let defaultURL = "https://playerservices.streamtheworld.com/api/livestream-redirect/WERSFMAAC.aac"
        let urlString = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : defaultURL

        guard let url = URL(string: urlString) else {
            FileHandle.standardError.write(Data("Invalid URL: \(urlString)\n".utf8))
            exit(1)
        }

        let parser = MetadataParser()
        let formatter = ISO8601DateFormatter()

        parser.onTrackUpdate = { title in
            print("\(formatter.string(from: Date()))\t\(title ?? "<nil>")")
            fflush(stdout)
        }
        parser.onStationName = { name in
            print("# station: \(name ?? "<nil>")")
            fflush(stdout)
        }
        parser.onError = { msg in
            FileHandle.standardError.write(Data("# error: \(msg)\n".utf8))
        }

        print("# capturing \(url.absoluteString) — Ctrl-C to stop")
        fflush(stdout)
        parser.connect(to: url)
        RunLoop.main.run()
    }
}
