/* Barra laterale dell'installer ZETA RAYS: logo e passi dell'installazione.
   Sostituisce quella predefinita (che mostra il pulsante "Informazioni su"
   con i crediti del motore di installazione). */
import QtQuick
import QtQuick.Layouts
import io.calamares.ui 1.0
import io.calamares.core 1.0

Rectangle {
    id: sideBar
    color: "#000000"
    anchors.fill: parent

    ColumnLayout {
        anchors.fill: parent
        // Su schermi piccoli (800x600) Calamares stringe la barra a 100 px
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
                    text: display
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
