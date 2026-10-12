// ZETA RAYS — login screen (SDDM)
import QtQuick 2.15

Rectangle {
    id: root
    width: 1440
    height: 900
    color: "#000000"

    property color accent: config.accent || "#3A8DFF"
    // Text in English, in Italian if the system language is Italian
    // (SDDM passes the LANG from /etc/default/locale to the greeter).
    readonly property bool italian: Qt.locale().name.indexOf("it") === 0
    function t(en, it) { return italian ? it : en }
    // password visible while typing (eye icon in the field)
    property bool showPassword: false
    // Always the ZETA RAYS session (zeta.desktop): at the first login after
    // installation there is no "last session" yet, and index 0 could be another entry.
    property int zetaSession: -1
    property int sessionIndex: zetaSession >= 0 ? zetaSession
                               : (sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0)
    Repeater {
        model: sessionModel
        delegate: Item {
            Component.onCompleted: {
                if (String(model.file).indexOf("zeta") >= 0 && root.zetaSession < 0)
                    root.zetaSession = index
            }
        }
    }
    // Last user; on first boot, the first available user
    property string userName: userModel.lastUser !== "" ? userModel.lastUser
                              : (userModel.count > 0 ? userModel.data(userModel.index(0, 0), Qt.UserRole + 1) : "")
    // User picture (Settings › Account): SDDM gets it from AccountsService
    // (IconRole = UserRole + 4). The SDDM default one (/usr/share/sddm/faces)
    // is not used: the ZETA RAYS silhouette stays instead.
    property string userIcon: {
        for (var i = 0; i < userModel.count; ++i) {
            var idx = userModel.index(i, 0)
            if (userModel.data(idx, Qt.UserRole + 1) === root.userName) {
                var ic = String(userModel.data(idx, Qt.UserRole + 4) || "")
                if (ic === "" || ic.indexOf("/usr/share/sddm/") >= 0) return ""
                // SDDM may provide it as a path or already as «file://»
                return ic.indexOf("file:") === 0 ? ic : "file://" + ic
            }
        }
        return ""
    }

    // Solid black background, no glow and no logo: this is also the screen
    // shown when switching users, which must stay as neutral as the lock screen.

    // Time and date
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.17
        spacing: 6

        Text {
            id: clock
            anchors.horizontalCenter: parent.horizontalCenter
            color: "#EDEDEA"
            font.family: "Roboto"
            font.weight: Font.Light
            font.pixelSize: 112
            font.letterSpacing: -4
            text: Qt.formatTime(new Date(), "hh:mm")
        }
        Text {
            id: date
            anchors.horizontalCenter: parent.horizontalCenter
            color: "#8A8A8E"
            font.family: "Roboto"
            font.pixelSize: 17
            text: new Date().toLocaleDateString(Qt.locale(), "dddd d MMMM")
        }
        Timer {
            interval: 1000; running: true; repeat: true
            onTriggered: {
                clock.text = Qt.formatTime(new Date(), "hh:mm")
                date.text = new Date().toLocaleDateString(Qt.locale(), "dddd d MMMM")
            }
        }
    }

    // User and password
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.53
        spacing: 18

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 88; height: 88; radius: 44
            color: photo.status === Image.Ready ? "transparent" : "#19191C"
            border.color: photo.status === Image.Ready ? "transparent" : Qt.rgba(1, 1, 1, 0.1)
            // the image is already round (with transparency): no mask needed
            Image {
                id: photo
                anchors.fill: parent
                source: root.userIcon
                sourceSize: Qt.size(176, 176)
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                visible: status === Image.Ready
            }
            Image {
                anchors.centerIn: parent
                source: "icons/user.svg"
                width: 36; height: 36
                sourceSize: Qt.size(72, 72)
                opacity: 0.65
                visible: photo.status !== Image.Ready
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            color: "#EDEDEA"
            font.family: "Roboto"
            font.weight: Font.Medium
            font.pixelSize: 17
            text: root.userName
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8

            Rectangle {
                width: 264; height: 44; radius: 12
                color: Qt.rgba(1, 1, 1, 0.06)
                border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.35)

                TextInput {
                    id: password
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 44
                    verticalAlignment: TextInput.AlignVCenter
                    echoMode: root.showPassword ? TextInput.Normal : TextInput.Password
                    passwordCharacter: "●"
                    color: "#EDEDEA"
                    font.pixelSize: 14
                    font.letterSpacing: root.showPassword ? 0.5 : 3
                    cursorDelegate: Rectangle { width: 1.5; color: root.accent }
                    focus: true
                    Keys.onReturnPressed: root.doLogin()
                    Keys.onEnterPressed: root.doLogin()
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    visible: password.text.length === 0
                    color: "#6E6E73"
                    font.family: "Roboto"
                    font.pixelSize: 14
                    text: "Password"
                }
                // Show / Hide password
                Item {
                    id: eye
                    width: 36; height: 36
                    anchors.right: parent.right
                    anchors.rightMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    Image {
                        anchors.centerIn: parent
                        source: root.showPassword ? "icons/eye-off.svg" : "icons/eye.svg"
                        width: 18; height: 18
                        sourceSize: Qt.size(36, 36)
                        opacity: eyeArea.containsMouse ? 0.95 : 0.55
                    }
                    MouseArea {
                        id: eyeArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.showPassword = !root.showPassword
                            password.forceActiveFocus()
                        }
                    }
                }
            }

            Rectangle {
                width: 44; height: 44; radius: 12
                color: root.accent
                Image {
                    anchors.centerIn: parent
                    source: "icons/arrow.svg"
                    width: 20; height: 20
                    sourceSize: Qt.size(40, 40)
                }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.doLogin() }
            }
        }

        Text {
            id: hint
            anchors.horizontalCenter: parent.horizontalCenter
            color: "#6E6E73"
            font.family: "Roboto"
            font.pixelSize: 12
            text: root.t("Press Enter to sign in", "Premi Invio per accedere")  // i18n-data
        }
    }

    // Power
    Row {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 36
        anchors.bottomMargin: 28
        spacing: 18

        Repeater {
            model: [
                { icon: "moon", label: root.t("Suspend", "Sospendi"), action: "suspend" },  // i18n-data
                { icon: "restart", label: root.t("Restart", "Riavvia"), action: "reboot" },  // i18n-data
                { icon: "power", label: root.t("Shut Down", "Spegni"), action: "powerOff" }  // i18n-data
            ]
            delegate: Column {
                spacing: 8
                // suspend is disabled in virtual machines (they would not resume)
                visible: modelData.action !== "suspend" || sddm.canSuspend
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 44; height: 44; radius: 22
                    color: area.containsMouse ? Qt.rgba(1, 1, 1, 0.1) : Qt.rgba(1, 1, 1, 0.05)
                    border.color: Qt.rgba(1, 1, 1, 0.08)
                    Image {
                        anchors.centerIn: parent
                        source: "icons/" + modelData.icon + ".svg"
                        width: 18; height: 18
                        sourceSize: Qt.size(36, 36)
                        opacity: 0.65
                    }
                    MouseArea {
                        id: area
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (modelData.action === "suspend") sddm.suspend()
                            else if (modelData.action === "reboot") sddm.reboot()
                            else sddm.powerOff()
                        }
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: "#6E6E73"
                    font.family: "Roboto"
                    font.pixelSize: 11
                    text: modelData.label
                }
            }
        }
    }

    function doLogin() {
        hint.text = root.t("Signing in…", "Accesso in corso…")  // i18n-data
        sddm.login(root.userName, password.text, root.sessionIndex)
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            password.text = ""
            hint.color = "#FF6B6B"
            hint.text = root.t("Wrong password, try again", "Password errata, riprova")  // i18n-data
        }
    }
}
