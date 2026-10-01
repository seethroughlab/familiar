// familiar-postgres-agent: runs Postgres beside the App Sandbox (ADR-0136 point 4).
//
// Registered by Familiar Server with `SMAppService.agent`, so launchd starts it at login and
// restarts it if it crashes. It is unsandboxed because Postgres cannot run in the sandbox: it always
// creates a 56-byte System V shared-memory segment as a postmaster interlock, and the sandbox refuses
// System V shared memory (ADR-0136's spike). It never touches the music folder.
//
// On first run it creates the cluster, then it replaces itself with `postgres`, so the process
// launchd supervises is Postgres itself.
import Darwin
import Foundation
import FamiliarServerCore

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("familiar-postgres-agent: \(message)\n".utf8))
    exit(1)
}

/// This executable's absolute path, from the kernel. Not `argv[0]`: launchd starts a `BundleProgram`
/// agent with the bundle-relative `Contents/MacOS/familiar-postgres-agent`, which resolved against
/// `/` and sent the agent looking for `/Contents/Resources/postgres/bin/initdb`. Hidden for as long as
/// the integration check started the agent by hand, with a full path (ADR-0140).
func ownPath() -> URL {
    var size: UInt32 = 0
    _NSGetExecutablePath(nil, &size)
    var buffer = [CChar](repeating: 0, count: Int(size))
    guard _NSGetExecutablePath(&buffer, &size) == 0 else { fail("cannot find my own executable") }
    return URL(fileURLWithPath: String(cString: buffer)).resolvingSymlinksInPath()
}

let executable = ownPath()
let contents = executable.deletingLastPathComponent().deletingLastPathComponent()  // …/Contents
// The app bundle's own id (this executable lives in its Contents/MacOS), so an integration build's
// agent finds the integration build's folder.
let bundleID = Bundle(url: contents.deletingLastPathComponent())?.bundleIdentifier ?? Identity.bundleID
let layout = Layout(appSupport: Layout.defaultAppSupport(bundleID: bundleID), resources: contents.appendingPathComponent("Resources"))

// launchd gives an agent no log file of its own, and the plist cannot name a path under the user's
// home, so the agent points its own output at its own folder before doing anything else.
try? FileManager.default.createDirectory(
    at: layout.postgresLog.deletingLastPathComponent(), withIntermediateDirectories: true
)
if let log = fopen(layout.postgresLog.path, "a") {
    dup2(fileno(log), STDOUT_FILENO)
    dup2(fileno(log), STDERR_FILENO)
}

let fm = FileManager.default
if !fm.fileExists(atPath: layout.postgresData.appendingPathComponent("PG_VERSION").path) {
    // The app normally writes the password before registering this agent; if it has not, the agent
    // makes one, and the app reads it from the same place.
    if !fm.fileExists(atPath: layout.postgresPasswordFile.path) {
        let password = PostgresSetup.generatePassword()
        guard fm.createFile(
            atPath: layout.postgresPasswordFile.path,
            contents: Data(password.utf8),
            attributes: [.posixPermissions: 0o600]
        ) else { fail("could not write \(layout.postgresPasswordFile.path)") }
    }
    try? fm.removeItem(at: layout.postgresData)
    let initdb = Process()
    initdb.executableURL = layout.postgresBin.appendingPathComponent("initdb")
    initdb.arguments = PostgresSetup.initdbArguments(
        dataDirectory: layout.postgresData, passwordFile: layout.postgresPasswordFile
    )
    do { try initdb.run() } catch { fail("could not run initdb: \(error)") }
    initdb.waitUntilExit()
    guard initdb.terminationStatus == 0 else { fail("initdb exited \(initdb.terminationStatus)") }

    // `initdb` makes only `postgres` and the templates. The server's own database is created here,
    // in single-user mode, which reads SQL from stdin and needs no server running yet.
    let single = Process()
    single.executableURL = layout.postgresBin.appendingPathComponent("postgres")
    single.arguments = ["--single", "-D", layout.postgresData.path, "postgres"]
    let input = Pipe()
    single.standardInput = input
    do { try single.run() } catch { fail("could not run postgres --single: \(error)") }
    input.fileHandleForWriting.write(Data("CREATE DATABASE \(PostgresSetup.database) OWNER \(PostgresSetup.user);\n".utf8))
    try? input.fileHandleForWriting.close()
    single.waitUntilExit()
    guard single.terminationStatus == 0 else { fail("creating the database exited \(single.terminationStatus)") }
}

let postgres = layout.postgresBin.appendingPathComponent("postgres").path
let arguments = [postgres] + PostgresSetup.serverArguments(dataDirectory: layout.postgresData)
let argv = arguments.map { strdup($0) } + [nil]
execv(postgres, argv)
fail("could not exec \(postgres): \(String(cString: strerror(errno)))")
