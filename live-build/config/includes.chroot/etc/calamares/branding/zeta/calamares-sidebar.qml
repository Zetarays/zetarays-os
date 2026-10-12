/* Sidebar of the ZETA RAYS installer: logo and installation steps.
   Replaces the default one (which shows an "About" button with the
   credits of the installer engine). */
import QtQuick
import QtQuick.Layouts
import io.calamares.ui 1.0
import io.calamares.core 1.0

Rectangle {
    id: sideBar
    color: "#000000"
    anchors.fill: parent

    // The installer translates the step names, but the model does not notify
    // the sidebar when the language changes: they stayed in English with the
    // installer in Italian. They are re-read continuously (eight strings, no
    // visible cost).
    property int tick: 0
    Timer { interval: 500; running: true; repeat: true; onTriggered: sideBar.tick++ }
    function stepName(i, fallback) {
        void(sideBar.tick)
        var v = ViewManager.data(ViewManager.index(i, 0))
        return v ? v : fallback
    }

    ColumnLayout {
        anchors.fill: parent
        // On small screens (800x600) Calamares shrinks the sidebar to 100 px
        anchors.leftMargin: sideBar.width < 150 ? 6 : 16
        anchors.rightMargin: sideBar.width < 150 ? 6 : 16
        anchors.topMargin: 22
        anchors.bottomMargin: 16
        spacing: 4

        Image {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: Math.min(92, sideBar.width - 20)
            Layout.preferredHeight: Math.min(92, sideBar.width - 20)
            Layout.bottomMargin: 26
            source: "file:/" + Branding.imagePath(Branding.ProductLogo)
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
        }

        Repeater {
            model: ViewManager
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                radius: 8
                color: index == ViewManager.currentStepIndex ? "#16161A" : "transparent"
                border.width: index == ViewManager.currentStepIndex ? 1 : 0
                border.color: "#2A2A30"

                Rectangle {
                    visible: index == ViewManager.currentStepIndex
                    width: 3; height: 14; radius: 2
                    color: "#3A8DFF"
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: sideBar.width < 150 ? 16 : 20
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    elide: Text.ElideRight
                    text: sideBar.stepName(index, display)
                    font.family: "Roboto"
                    font.pixelSize: sideBar.width < 150 ? 12 : 13
                    font.weight: index == ViewManager.currentStepIndex ? Font.Medium : Font.Normal
                    color: index == ViewManager.currentStepIndex ? "#EDEDEA"
                         : (index < ViewManager.currentStepIndex ? "#A1A1A6" : "#6E6E73")
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
