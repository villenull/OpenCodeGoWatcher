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

  // Contrast ramp for the whole panel, in one place.
  //
  // The theme's own muted token is #707880 on a #101315 panel, which is legible
  // but not comfortably so when you are reading numbers off a bar, and
  // PanelSectionHeader goes darker still. Secondary text here is a *lifted*
  // foreground instead: same hue as the theme, but readable. Colour.muted is
  // kept for the one thing that genuinely wants to recede: nothing.
  readonly property color textStrong: Color.foreground
  readonly property color textSoft: Qt.darker(Color.foreground, 1.3)
  readonly property color textFaint: Qt.darker(Color.foreground, 1.5)
  readonly property color textAccent: Color.accent
  readonly property color textUrgent: Color.urgent

  readonly property var screenInfo: (typeof Quickshell !== "undefined" && Quickshell.screens && Quickshell.screens.length > 0) ? Quickshell.screens[0] : null
  readonly property int screenW: screenInfo ? screenInfo.width : 1920
  readonly property int screenH: screenInfo ? screenInfo.height : 1080

  // Must agree with the `size` in the Hyprland window rule. The rule wins when
  // it is present; these are the fallback for when it is not, and the clamp
  // keeps the window inside a small screen.
  //
  // Sized so the header, the free-model list, both ten-row charts, the warnings
  // and the attribution all fit at once: the whole point of a comparison view is
  // being able to see both charts together, and scrolling defeats that.
  readonly property int boxW: Math.min(1180, screenW - Style.space(80))
  readonly property int boxH: Math.min(1010, screenH - Style.space(80))
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
    // popups.background, not background: the raw background token carries the
    // theme's background alpha, and a panel drawn in it is see-through.
    color: Color.popups.background
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

    // No inner card. There used to be a Rectangle inset inside a transparent
    // window, which meant the window and the visible surface were two different
    // rectangles: Hyprland draws the active border on the window, so the
    // highlight came out 30px larger than the card on every side. The window's
    // own colour is the surface instead, so border and content are the same
    // rectangle by construction.
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
          // Title only. The actions used to sit to the right of this, vertically
          // centred against it, which left them floating above the thing they
          // act on: both of them change the free models, and the free models
          // are the list below. They moved down to the "Free today" line, which
          // is the first line of the thing they operate on.
          //
          // Not PanelHero's `trailingControl` either: the hero is given no icon
          // here, and with an empty icon slot the trailing loader had nothing to
          // measure against and pushed its contents past the window edge.
          PanelHero {
            id: hero
            width: parent.width
            title: "Free models"
            // No count here: the list directly below says which models are
            // free, so "2 free" above the list is a number you have to
            // cross-check against something you can already see.
            meta: root.aaConfigured
                  ? "Artificial Analysis · " + ((root.snapshot.aa && root.snapshot.aa.modelCount) || 0) + " models"
                  : "no Artificial Analysis key"
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
              color: root.evalState.running ? root.textAccent : root.textSoft
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
              border.color: Qt.alpha(root.textSoft, 0.4)

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
              color: root.textAccent
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
          }

          Text {
            width: parent.width
            wrapMode: Text.Wrap
            visible: root.loadError ? true : false
            text: root.loadError || ""
            color: root.textUrgent
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          Text {
            width: parent.width
            wrapMode: Text.Wrap
            visible: root.actionError ? true : false
            text: root.actionError || ""
            color: root.textSoft
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }

          // ----------------------------------------------------- free models
          Column {
            width: parent.width
            spacing: Style.space(4)

            // The actions live on this line, top-aligned with the heading and
            // pushed to the right edge, so the buttons sit beside the first line
            // of the list they change rather than floating above it in the hero.
            Item {
              width: parent.width
              height: Math.max(freeTodayTitle.implicitHeight, actionRow.implicitHeight)

              Text {
                id: freeTodayTitle
                anchors.left: parent.left
                anchors.top: parent.top
                text: "Free today"
                color: root.textStrong
                font.family: Style.font.family
                font.pixelSize: Style.font.subtitle
                font.bold: true
              }

              Row {
                id: actionRow
                anchors.right: parent.right
                anchors.top: parent.top
                spacing: Style.space(8)

                Button {
                  text: root.evalState.running ? "Cancel" : "Benchmark free models"
                  bordered: true
                  enabled: !evalAction.running
                  onClicked: root.evalState.running ? root.cancelEval() : root.startEval()
                }
                Button {
                  text: "Refresh AA benchmarks"
                  bordered: true
                  enabled: !root.building
                  onClicked: root.refresh(true)
                }
              }
            }

            Text {
              width: parent.width
              wrapMode: Text.Wrap
              visible: root.freeModels.length === 0
              text: "opencode Go is serving no free models right now."
              color: root.textSoft
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            Repeater {
              model: root.freeModels
              Row {
                width: content.width
                spacing: Style.space(10)

                Text {
                  width: 220
                  text: modelData.label
                  color: root.textAccent
                  font.family: Style.font.family
                  font.pixelSize: Style.font.body
                  font.bold: true
                  elide: Text.ElideRight
                }
                Text {
                  width: 210
                  text: modelData.id
                  color: root.textFaint
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  elide: Text.ElideRight
                }
                Text {
                  width: parent.width - 220 - 210 - Style.space(20)
                  text: modelData.note || ""
                  color: root.textSoft
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  elide: Text.ElideRight
                }
              }
            }

            Row {
              width: content.width
              spacing: Style.space(10)
              topPadding: Style.space(2)

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
                color: root.textSoft
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
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
              color: root.textFaint
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
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
              color: root.textFaint
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
          }

          PanelSeparator { width: parent.width }

          // A licence condition of AA's data API, so it stays.
          Text {
            width: parent.width
            wrapMode: Text.Wrap
            text: "Leaderboard and speed figures from Artificial Analysis."
            color: root.textSoft
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }

          Item { width: 1; height: Style.space(20) }
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
