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
    refresh(false)
    if (window.visible) return
    // Register the window rule first and map the window once Hyprland has it:
    // rules only apply when a window is mapped.
    windowRule.command = ["hyprctl", "eval", windowRuleLua()]
    windowRule.running = true
  }

  // The window's Hyprland rule, registered at runtime instead of living in the
  // user's config, the same way omarchy-launch-about sizes the About window.
  // Replacing the previous rule on every open keeps the size in step with
  // boxW/boxH. float + center + no pin is what makes it behave like About: it
  // opens in the middle of the current workspace, SUPER + drag moves it, and it
  // stays on that workspace. The opacity pair undoes omarchy's default 0.96
  // window alpha, which reads as ghosting through a chart.
  function windowRuleLua() {
    return "if ogw_charts_rule then ogw_charts_rule:set_enabled(false) end; " +
      "ogw_charts_rule = hl.window_rule({ " +
      "match = { class = \"^org\\\\.quickshell$\", title = \"^" + window.title + "$\" }, " +
      "float = true, center = true, size = { " + boxW + ", " + boxH + " }, " +
      "tag = \"-default-opacity\", opacity = \"1 1\" })"
  }

  Process {
    id: windowRule
    // hyprctl eval reports a Lua error on stdout, not stderr.
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "ok") console.warn("opencode-go-watcher: window rule:", text.trim())
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") console.warn("opencode-go-watcher: window rule:", text.trim())
    }
    // Show the window even if hyprctl failed: an unstyled window beats none.
    onExited: window.visible = true
  }

  function close() {
    closingFromHost = true
    window.visible = false
    closingFromHost = false
  }

  // The panel owns an IPC target of its own rather than being summoned through
  // the shell.
  //
  // `omarchy-shell shell summon <id>` sets the shell's openPanelIds and delivers
  // the payload through the plugin's Loader. Close this window with SUPER + W and
  // the compositor destroys the surface, which tears the Loader down; the next
  // summon then queues a payload nobody delivers, and the button does nothing at
  // all until the shell is reloaded. That is the bug this replaces.
  //
  // `keepLoaded` in the manifest keeps the panel component mounted whatever the
  // shell's registry thinks, so this handler is always live and `open` is
  // idempotent — it can only ever open, never toggle shut.
  IpcHandler {
    target: "opencode-go-watcher.charts"
    function open(): void { root.open("") }
    function close(): void { root.close() }
    function toggle(): void { root.evalState && root.windowVisible ? root.close() : root.open("") }
  }

  readonly property bool windowVisible: window.visible

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
  readonly property var summary: (snapshot && snapshot.summary) ? snapshot.summary : []

  // Which of the three operations in the Benchmark box still owe us a result for
  // at least one free model. The snapshot computes this per model rather than
  // from a timestamp: a probe that measured one of two free models has still not
  // measured the other. Deliberately nothing for AA — every number on that chart
  // comes from Artificial Analysis and is never missing, so there is nothing the
  // user could have failed to run.
  readonly property var pendingIntelligence: (snapshot && snapshot.pending) ? snapshot.pending.intelligence : null
  readonly property var pendingSpeed: (snapshot && snapshot.pending) ? snapshot.pending.speed : null
  readonly property bool intelligencePending: pendingIntelligence !== null && pendingIntelligence.length > 0
  readonly property bool speedPending: pendingSpeed !== null && pendingSpeed.length > 0

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
  // The card, with the theme's hue but no alpha.
  //
  // Color.popups.background carries the theme's background alpha, which is right
  // for a bar-anchored popup over a busy desktop and wrong here: this window is
  // a full-height surface with columns and gaps between them, and at any alpha
  // the text of whatever is behind reads straight through the chart as ghosting.
  // A chart you read numbers off has to be opaque.
  readonly property color cardSurface: Qt.rgba(Color.popups.background.r,
                                              Color.popups.background.g,
                                              Color.popups.background.b, 1)

  readonly property color textStrong: Color.foreground
  readonly property color textSoft: Qt.darker(Color.foreground, 1.3)
  readonly property color textFaint: Qt.darker(Color.foreground, 1.5)
  readonly property color textAccent: Color.accent
  readonly property color textUrgent: Color.urgent

  readonly property var screenInfo: (typeof Quickshell !== "undefined" && Quickshell.screens && Quickshell.screens.length > 0) ? Quickshell.screens[0] : null
  readonly property int screenW: screenInfo ? screenInfo.width : 1920
  readonly property int screenH: screenInfo ? screenInfo.height : 1080

  // The window's size: windowRuleLua() hands these to Hyprland, and the clamp
  // keeps the window inside a small screen.
  //
  // Sized so the header, the free-model list, both ten-row charts, the warnings
  // and the attribution all fit at once: the whole point of a comparison view is
  // being able to see both charts together, and scrolling defeats that.
  readonly property int boxW: Math.min(1080, screenW - Style.space(80))
  // Fits the header, three side-by-side charts of ~10 rows, the summary and the
  // legend. Anything taller — an eval in flight, more rows — scrolls.
  readonly property int boxH: Math.min(500, screenH - Style.space(80))
  // A FloatingWindow, not a PanelWindow, and that is load-bearing. Omarchy's own
  // centred windows are FloatingWindows: they are real toplevels, so Hyprland
  // makes one the active window and SUPER + W — which is
  // `hl.dsp.window.close()` — closes it. A PanelWindow is layer-shell, has no
  // toplevel for the compositor to focus, and is therefore uncloseable by any
  // window binding; it can only be dismissed by a keypress this surface happens
  // to hold focus for. The window rule from windowRuleLua() makes it float at
  // boxW x boxH.
  FloatingWindow {
    id: window
    title: "OpenCode Go free models"
    // Hidden until open() has registered the window rule; mapped any earlier,
    // Hyprland would tile it.
    visible: false
    // popups.background, not background: the raw background token carries the
    // theme's background alpha, and a panel drawn in it is see-through.
    color: root.cardSurface
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

          // No title block. "Free today" directly below says what this is, and
          // the AA model count was a number with nothing to compare it against.
          // Whether Artificial Analysis is configured still shows up where it
          // matters: the legend names it as a source, and a missing key raises a
          // warning at the foot of the window.

          // --------------------------------------------------------- progress
          Column {
            width: parent.width
            spacing: Style.space(4)
            // Only while a run is going or after one failed: "Run complete" is
            // already said by the charts themselves.
            visible: (root.evalState.running || root.evalState.error) ? true : false

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

          // ---------------------------------------------------------- header
          // Title and the three operations on one line; the free models under
          // it. The buttons are ringed red while a free model still has no
          // result from that operation — a "not done yet" cue, not a disabled
          // state.
          Item {
            width: parent.width
            height: Math.max(titleText.implicitHeight, actions.implicitHeight)

            Text {
              id: titleText
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              text: "OpenCode Go · free models"
              color: root.textStrong
              font.family: Style.font.family
              font.pixelSize: Style.font.subtitle
              font.bold: true
            }

            Row {
              id: actions
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(8)

              Button {
                text: root.building ? "Refreshing…" : "Refresh"
                bordered: true
                enabled: !root.building
                onClicked: root.refresh(true)
              }

              Button {
                text: root.evalState.running ? "Cancel" : "Run Omniscience"
                bordered: true
                enabled: !evalAction.running
                onClicked: root.evalState.running ? root.cancelEval() : root.startEval()
                Rectangle {
                  anchors.fill: parent
                  radius: Style.cornerRadius
                  color: "transparent"
                  border.width: 1
                  border.color: root.textUrgent
                  visible: root.intelligencePending && !root.evalState.running
                }
              }

              Button {
                text: speedAction.running ? "Measuring…" : "Measure speed"
                bordered: true
                enabled: !speedAction.running
                onClicked: root.measureSpeed()
                Rectangle {
                  anchors.fill: parent
                  radius: Style.cornerRadius
                  color: "transparent"
                  border.width: 1
                  border.color: root.textUrgent
                  visible: root.speedPending
                }
              }
            }
          }

          Text {
            width: parent.width
            wrapMode: Text.Wrap
            text: root.freeModels.length === 0
              ? "opencode Go is serving no free models right now."
              : "Free now: " + root.freeModels.map(function (model) { return model.label }).join("  ·  ")
            color: root.freeModels.length === 0 ? root.textSoft : root.textAccent
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            font.bold: root.freeModels.length > 0
          }

          PanelSeparator { width: parent.width }

          // ---------------------------------------------------------- charts
          // Omniscience | AA Intelligence Index | Output speed, side by side.
          Row {
            id: charts
            width: parent.width
            spacing: Style.space(20)
            readonly property var blocks: root.intelligenceBlocks.concat(root.speedBlocks)
            readonly property real columnWidth: blocks.length > 0
              ? (width - spacing * (blocks.length - 1)) / blocks.length : width

            Repeater {
              model: charts.blocks
              FreeForAllBars {
                width: charts.columnWidth
                block: modelData
                textStrong: root.textStrong
                textSoft: root.textSoft
                textFaint: root.textFaint
                accentColor: root.textAccent
              }
            }
          }

          // --------------------------------------------------------- summary
          Column {
            width: parent.width
            spacing: Style.space(2)
            visible: root.summary.length > 0

            Repeater {
              model: root.summary
              Text {
                width: parent.width
                wrapMode: Text.Wrap
                text: modelData
                color: root.textAccent
                font.family: Style.font.family
                font.pixelSize: Style.font.body
              }
            }
          }

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

          // Legend and source in one line. Crediting Artificial Analysis stays.
          Text {
            width: parent.width
            wrapMode: Text.Wrap
            text: "Accent: free · bold: your orchestrators (medium effort) · dim: AA's top models · outlined: measured here. "
                  + "Other figures from Artificial Analysis."
            color: root.textFaint
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
    // Only while the window is up. keepLoaded means this component is alive for
    // the whole session, and a 20-second poll of a process that reports "no run"
    // is not something to do forever behind a closed window.
    running: root.windowVisible
    repeat: true
    triggeredOnStart: true
    onTriggered: root.pollEval()
  }
}
