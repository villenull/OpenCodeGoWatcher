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

  readonly property string publisher: Qt.resolvedUrl("bin/opencode-go-watcher-publish")

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

  Component.onCompleted: root.publish()
}
