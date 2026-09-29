import QtQuick
import Quickshell
import Quickshell.Io

// Keeps the OpenCode Go record current in the usage directory the stock
// omarchy.agents panel watches.
//
// The panel is strictly a display: it draws whatever records it finds there,
// whoever wrote them. The stock omarchy-agent-usage-update cannot supply this
// one, because it only globs "$OMARCHY_PATH"/bin/omarchy-agent-usage-* and that
// directory belongs to the omarchy package — a collector inside a plugin
// checkout is never invoked. So this service publishes the record itself.
Item {
  id: root

  // The built-in widget refreshes its own agents every 15 minutes; this record
  // is not one of them, so it needs its own cadence. Local stats walk a
  // database that reaches tens of gigabytes, and the collector caches a scan
  // for 20 seconds, so a shorter interval would mostly re-read the cache.
  readonly property int intervalMs: 300000

  // The free-model charts are on a six-hour cache, because one build costs up
  // to twelve paginated requests against Artificial Analysis's 100 requests per
  // 24h free tier. Rebuilding on every shell start would burn that budget for
  // data that has not moved, so this only primes the cache if it is missing.
  readonly property int chartsIntervalMs: 21600000

  readonly property string publisher: Qt.resolvedUrl("bin/opencode-go-watcher-publish")
  readonly property string charts: Qt.resolvedUrl("bin/opencode-go-watcher-free-for-all")

  Process {
    id: publisherProcess
    running: false

    onExited: (exitCode) => {
      if (exitCode !== 0) {
        console.warn("opencode-go-watcher", "publisher exited " + exitCode)
      }
    }

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") console.warn("opencode-go-watcher", text.trim())
    }
  }

  function publish() {
    // Never run two collectors for the same agent at once: they would race on
    // the scan cache and on the record file.
    if (publisherProcess.running) return
    publisherProcess.command = [root.publisher]
    publisherProcess.running = true
  }

  Timer {
    interval: root.intervalMs
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.publish()
  }

  // Primes the free-model charts without a --force, so the six-hour cache in
  // the collector decides whether anything is actually re-fetched.
  Timer {
    interval: root.chartsIntervalMs
    running: true
    repeat: true
    onTriggered: {
      if (chartsProcess.running) return
      chartsProcess.running = true
    }
  }

  Process {
    id: chartsProcess
    running: false
    command: [root.charts]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {}  // the snapshot is read from disk by the window
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") console.warn("opencode-go-watcher", text.trim())
    }
  }

  Component.onCompleted: {
    root.publish()
    // A cache miss here is the one case worth paying for at shell start: without
    // it the window would open to an empty state on a first run.
    if (chartsProcess.running === false) chartsProcess.running = true
  }
}
