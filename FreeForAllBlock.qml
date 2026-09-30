import QtQuick
import qs.Commons
import "."

// One chart block: a caption, its unit, and the bars.
//
// `rows.intelligence` and `rows.speed` are lists of these rather than single
// blocks, because AA's Intelligence Index runs 0-70 while our own Omniscience
// run runs -100..100. Merging them onto one axis would produce a chart that
// looks authoritative and is not.
Column {
  id: root

  property var block: ({})
  property bool showZero: false

  // See FreeForAllRow: the window owns the contrast ramp for the whole panel.
  property color textStrong: Color.foreground
  property color textSoft: Color.foreground
  property color accentColor: Color.accent

  property real labelWidth: 300
  property real valueWidth: 62

  spacing: Style.space(3)

  // Not PanelSectionHeader: that component paints in
  // Qt.darker(foreground, 1.4), which is dimmer than the muted grey the notes
  // used to be in, so the section titles were the least legible text in the
  // window. This is a chart heading, not a panel section label.
  Text {
    width: parent.width
    text: root.block && root.block.caption ? root.block.caption : ""
    color: root.textStrong
    font.family: Style.font.family
    font.pixelSize: Style.font.subtitle
    font.bold: true
    elide: Text.ElideRight
  }

  Text {
    width: parent.width
    text: root.block && root.block.unit ? root.block.unit : ""
    color: root.textSoft
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    bottomPadding: Style.space(2)
  }

  // A block with no rows is the empty state, not a zero-height strip: the
  // original rendered a blank card, which read as "broken" rather than
  // "nothing measured yet".
  Text {
    visible: !root.hasRows
    width: parent.width
    wrapMode: Text.Wrap
    text: "Nothing measured yet."
    color: root.textSoft
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    topPadding: Style.space(2)
  }

  readonly property bool hasRows: root.block && root.block.rows && root.block.rows.length > 0

  Column {
    width: parent.width
    spacing: Style.space(5)

    Repeater {
      model: root.hasRows ? root.block.rows : []

      FreeForAllRow {
        width: root.width
        row: modelData
        domain: root.block ? root.block.domain : ({ min: 0, max: 1, zero: 0 })
        scale: root.block ? root.block.scale : ""
        showZero: root.showZero
        labelWidth: root.labelWidth
        valueWidth: root.valueWidth
        textStrong: root.textStrong
        textSoft: root.textSoft
        accentColor: root.accentColor
      }
    }
  }
}
