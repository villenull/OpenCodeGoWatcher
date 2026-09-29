import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
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

  spacing: Style.space(6)

  PanelSectionHeader {
    width: parent.width
    text: root.block && root.block.caption ? root.block.caption : ""
  }

  Text {
    text: root.block && root.block.unit ? root.block.unit : ""
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
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
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  readonly property bool hasRows: root.block && root.block.rows && root.block.rows.length > 0

  Column {
    width: parent.width
    spacing: Style.space(8)

    Repeater {
      model: root.hasRows ? root.block.rows : []

      FreeForAllRow {
        width: root.width
        row: modelData
        domain: root.block ? root.block.domain : ({ min: 0, max: 1, zero: 0 })
        scale: root.block ? root.block.scale : ""
        showZero: root.showZero
      }
    }
  }
}
