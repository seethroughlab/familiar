// ADR-0136 point 8 spike. Headless and sandboxed; writes report.json into its container.
import Foundation

let bundle = Bundle.main.bundleURL
let resources = bundle.appendingPathComponent("Contents/Resources")
let pgBin = resources.appendingPathComponent("postgres/bin")
let python = resources.appendingPathComponent("python/bin/python3")
let home = URL(fileURLWithPath: NSHomeDirectory())  // the container's Data dir under the sandbox
let pgData = home.appendingPathComponent("pgdata")
let musicFolder = ProcessInfo.processInfo.environment["SPIKE_MUSIC"] ?? CommandLine.arguments.dropFirst().first ?? ""
let port = "54329"

var report: [String: Any] = [
    "home": home.path,
    "sandboxed": ProcessInfo.processInfo.environment["APP_SANDBOX_CONTAINER_ID"] != nil,
]

@discardableResult
func run(_ name: String, _ exe: URL, _ args: [String], env extra: [String: String] = [:], timeout: TimeInterval = 120) -> Int32 {
    let p = Process()
    p.executableURL = exe
    p.arguments = args
    var env = ProcessInfo.processInfo.environment
    extra.forEach { env[$0] = $1 }
    p.environment = env
    let out = Pipe(), err = Pipe()
    p.standardOutput = out
    p.standardError = err
    var entry: [String: Any] = ["cmd": ([exe.lastPathComponent] + args).joined(separator: " ")]
    do {
        try p.run()
        let deadline = Date().addingTimeInterval(timeout)
        while p.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
        if p.isRunning { p.terminate(); entry["timeout"] = true }
        p.waitUntilExit()
        entry["status"] = p.terminationStatus
        entry["stdout"] = String(decoding: out.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self).suffix(4000).description
        entry["stderr"] = String(decoding: err.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self).suffix(4000).description
    } catch {
        entry["launch_error"] = "\(error)"
        entry["status"] = -1
    }
    report[name] = entry
    return (entry["status"] as? Int32) ?? -1
}

try? FileManager.default.removeItem(at: pgData)

// 1. initdb with the settings ADR-0136 point 4 names, passed to its bootstrap backend too.
let shm = ["-c", "shared_memory_type=mmap", "-c", "dynamic_shared_memory_type=mmap"]
run("1_initdb", pgBin.appendingPathComponent("initdb"),
    ["-D", pgData.path, "-U", "familiar", "--auth=trust", "--no-sync"] + shm)

// 2. start: TCP on loopback only, no unix socket (container paths exceed sun_path).
let serverOpts = "-c listen_addresses=localhost -c port=\(port) -c unix_socket_directories='' -c shared_memory_type=mmap -c dynamic_shared_memory_type=mmap"
run("2_pg_ctl_start", pgBin.appendingPathComponent("pg_ctl"),
    ["-D", pgData.path, "-o", serverOpts, "-l", home.appendingPathComponent("pg.log").path, "-w", "-t", "30", "start"])

// 3. pgvector, including an HNSW index (what the backend builds on track_analysis.embedding).
let sql = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE t (id serial primary key, e vector(3));
INSERT INTO t (e) SELECT ARRAY[random(), random(), random()]::vector FROM generate_series(1, 2000);
CREATE INDEX ON t USING hnsw (e vector_cosine_ops);
SET enable_seqscan = off;
SELECT count(*) FROM (SELECT id FROM t ORDER BY e <=> '[1,1,1]' LIMIT 10) s;
SELECT extversion FROM pg_extension WHERE extname = 'vector';
"""
run("3_pgvector", pgBin.appendingPathComponent("psql"),
    ["-h", "localhost", "-p", port, "-U", "familiar", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-At", "-c", sql])

// 4. Python: spawn pools, onnxruntime, and the read-only music folder.
run("4_python", python, [resources.appendingPathComponent("experiments.py").path, musicFolder],
    env: ["PYTHONDONTWRITEBYTECODE": "1"], timeout: 180)

// 5. stop.
run("5_pg_ctl_stop", pgBin.appendingPathComponent("pg_ctl"), ["-D", pgData.path, "-m", "fast", "-w", "stop"])
if let log = try? String(contentsOf: home.appendingPathComponent("pg.log"), encoding: .utf8) {
    report["pg_log_tail"] = String(log.suffix(3000))
}

let data = try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
try! data.write(to: home.appendingPathComponent("report.json"))
print(home.appendingPathComponent("report.json").path)
