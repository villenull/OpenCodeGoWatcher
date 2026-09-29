import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "."

// The free-model charts window: how the free models on your OpenCode Go plan
// compare, on intelligence and on output speed, with a button to run the
// Omniscience evaluation that produces our own intelligence numbers.
//
// Summon it with:
//   omarchy-shell shell summon io.github.villenull.opencode-go-watcher '{}'
//
// Everything drawn here comes out of one JSON file written by
// bin/opencode-go-watcher-free-for-all, so opening and scrolling never waits
// on the network. A long eval runs in its own detached process; this window only
// polls its state file.
Item {
  id: root

  property var shell: null
  property bool closingFromHost: false

  readonly property string binDir: Qt.resolvedUrl("bin")
  readonly property string snapshotCmd: binDir + "/opencode-go-watcher-free-for-all"
  readonly property string evalCmd: binDir + "/opencode-go-watcher-free-for-all-eval"
  readonly property string speedCmd: binDir + "/opencode-go-watcher-free-for-all-speed"

  property var snapshot: null
  property var evalState: ({ running: false })
  property string loadError: ""
  property string actionError: ""
  property bool building: false
  property bool wasRunning: false

  // ------------------------------------------------------------- lifecycle

  function open(payloadJson) {
    closingFromHost = false
    window.visible = true
    refresh(false)
  }

  function close() {
    closingFromHost = true
    window.visible = false
    closingFromHost = false
  }

  function requestClose() {
    if (shell && typeof shell.hide === "function") shell.hide("io.github.villenull.opencode-go-watcher")
    else window.visible = false
  }

  // ------------------------------------------------------------------ data

  function refresh(force) {
    if (snapshotProcess.running) return
    building = true
    snapshotProcess.command = force ? [snapshotCmd, "--force"] : [snapshotCmd]
    snapshotProcess.running = true
  }

  function applySnapshot(text) {
    try {
      snapshot = JSON.parse(String(text || ""))
      loadError = ""
    } catch (e) {
      loadError = "Could not read the snapshot: " + e
      console.warn("opencode-go-watcher", loadError)
    }
    pollEval()
  }

  function pollEval() {
    if (evalProcess.running) return
    evalProcess.running = true
  }

  function applyEvalState(text) {
    try {
      evalState = JSON.parse(String(text || ""))
      actionError = ""
    } catch (e) {
      actionError = "Could not read the eval state: " + e
    }
    // A finished run changes the charts, so rebuild once on the transition.
    if (wasRunning && !evalState.running) refresh(true)
    wasRunning = evalState.running === true
  }

  function startEval() {
    actionError = ""
    evalAction.command = [evalCmd, "start"]
    evalAction.running = true
  }

  function cancelEval() {
    actionError = ""
    evalAction.command = [evalCmd, "cancel"]
    evalAction.running = true
  }

  function measureSpeed() {
    actionError = "Measuring output speed… this spends a little of your Go quota."
    speedAction.command = [speedCmd]
    speedAction.running = true
  }

  // ---------------------------------------------------------------- layout

  readonly property var intelligenceBlocks: (snapshot && snapshot.rows && snapshot.rows.intelligence) ? snapshot.rows.intelligence : []
  readonly property var speedBlocks: (snapshot && snapshot.rows && snapshot.rows.speed) ? snapshot.rows.speed : []
  readonly property var freeModels: (snapshot && snapshot.freeModels) ? snapshot.freeModels : []
  readonly property var warnings: (snapshot && snapshot.warnings) ? snapshot.warnings : []
  readonly property bool aaConfigured: !!(snapshot && snapshot.aa && snapshot.aa.configured)

  readonly property real progress: (evalState && typeof evalState.progress === "number") ? evalState.progress : 0
  readonly property int currentQuestion: (evalState && typeof evalState.currentQuestion === "number") ? evalState.currentQuestion : 0
  readonly property int totalQuestions: (evalState && typeof evalState.totalQuestions === "number") ? evalState.totalQuestions : 0

  readonly property var screenInfo: (typeof Quickshell !== "undefined" && Quickshell.screens && Quickshell.screens.length > 0) ? Quickshell.screens[0] : null
  readonly property int screenW: screenInfo ? screenInfo.width : 1920
  readonly property int screenH: screenInfo ? screenInfo.height : 1080

  // Preferred content size, clamped to leave a visible border on any screen.
  readonly property int boxW: Math.min(840, screenW - Style.space(80))
  readonly property int boxH: Math.min(900, screenH - Style.space(80))
  // A FloatingWindow, not a PanelWindow, and that is load-bearing. Omarchy's own
  // centred windows are FloatingWindows: they are real toplevels, so Hyprland
  // makes one the active window and SUPER + W — which is
  // `hl.dsp.window.close()` — closes it. A PanelWindow is layer-shell, has no
  // toplevel for the compositor to focus, and is therefore uncloseable by any
  // window binding; it can only be dismissed by a keypress this surface happens
  // to hold focus for.
  //
  // The cost is that a FloatingWindow fills the screen, so the window is
  // transparent and the actual card is centred inside it. That is the same
  // trade omarchy's own dev gallery makes: 3416x1390 of toplevel around a
  // 720px panel.
  FloatingWindow {
    id: window
    title: "OpenCode Go free models"
    color: "transparent"
    implicitWidth: root.boxW
    implicitHeight: root.boxH
    minimumSize: Qt.size(root.boxW, root.boxH)

    onVisibleChanged: {
      if (!visible && !root.closingFromHost && root.shell && typeof root.shell.hide === "function")
        root.shell.hide("io.github.villenull.opencode-go-watcher")
    }

    PanelKeyCatcher {
      anchors.fill: parent
      onCloseRequested: root.requestClose()
    }

    // The visible card. The window behind it is transparent and full-screen, so
    // this is the only thing drawn.
    Rectangle {
      id: card
      anchors.centerIn: parent
      width: root.boxW
      height: root.boxH
      color: Color.background
      radius: Style.cornerRadius
      border.width: 1
      border.color: Qt.alpha(Color.muted, 0.4)

    FocusScope {
      anchors.fill: parent
      focus: true

      ScrollView {
        id: scroll
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        // Positioner (QtQuick's Column) has no padding, so the inset lives on
        // the Column's own x/y and every child measures against its width.
        Column {
          id: content
          x: Style.space(18)
          y: Style.space(16)
          width: Math.max(320, scroll.availableWidth - Style.space(36))
          spacing: Style.space(14)

          // ------------------------------------------------------------ hero
          // The buttons sit in their own right-aligned row rather than in
          // PanelHero's `trailingControl`: the hero is given no icon here, and
          // with an empty icon slot the trailing loader had nothing to measure
          // against and pushed the row past the window's right edge.
          Row {
            width: parent.width
            spacing: Style.space(12)

            PanelHero {
              id: hero
              width: parent.width - actionRow.width - Style.space(12)
              title: "Free models"
              meta: root.aaConfigured
                    ? "Artificial Analysis · " + ((root.snapshot.aa && root.snapshot.aa.modelCount) || 0) + " models"
                    : "no Artificial Analysis key"
              detail: "opencode Go · " + (root.freeModels.length || 0) + " free"
            }

            Row {
              id: actionRow
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(8)

              Button {
                text: root.evalState.running ? "Cancel" : "Run eval"
                bordered: true
                enabled: !evalAction.running
                onClicked: root.evalState.running ? root.cancelEval() : root.startEval()
              }
              Button {
                text: "Refresh"
                bordered: true
                enabled: !root.building
                onClicked: root.refresh(true)
              }
              Button {
                text: "Close"
                bordered: true
                onClicked: root.requestClose()
              }
            }
          }

          // --------------------------------------------------------- progress
          Column {
            width: parent.width
            spacing: Style.space(4)
            visible: (root.evalState.running || root.evalState.message || root.evalState.error) ? true : false

            Text {
              width: parent.width
              wrapMode: Text.Wrap
              text: (root.evalState.running && root.evalState.message) ? root.evalState.message
                    : (root.evalState.error ? root.evalState.error : (root.evalState.message || ""))
              color: root.evalState.running ? Color.accent : Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            Rectangle {
              width: parent.width
              height: 4
              radius: 2
              visible: root.evalState.running === true
              color: "transparent"
              border.width: 1
              border.color: Qt.alpha(Color.muted, 0.35)

              Rectangle {
                width: parent.width * Math.max(0, Math.min(1, root.progress))
                height: parent.height
                radius: 2
                color: Color.accent
              }
            }

            Text {
              width: parent.width
              visible: (root.evalState.running && root.totalQuestions > 0) ? true : false
              text: Math.round(root.progress * 100) + "% · " + root.currentQuestion + "/" + root.totalQuestions + " graded"
              color: Color.accent
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }
          }

          Text {
            width: parent.width
            wrapMode: Text.Wrap
            visible: root.loadError ? true : false
            text: root.loadError || ""
            color: Color.urgent
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          Text {
            width: parent.width
            wrapMode: Text.Wrap
            visible: root.actionError ? true : false
            text: root.actionError || ""
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          // ----------------------------------------------------- free models
          Column {
            width: parent.width
            spacing: Style.space(6)

            PanelSectionHeader { width: parent.width; text: "Free today" }

            Text {
              width: parent.width
              wrapMode: Text.Wrap
              visible: root.freeModels.length === 0
              text: "opencode Go is serving no free models right now."
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            Repeater {
              model: root.freeModels
              Column {
                width: content.width
                spacing: Style.space(1)
                Text {
                  width: parent.width
                  text: modelData.label
                  color: Color.foreground
                  font.family: Style.font.family
                  font.pixelSize: Style.font.body
                }
                Text {
                  width: parent.width
                  text: modelData.id + (modelData.note ? "  ·  " + modelData.note : "")
                  color: Color.muted
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }
            }

            Row {
              width: content.width
              spacing: Style.space(8)
              Button {
                text: speedAction.running ? "Probing…" : "Measure speed"
                bordered: true
                enabled: !speedAction.running
                onClicked: root.measureSpeed()
              }
              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: (root.snapshot && root.snapshot.speedProbedAt)
                      ? "probed " + String(root.snapshot.speedProbedAt).slice(0, 19).replace("T", " ") + "Z"
                      : "never probed"
                color: Color.muted
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }
            }
          }

          PanelSeparator { width: parent.width }

          // ------------------------------------------- chart 1: intelligence
          Column {
            width: parent.width
            spacing: Style.space(8)

            PanelSectionHeader { width: parent.width; text: "Intelligence" }

            Text {
              width: parent.width
              wrapMode: Text.Wrap
              text: "filled = Artificial Analysis · outlined = measured by this plugin · FREE marks a Go free model"
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }

            Repeater {
              model: root.intelligenceBlocks
              FreeForAllBlock {
                width: content.width
                block: modelData
                // The Omniscience index is signed, so a negative one has to be
                // readable as negative: a diverging block draws its zero rule.
                showZero: modelData.scale === "omniscience"
              }
            }
          }

          PanelSeparator { width: parent.width }

          // -------------------------------------------------- chart 2: speed
          Column {
            width: parent.width
            spacing: Style.space(8)

            PanelSectionHeader { width: parent.width; text: "Speed" }

            Repeater {
              model: root.speedBlocks
              FreeForAllBlock {
                width: content.width
                block: modelData
              }
            }
          }

          // -------------------------------------------------------- warnings
          Repeater {
            model: root.warnings
            Text {
              width: content.width
              wrapMode: Text.Wrap
              text: "⚠ " + modelData
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }
          }

          PanelSeparator { width: parent.width }

          // A licence condition of AA's data API, so it stays.
          Text {
            width: parent.width
            wrapMode: Text.Wrap
            text: "Leaderboard and speed figures from Artificial Analysis."
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Item { width: 1; height: Style.space(20) }
        }
      }
    }
    }
  }

  // -------------------------------------------------------------- processes

  Process {
    id: snapshotProcess
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applySnapshot(text)
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") root.loadError = text.trim()
    }
    onExited: root.building = false
  }

  Process {
    id: evalProcess
    command: [root.evalCmd, "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyEvalState(text)
    }
  }

  Process {
    id: evalAction
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") console.log("opencode-go-watcher", text.trim())
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") root.actionError = text.trim()
    }
    onExited: root.pollEval()
  }

  Process {
    id: speedAction
    onExited: {
      root.actionError = ""
      root.refresh(true)
    }
  }

  // Fast while a run is in flight, slow otherwise.
  Timer {
    interval: root.evalState.running ? 2000 : 20000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.pollEval()
  }
}
