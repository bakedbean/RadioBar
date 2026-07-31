import Foundation

struct Station: Identifiable, Codable, Equatable {
    var id = UUID()
    var name: String
    var streamURL: String
    var genre: String
    var websiteURL: String?

    var url: URL? { URL(string: streamURL) }

    static let builtIn: [Station] = [
        Station(
            name: "WERS 88.9 FM",
            streamURL: "https://playerservices.streamtheworld.com/api/livestream-redirect/WERSFMAAC.aac",
            genre: "College/Eclectic",
            websiteURL: "https://wers.org"
        ),
        Station(
            name: "KEXP 90.3 FM",
            streamURL: "https://kexp.streamguys1.com/kexp160.aac",
            genre: "Eclectic",
            websiteURL: "https://kexp.org"
        ),
        Station(
            name: "WXPN 88.5 FM",
            streamURL: "https://wxpnhi.xpn.org/xpnhi",
            genre: "College/AAA",
            websiteURL: "https://xpn.org"
        ),
        Station(
            name: "WXPN: XPN2",
            streamURL: "https://wxpn.xpn.org/xpn2mp3hi",
            genre: "College/Eclectic",
            websiteURL: "https://xpn.org/program/xpn2/"
        ),
        Station(
            name: "SomaFM: Groove Salad",
            streamURL: "https://ice3.somafm.com/groovesalad-256-mp3",
            genre: "Ambient/Downtempo",
            websiteURL: "https://somafm.com"
        ),
        Station(
            name: "SomaFM: Secret Agent",
            streamURL: "https://ice3.somafm.com/secretagent-128-mp3",
            genre: "Spy/Lounge",
            websiteURL: "https://somafm.com"
        ),
        Station(
            name: "SomaFM: Drone Zone",
            streamURL: "https://ice3.somafm.com/dronezone-256-mp3",
            genre: "Ambient/Drone",
            websiteURL: "https://somafm.com"
        ),
        Station(
            name: "SomaFM: Lush",
            streamURL: "https://ice3.somafm.com/lush-128-mp3",
            genre: "Vocal/Electronic",
            websiteURL: "https://somafm.com"
        ),
        Station(
            name: "BBC Radio 6 Music",
            streamURL: "https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/nonuk/sbr_vlow/ak/bbc_6music.m3u8",
            genre: "Eclectic",
            websiteURL: "https://www.bbc.co.uk/6music"
        ),
        Station(
            name: "NTS Radio 1",
            streamURL: "https://stream-relay-geo.ntslive.net/stream",
            genre: "Eclectic",
            websiteURL: "https://nts.live"
        ),
        Station(
            name: "FIP",
            streamURL: "https://icecast.radiofrance.fr/fip-midfi.mp3",
            genre: "Eclectic",
            websiteURL: "https://www.radiofrance.fr/fip"
        ),
        Station(
            name: "Radio Paradise: Main Mix",
            streamURL: "https://stream.radioparadise.com/aac-320",
            genre: "Eclectic",
            websiteURL: "https://radioparadise.com"
        ),
    ]
}

/// Persists stations to/from JSON in Application Support.
struct StationStore {
    private static let fileName = "stations.json"

    static func load() -> [Station] {
        guard let url = storeURL else { return Station.builtIn }
        guard let data = try? Data(contentsOf: url),
              let stations = try? JSONDecoder().decode([Station].self, from: data)
        else { return Station.builtIn }
        return stations
    }

    static func save(_ stations: [Station]) {
        guard let url = storeURL,
              let data = try? JSONEncoder().encode(stations) else { return }
        try? data.write(to: url, options: .atomic)
    }

    private static var storeURL: URL? {
        guard let dir = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first else { return nil }
        let appDir = dir.appendingPathComponent("RadioBar")
        try? FileManager.default.createDirectory(at: appDir,
            withIntermediateDirectories: true)
        return appDir.appendingPathComponent(fileName)
    }
}
