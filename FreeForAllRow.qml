import QtQuick
import qs.Commons

// One bar in a chart block: a label, a track, the bar itself, and the value.
//
// Bar geometry follows the original: the bar spans from whichever of zero and
// the value is further left, to the value, mapped across the block's domain.
// On a diverging domain (the Omniscience block runs -100..100) that is what
// lets a negative index extend left of the zero line instead of being clamped.
//
// A self-measured bar is outlined and an AA bar is filled, so the two sources
// are never confused for one another.
Item {
  id: root

  property var row: ({})
  property var domain: ({ min: 0, max: 1, zero: 0 })
  property string scale: ""
  property bool showZero: false
  property real trackHeight: 22
  property real labelWidth: 190
  property real barGap: Style.space(10)

  readonly property real value: {
    var raw = root.row && root.row.value !== null && root.row.value !== undefined ? Number(root.row.value) : 0
    return isFinite(raw) ? raw : 0
  }
  readonly property real span: {
    var lo = Number(root.domain.min || 0)
    var hi = Number(root.domain.max || 1)
    return (hi - lo) || 1
  }
  readonly property real endFraction: Math.max(0, Math.min(1, (root.value - Number(root.domain.min || 0)) / root.span))
  readonly property real zeroFraction: Math.max(0, Math.min(1, Number(root.domain.zero || 0)))
  readonly property bool diverging: Number(root.domain.min || 0) < 0
  readonly property real startFraction: root.diverging ? Math.min(root.zeroFraction, root.endFraction) : 0
  readonly property real widthFraction: Math.max(0, root.endFraction - root.startFraction)
  readonly property bool isSelf: root.row && root.row.source === "self"
  readonly property bool isFree: root.row && root.row.isFree === true

  implicitHeight: label.implicitHeight + (root.row && root.row.note ? note.implicitHeight + Style.space(2) : 0) + Style.space(8)

  Text {
    id: label
    width: root.labelWidth
    text: {
      if (!root.row) return ""
      // A free model is marked in the label itself, because in a chart of free
      // models against paid context rows the distinction is the whole point.
      return (root.isFree ? "FREE · " : "") + (root.row.label || "")
    }
    color: root.isFree ? Color.accent : Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    elide: Text.ElideRight
  }

  Item {
    id: track
    anchors.left: label.right
    anchors.leftMargin: root.barGap
    anchors.right: valueLabel.left
    anchors.rightMargin: root.barGap
    height: root.trackHeight

    // The zero rule, drawn once per block by ChartBlock; here only the extent.
    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: "transparent"
      border.width: 1
      border.color: Qt.alpha(Color.muted, 0.35)
    }

    Rectangle {
      id: bar
      height: parent.height
      x: parent.width * root.startFraction
      width: Math.max(2, parent.width * root.widthFraction)
      radius: Style.cornerRadius
      // Outlined = measured by us. Filled = published by Artificial Analysis.
      color: root.isSelf ? "transparent" : Color.accent
      border.width: root.isSelf ? 1 : 0
      border.color: Color.accent
    }
  }

  Text {
    id: valueLabel
    anchors.right: parent.right
    anchors.verticalCenter: track.verticalCenter
    width: Style.space(64)
    horizontalAlignment: Text.AlignRight
    text: {
      if (!root.row || root.row.value === null || root.row.value === undefined) return "—"
      var value = Number(root.row.value)
      if (!isFinite(value)) return "—"
      // Output speed is a whole number of tokens per second; the two index
      // scales are read to one decimal.
      return root.scale === "aa-speed" ? String(Math.round(value)) : value.toFixed(1)
    }
    color: root.row && root.row.value !== null && root.row.value !== undefined ? Color.foreground : Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Text {
    id: note
    visible: root.row && root.row.note ? true : false
    anchors.left: track.left
    anchors.right: valueLabel.right
    anchors.top: track.bottom
    anchors.topMargin: Style.space(2)
    text: root.row && root.row.note ? root.row.note : ""
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    elide: Text.ElideRight
    maximumLineCount: 2
    wrapMode: Text.Wrap
  }
}
