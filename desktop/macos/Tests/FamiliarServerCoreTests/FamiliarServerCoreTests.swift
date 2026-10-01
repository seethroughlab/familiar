import Foundation
import XCTest

@testable import FamiliarServerCore

final class LayoutTests: XCTestCase {
    func testPostgresStateIsSharedAndServerStateIsNot() {
        let layout = Layout(
            groupContainer: URL(fileURLWithPath: "/G"),
            appSupport: URL(fileURLWithPath: "/A"),
            resources: URL(fileURLWithPath: "/R")
        )
        // The agent and the sandboxed server both reach the group container, and nothing else.
        XCTAssertTrue(layout.postgresData.path.hasPrefix("/G/"))
        XCTAssertTrue(layout.postgresPasswordFile.path.hasPrefix("/G/"))
        XCTAssertTrue(layout.serverData.path.hasPrefix("/A/"))
        XCTAssertEqual(layout.python.path, "/R/python/bin/python3")
    }

    /// ADR-0136's spike: macOS caps a semaphore name at 31 characters, and Python appends
    /// `-` and eight random characters to the prefix.
    func testTheSemaphorePrefixLeavesRoomForPythonsNames() {
        XCTAssertTrue(Identity.semaphorePrefix.hasPrefix(Identity.appGroup + "/"))
        XCTAssertLessThanOrEqual(Identity.semaphorePrefix.count + 1 + 8, 31)
    }
}

final class PostgresSetupTests: XCTestCase {
    func testLoopbackOnlyAndNoSocket() {
        let args = PostgresSetup.serverArguments(dataDirectory: URL(fileURLWithPath: "/d"))
        XCTAssertTrue(args.contains("listen_addresses=127.0.0.1"))
        XCTAssertTrue(args.contains("unix_socket_directories="))
    }

    func testInitdbUsesAPasswordNotTrust() {
        let args = PostgresSetup.initdbArguments(dataDirectory: URL(fileURLWithPath: "/d"), passwordFile: URL(fileURLWithPath: "/p"))
        XCTAssertTrue(args.contains("--auth=scram-sha-256"))
        XCTAssertTrue(args.contains("--pwfile=/p"))
        XCTAssertFalse(args.contains { $0.contains("trust") })
    }

    func testThePasswordIsEncodedIntoTheURL() {
        XCTAssertEqual(
            PostgresSetup.databaseURL(password: "a/b+c@d"),
            "postgresql+asyncpg://familiar:a%2Fb%2Bc%40d@127.0.0.1:54329/familiar"
        )
    }

    func testGeneratedPasswordsAreLongAndDistinct() {
        let a = PostgresSetup.generatePassword(), b = PostgresSetup.generatePassword()
        XCTAssertGreaterThanOrEqual(a.count, 40)
        XCTAssertNotEqual(a, b)
        XCTAssertFalse(a.contains("/") || a.contains("+") || a.contains("="))
    }
}

final class ServerLaunchTests: XCTestCase {
    private let layout = Layout(
        groupContainer: URL(fileURLWithPath: "/G"),
        appSupport: URL(fileURLWithPath: "/A"),
        resources: URL(fileURLWithPath: "/R")
    )

    func testItRunsAppServeOnLoopbackByDefault() {
        let launch = ServerLaunch(layout: layout, musicFolder: URL(fileURLWithPath: "/Music"), databasePassword: "pw")
        XCTAssertEqual(launch.executable.path, "/R/python/bin/python3")
        XCTAssertEqual(launch.arguments, ["-m", "app.serve", "--host", "127.0.0.1", "--port", "4400"])
        XCTAssertEqual(launch.workingDirectory.path, "/R/backend")
    }

    func testLANIsAChoice() {
        let launch = ServerLaunch(layout: layout, musicFolder: URL(fileURLWithPath: "/Music"), databasePassword: "pw", lan: true)
        XCTAssertEqual(launch.arguments[3], "0.0.0.0")
    }

    func testTheEnvironmentTheServerIsOwed() {
        let env = ServerLaunch(layout: layout, musicFolder: URL(fileURLWithPath: "/Music"), databasePassword: "pw").environment
        XCTAssertEqual(env["MUSIC_LIBRARY_PATH"], "/Music")
        XCTAssertEqual(env["FAMILIAR_DATA_DIR"], "/A/data")
        XCTAssertEqual(env["FAMILIAR_SEMAPHORE_PREFIX"], "7JL9RZ9C8P.fs/mp")
        XCTAssertEqual(env["MAX_ANALYSIS_WORKERS"], "1")
        XCTAssertTrue(env["PATH"]!.hasPrefix("/R/bin:"), "the bundled ffmpeg is found first")
        XCTAssertEqual(env["FAMILIAR_CHROMAPRINT_LIBRARY"], "/R/lib/libchromaprint.1.dylib")
        XCTAssertEqual(env["DATABASE_URL"], "postgresql+asyncpg://familiar:pw@127.0.0.1:54329/familiar")
    }

    /// ADR-0133: a `REDIS_URL` in the developer's shell would switch the server's store.
    func testNothingElseFromTheParentLeaksIn() {
        let env = ServerLaunch(
            layout: layout, musicFolder: URL(fileURLWithPath: "/M"), databasePassword: "pw",
            inherited: ["HOME": "/h", "REDIS_URL": "redis://x", "FAMILIAR_ALLOW_WRITABLE_LIBRARY": "1"]
        ).environment
        XCTAssertEqual(env["HOME"], "/h")
        XCTAssertNil(env["REDIS_URL"])
        XCTAssertNil(env["FAMILIAR_ALLOW_WRITABLE_LIBRARY"], "zero-touch is never waived from outside")
    }
}

final class RestartPolicyTests: XCTestCase {
    func testBackoffDoublesToAMinute() {
        var policy = RestartPolicy()
        let delays = (0..<8).map { _ in policy.delay(afterExitWithUptime: 1) }
        XCTAssertEqual(delays, [1, 2, 4, 8, 16, 32, 60, 60])
    }

    func testAHealthyRunIsForgiven() {
        var policy = RestartPolicy()
        _ = policy.delay(afterExitWithUptime: 1)
        _ = policy.delay(afterExitWithUptime: 1)
        XCTAssertEqual(policy.delay(afterExitWithUptime: 3600), 1)
    }
}

final class EtiquetteTests: XCTestCase {
    let now = Date(timeIntervalSince1970: 1_000_000)

    func testAPluggedInCoolMachineRuns() {
        XCTAssertEqual(Etiquette.decide(MachineState(), now: now), .run)
    }

    func testEachReasonToPause() {
        XCTAssertEqual(Etiquette.decide(MachineState(onBattery: true), now: now).reason, "On battery")
        XCTAssertEqual(Etiquette.decide(MachineState(lowPowerMode: true), now: now).reason, "Low Power Mode")
        XCTAssertEqual(Etiquette.decide(MachineState(thermal: .serious), now: now).reason, "Your Mac is running hot")
        XCTAssertEqual(Etiquette.decide(MachineState(thermal: .fair), now: now), .run, "fair is not hot")
    }

    func testHeatIsNamedBeforeBattery() {
        let state = MachineState(onBattery: true, thermal: .critical)
        XCTAssertEqual(Etiquette.decide(state, now: now).reason, "Your Mac is running hot")
    }

    func testAnOverrideRunsAnywayUntilItExpires() {
        var state = MachineState(onBattery: true, overrideUntil: now.addingTimeInterval(3600))
        XCTAssertEqual(Etiquette.decide(state, now: now), .run)
        state.overrideUntil = now.addingTimeInterval(-1)
        XCTAssertEqual(Etiquette.decide(state, now: now).reason, "On battery", "it expires by itself")
    }

    func testTheOwnersPauseBeatsTheirOwnOverride() {
        let state = MachineState(pausedByOwner: true, overrideUntil: now.addingTimeInterval(3600))
        XCTAssertEqual(Etiquette.decide(state, now: now).reason, "Paused by you")
    }
}

final class SyncDebouncerTests: XCTestCase {
    func testASyncWaitsForTheFolderToGoQuiet() {
        var debouncer = SyncDebouncer(quietPeriod: 180)
        let t0 = Date(timeIntervalSince1970: 0)
        XCTAssertFalse(debouncer.takeDue(at: t0), "nothing changed")
        debouncer.noteChange(at: t0)
        debouncer.noteChange(at: t0.addingTimeInterval(100))  // an album still copying
        XCTAssertFalse(debouncer.takeDue(at: t0.addingTimeInterval(200)))
        XCTAssertTrue(debouncer.takeDue(at: t0.addingTimeInterval(281)))
        XCTAssertFalse(debouncer.takeDue(at: t0.addingTimeInterval(500)), "one sync per quiet spell")
    }
}

final class PairingLinkBuilderTests: XCTestCase {
    /// The player form-decodes (familiar-apple `PairingLink`), and so does `URLComponents`.
    func testValuesSurviveTheRoundTrip() {
        let url = PairingLinkBuilder.link(
            serverID: "35a8b200-186c-4ac2-a005-9717a58ef8d5", name: "Studio MacBook",
            host: "127.0.0.1", port: 4400, token: "tok/+="
        )
        XCTAssertEqual(url.scheme, "familiar")
        XCTAssertEqual(url.host, "pair")
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)!.queryItems!
        let query = Dictionary(uniqueKeysWithValues: items.map { ($0.name, $0.value!) })
        XCTAssertEqual(query["name"], "Studio MacBook")
        XCTAssertEqual(query["token"], "tok/+=")
        XCTAssertEqual(query["port"], "4400")
        XCTAssertFalse(url.absoluteString.contains("+"), "a literal plus would read back as a space")
    }
}

final class PlayerLinksTests: XCTestCase {
    /// The site's install links are checked against the live App Store by `check-claims`; this keeps
    /// the menu's in step with them.
    func testTheMenuLinksTheAppTheSiteLinks() throws {
        let repo = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let site = try String(contentsOf: repo.appendingPathComponent("site/index.html"), encoding: .utf8)
        XCTAssertTrue(site.contains("apps.apple.com/us/app/familiar-player/id\(PlayerLinks.appStoreID)?platform=mac"))
        XCTAssertTrue(site.contains(PlayerLinks.iPhone.absoluteString))
        XCTAssertEqual(PlayerLinks.mac.scheme, "macappstore")
    }
}
