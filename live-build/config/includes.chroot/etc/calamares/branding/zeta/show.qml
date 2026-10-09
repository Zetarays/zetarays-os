import QtQuick 2.0
import calamares.slideshow 1.0

Presentation {
    id: presentation
    // Sfondo nero su tutta l'area (altrimenti Qt la riempie di bianco)
    Rectangle { anchors.fill: parent; color: "#000000"; z: -1 }
    Timer { interval: 6000; running: true; repeat: true; onTriggered: presentation.goToNextSlide() }

    Slide {
        Rectangle { anchors.fill: parent; color: "#000000" }
        Image {
            id: logo; source: "logo.png"
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -30
            width: 190; fillMode: Image.PreserveAspectFit
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: logo.bottom; anchors.topMargin: 34
            // nella lingua scelta nell'installer (inglese per le lingue
            // in cui ZETA RAYS non e' tradotto)
            text: Qt.locale().name.indexOf("it") === 0 ? "Installazione di ZETA RAYS OS"
                                                        : "Installing ZETA RAYS OS"
            color: "#EDEDEA"; font.pixelSize: 20; font.family: "Roboto"
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: logo.bottom; anchors.topMargin: 66
            text: "AI · Security · Control"
            color: "#6E6E73"; font.pixelSize: 13; font.family: "Roboto"
        }
    }
}
