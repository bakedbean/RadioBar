import Foundation

@main
struct HTMLEntitiesTests {
    static func main() {
        var failures = 0
        func check(_ name: String, _ got: String, _ want: String) {
            let ok = got == want
            print(ok ? "✓ \(name)" : "✗ \(name): got \"\(got)\", want \"\(want)\"")
            if !ok { failures += 1 }
        }

        check("named apostrophe",
              HTMLEntities.decode("Don&apos;t Stop Believin&apos;"),
              "Don't Stop Believin'")
        check("named ampersand",
              HTMLEntities.decode("Simon &amp; Garfunkel"),
              "Simon & Garfunkel")
        check("decimal numeric",
              HTMLEntities.decode("It&#39;s Alright &#8211; Live"),
              "It's Alright – Live")
        check("hex numeric",
              HTMLEntities.decode("It&#x27;s Alright"),
              "It's Alright")
        check("single pass, no double decode",
              HTMLEntities.decode("&amp;apos;"),
              "&apos;")
        check("bare ampersand untouched",
              HTMLEntities.decode("Tom & Jerry; Friends"),
              "Tom & Jerry; Friends")
        check("unknown entity untouched",
              HTMLEntities.decode("R&bogus;B"),
              "R&bogus;B")
        check("no entities fast path",
              HTMLEntities.decode("Plain Title"),
              "Plain Title")
        check("accented named entity",
              HTMLEntities.decode("Beyonc&eacute;"),
              "Beyoncé")
        check("invalid numeric untouched",
              HTMLEntities.decode("bad &#; and &#xzz; here"),
              "bad &#; and &#xzz; here")
        check("surrogate scalar untouched",
              HTMLEntities.decode("bad &#55296; here"),
              "bad &#55296; here")
        check("trailing ampersand",
              HTMLEntities.decode("Rock &"),
              "Rock &")
        check("longest valid decimal entity",
              HTMLEntities.decode("max &#1114111; scalar"),
              "max \u{10FFFF} scalar")

        if failures == 0 {
            print("\nAll tests passed")
        } else {
            print("\n\(failures) test(s) failed")
            exit(1)
        }
    }
}
