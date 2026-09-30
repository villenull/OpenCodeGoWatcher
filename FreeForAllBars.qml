import QtQuick
import qs.Commons
import "."

// One chart block as horizontal bars: a caption, its unit, then one row per
// model — name, bar, value.
//
// Horizontal rather than columns so three blocks fit side by side and model
// names stay on one line. Blocks never share an axis: AA's Intelligence Index,
// the −100…100 Omniscience index and tokens/second are different scales.
//
// Row styling carries the row's role, so the chart needs no per-row prefix:
//   free          accent-coloured name and bar
//   orchestrator  full-strength name, neutral bar
//   context       dimmed name and bar (AA's top models, for scale)
// A bar measured by this plugin is outlined; one published by AA is filled.
Column {
  id: root

  property var block: ({})

  property color textStrong: Color.foreground
  property color textSoft: Color.foreground
  property color textFaint: Color.foreground
  property color barColor: Qt.darker(Color.foreground, 1.5)
  property color accentColor: Color.accent

  property real nameWidth: 185
  property real valueWidth: 44
  property real rowHeight: 20

  spacing: Style.space(4)

  readonly property var rows: (root.block && root.block.rows) ? root.block.rows : []
  readonly property var domain: (root.block && root.block.domain) ? root.block.domain : ({ min: 0, max: 1, zero: 0 })
  readonly property real span: (Number(root.domain.max || 1) - Number(root.domain.min || 0)) || 1
  // Where value 0 sits across the bar track, 0..1. Only the Omniscience block
  // goes negative; everywhere else this is 0.
  readonly property real zero: Math.max(0, Math.min(1, Number(root.domain.zero || 0)))

  Text {
    width: parent.width
    text: root.block && root.block.caption ? root.block.caption : ""
    color: root.textStrong
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    font.bold: true
    elide: Text.ElideRight
  }

  Text {
    width: parent.width
    text: root.block && root.block.unit ? root.block.unit : ""
    color: root.textSoft
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    elide: Text.ElideRight
  }

  Text {
    visible: root.rows.length === 0
    width: parent.width
    wrapMode: Text.Wrap
    text: "Nothing measured yet."
    color: root.textSoft
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }

  Column {
    width: parent.width
    spacing: Style.space(2)

    Repeater {
      model: root.rows

      Item {
        id: row
        width: parent.width
        height: root.rowHeight

        readonly property string role: modelData && modelData.role ? modelData.role : (modelData && modelData.isFree ? "free" : "context")
        readonly property bool isFree: role === "free"
        readonly property bool isSelf: modelData && modelData.source === "self"
        readonly property real value: {
          var raw = modelData && modelData.value !== null && modelData.value !== undefined ? Number(modelData.value) : 0
          return isFinite(raw) ? raw : 0
        }
        readonly property color nameColor: isFree ? root.accentColor
          : (role === "orchestrator" ? root.textStrong : root.textFaint)
        readonly property color fill: isFree ? root.accentColor
          : (role === "orchestrator" ? root.barColor : Qt.alpha(root.barColor, 0.55))

        // Name, then the effort level AA measured it at, if not maximum.
        Row {
          id: nameRow
          width: root.nameWidth
          height: parent.height
          spacing: Style.space(4)
          clip: true

          Text {
            id: nameText
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, root.nameWidth - (effortText.visible ? effortText.implicitWidth + Style.space(4) : 0))
            text: modelData ? (modelData.shortLabel || modelData.label || "") : ""
            elide: Text.ElideRight
            color: row.nameColor
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: row.isFree || row.role === "orchestrator"
          }
          Text {
            id: effortText
            anchors.verticalCenter: parent.verticalCenter
            visible: text !== ""
            text: modelData && modelData.configLabel ? modelData.configLabel : ""
            color: root.textFaint
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }
        }

        // The bar track: zero at `root.zero`, positive bars grow right,
        // negative ones left.
        Item {
          id: track
          x: root.nameWidth + Style.space(6)
          width: parent.width - x - root.valueWidth - Style.space(6)
          height: parent.height

          Rectangle {
            visible: root.zero > 0
            x: track.width * root.zero
            width: 1
            height: parent.height
            color: Qt.alpha(root.barColor, 0.6)
          }

          Rectangle {
            readonly property real length: Math.min(1, Math.abs(row.value) / root.span) * track.width
            x: row.value >= 0 ? track.width * root.zero : track.width * root.zero - length
            width: Math.max(2, length)
            height: Math.round(parent.height * 0.62)
            anchors.verticalCenter: parent.verticalCenter
            radius: 2
            color: row.isSelf ? "transparent" : row.fill
            border.width: row.isSelf ? 1 : 0
            border.color: row.isFree ? root.accentColor : root.barColor
          }
        }

        Text {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: root.valueWidth
          horizontalAlignment: Text.AlignRight
          text: {
            if (!modelData || modelData.value === null || modelData.value === undefined) return "—"
            var v = Number(modelData.value)
            if (!isFinite(v)) return "—"
            return root.block && root.block.scale === "aa-speed" ? String(Math.round(v)) : v.toFixed(1)
          }
          color: row.isFree ? root.accentColor : (row.role === "orchestrator" ? root.textStrong : root.textFaint)
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          font.bold: row.isFree
        }
      }
    }
  }
}
