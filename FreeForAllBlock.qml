import QtQuick
import qs.Commons
import "."

// One chart block: a caption, its unit, and a column chart.
//
// `rows.intelligence` and `rows.speed` are lists of these rather than single
// blocks, because AA's Intelligence Index runs 0-70 while our own Omniscience
// run runs -100..100. Merging them onto one axis would produce a chart that
// looks authoritative and is not.
//
// Columns rather than bars, with the free models tinted: a free model is one
// column among ten context rows, and a `FREE` prefix on a narrow label under a
// column is not something you can read at a glance.
Column {
  id: root

  property var block: ({})
  property bool showZero: false

  // The window owns the contrast ramp for the whole panel. A component reaching
  // for the theme's muted token on its own is how this chart ended up
  // unreadable the first time.
  property color textStrong: Color.foreground
  property color textSoft: Color.foreground
  // Neutral fill for the paid context rows, so the accent-tinted free model is
  // the thing your eye lands on. The raw foreground token is far too loud for a
  // large filled area.
  property color trackColor: Qt.darker(Color.foreground, 1.5)
  property color valueColor: Color.foreground
  property color accentColor: Color.accent

  property real plotHeight: 210
  // The tallest column tops out below the plot edge, leaving room for its value
  // label. Without this the leading value is drawn over the unit line, and on
  // the speed chart it disappears entirely.
  readonly property real headroom: 0.86
  property real columnGap: Style.space(4)
  property real barWidth: 54
  property real labelHeight: 64

  spacing: Style.space(3)

  // Not PanelSectionHeader: that component paints in
  // Qt.darker(foreground, 1.4), which is dimmer than the notes under it, so the
  // headings were the least legible text in the window.
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
  }

  // A block with no rows is the empty state, not a zero-height strip.
  Text {
    visible: !root.hasRows
    width: parent.width
    wrapMode: Text.Wrap
    text: "Nothing measured yet."
    color: root.textSoft
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    topPadding: Style.space(8)
  }

  readonly property var rows: (root.block && root.block.rows) ? root.block.rows : []
  readonly property bool hasRows: rows.length > 0
  readonly property var domain: (root.block && root.block.domain) ? root.block.domain : ({ min: 0, max: 1, zero: 0 })

  readonly property real span: (Number(root.domain.max || 1) - Number(root.domain.min || 0)) || 1
  readonly property bool diverging: Number(root.domain.min || 0) < 0

  // Where the value-0 line sits, as a 0..1 fraction of the plot height. On a
  // zero-based block that is the floor; on the Omniscience block it is above
  // it, and negative columns hang below that rule.
  readonly property real zeroY: root.diverging
    ? root.plotHeight * (1 - Math.max(0, Math.min(1, Number(root.domain.zero || 0))))
    : root.plotHeight

  readonly property real columnWidth: root.hasRows
    ? Math.max(48, Math.min(112, Math.floor((root.width - root.columnGap * (rows.length - 1)) / rows.length)))
    : root.width

  visible: hasRows

  // The plot: every column in one row of a fixed-height strip, so the zero rule
  // can be drawn once across the whole thing.
  Item {
    id: plot
    width: parent.width
    height: root.plotHeight + root.labelHeight
    visible: root.hasRows

    // Value-0 rule. On a zero-based block this is the axis every column stands
    // on; on the diverging one it is a line through the middle.
    Rectangle {
      x: 0
      y: root.zeroY
      width: parent.width
      height: 1
      color: Qt.alpha(root.trackColor, 0.5)
    }

    Row {
      id: columns
      x: 0
      y: 0
      spacing: root.columnGap

      Repeater {
        model: root.rows

        Item {
          id: column
          width: root.columnWidth
          height: root.plotHeight + root.labelHeight

          readonly property real value: {
            var raw = modelData && modelData.value !== null && modelData.value !== undefined ? Number(modelData.value) : 0
            return isFinite(raw) ? raw : 0
          }
          // Clamped to the domain so a value outside it cannot draw outside the
          // plot, and floored at zero height so a null value is an empty column
          // rather than a hairline.
          readonly property real magnitude: Math.max(0,
            Math.min(root.span, value - Number(root.domain.min || 0)))
          readonly property real columnHeight: (magnitude / root.span) * root.plotHeight * root.headroom
          readonly property bool isFree: modelData && modelData.isFree === true
          readonly property bool isSelf: modelData && modelData.source === "self"
          readonly property color tint: isFree ? root.accentColor : root.trackColor

          // The column itself.
          Rectangle {
            id: bar
            width: Math.min(root.barWidth, column.width)
            height: column.columnHeight
            x: (column.width - width) / 2
            // Positive values grow up from the zero rule, negative hang below it.
            y: column.value >= 0 ? root.zeroY - height : root.zeroY
            radius: Style.cornerRadius
            // Outlined = measured by us. Filled = published by Artificial
            // Analysis. The free model is distinguished by the tint of both the
            // column and its label, not by a prefix on a narrow label.
            color: column.isSelf ? "transparent" : column.tint
            border.width: column.isSelf ? 1 : 0
            border.color: column.tint
          }

          // Value, sitting on the column's own tip rather than in a fixed band
          // at the top of the plot, so it tracks the height.
          Text {
            width: column.width
            horizontalAlignment: Text.AlignHCenter
            y: column.value >= 0
              ? Math.max(0, bar.y - implicitHeight - Style.space(3))
              : Math.min(root.plotHeight - implicitHeight, bar.y + bar.height + Style.space(3))
            text: {
              if (!modelData || modelData.value === null || modelData.value === undefined) return "—"
              var value = Number(modelData.value)
              if (!isFinite(value)) return "—"
              return root.block && root.block.scale === "aa-speed" ? String(Math.round(value)) : value.toFixed(1)
            }
            color: column.isFree ? root.accentColor : root.valueColor
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            font.bold: true
          }

          // Label under the axis. `shortLabel` has already had AA's
          // configuration parenthetical removed server-side; the full name is
          // still in the record, and is the tooltip.
          Text {
            width: column.width
            y: root.plotHeight + Style.space(6)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
            text: modelData ? (modelData.shortLabel || modelData.label || "") : ""
            color: column.isFree ? root.accentColor : root.textSoft
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: column.isFree
          }

          // The configuration the number was measured at, under the name. A
          // 57.6 taken at max effort with a fallback is not the same claim as
          // a bare 57.6, and with one row per model it is no longer visible in
          // the name itself. Dim so the name stays the label. Empty for models
          // AA publishes without a parenthetical, which is why the line is
          // hidden rather than blank.
          Text {
            width: column.width
            y: root.plotHeight + Style.space(40)
            horizontalAlignment: Text.AlignHCenter
            visible: text.length > 0
            text: modelData ? (modelData.configLabel || "") : ""
            // One line, elided. A column is about 110px and the widest label
            // is 20 characters, so this is a backstop rather than the norm —
            // but an overlapping label is far worse than a truncated one.
            elide: Text.ElideRight
            color: column.isFree ? Qt.alpha(root.accentColor, 0.6) : Qt.alpha(root.textSoft, 0.55)
            font.family: Style.font.family
            // A step below the name. "adaptive·fallback" is 17 characters and a
            // column is about 114px, so at bodySmall it elides to
            // "adaptive·fallba…" and the line stops saying anything. Never below
            // 9px, whatever the theme picks for bodySmall.
            font.pixelSize: Math.max(9, Math.round(Style.font.bodySmall * 0.85))
          }
        }
      }
    }
  }

  // Source note, under the chart rather than per column: only one row in each
  // chart is self-measured, and repeating a sentence ten times helps nobody.
  Text {
    width: parent.width
    visible: root.hasSelfRow
    text: "outlined = measured by this plugin"
    color: root.textSoft
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    topPadding: Style.space(2)
  }

  readonly property bool hasSelfRow: {
    for (var i = 0; i < root.rows.length; i++) {
      if (root.rows[i] && root.rows[i].source === "self") return true
    }
    return false
  }
}
