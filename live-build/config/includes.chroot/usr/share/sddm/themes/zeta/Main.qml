// ZETA RAYS — login screen (SDDM)
import QtQuick 2.15

Rectangle {
    id: root
    width: 1440
    height: 900
    color: "#000000"

    property color accent: config.accent || "#3A8DFF"

    // 3.5: the release wallpaper behind the login (theme.conf "background"),
    // darkened so the name, the password field and the buttons stay
    // readable on it. Loaded at screen size (sourceSize), not the 4K original;
    // missing or unreadable: the plain black of before.
    Image {
        id: wallpaper
        anchors.fill: parent
        z: -2
        source: config.background ? "file://" + config.background : ""
        sourceSize.width: 2560
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        visible: status === Image.Ready
    }
    Rectangle {
        anchors.fill: parent
        z: -1
        color: "#000000"
        opacity: 0.55
        visible: wallpaper.visible
    }
    // Text in English (qsTr), translated by SDDM with the theme's Qt
    // translations (translations/<language>.qm, see metadata.desktop) in the
    // system language: SDDM passes the LANG from /etc/default/locale to the
    // greeter. Sources: tools/qt-lang.
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
    property string userName: defaultUser()
    // User picture (Settings › Account): SDDM gets it from AccountsService
    // (IconRole = UserRole + 4). The SDDM default one (/usr/share/sddm/faces)
    // is not used: the ZETA RAYS silhouette stays instead.
    property string userIcon: iconOf(root.userName)

    // --- Switch user -------------------------------------------------------
    // "Switch user" under the name opens the list of the users SDDM shows
    // (userModel, the accounts with UID >= 1000) plus "Other user…", which
    // turns the name into a text field: any account can be typed there,
    // root included when Settings › Account allows signing in as root.
    property bool otherUser: false        // the name is typed by hand
    property bool listOpen: false
    property var listEntries: []          // [{name, label, detail, icon, other}]

    // The last user when SDDM lists it, otherwise the first listed one: a
    // name typed with "Other user…" (root, for example) is never offered by
    // itself at the next start. No listed user at all: the name field.
    function defaultUser() {
        var first = ""
        for (var i = 0; i < userModel.count; ++i) {
            var name = String(userModel.data(userModel.index(i, 0), Qt.UserRole + 1) || "")
            if (first === "") first = name
            if (name !== "" && name === userModel.lastUser) return name
        }
        return first !== "" ? first : (userModel.lastUser !== "root" ? userModel.lastUser : "")
    }
    Component.onCompleted: {
        if (root.userName === "") {
            root.otherUser = true
            startFocus.start()
        }
    }
    // focus to the name field once the screen is shown (at creation the
    // password field's "focus: true" would win)
    Timer { id: startFocus; interval: 50; onTriggered: nameField.forceActiveFocus() }

    function iconOf(name) {
        for (var i = 0; i < userModel.count; ++i) {
            var idx = userModel.index(i, 0)
            if (userModel.data(idx, Qt.UserRole + 1) === name) {
                var ic = String(userModel.data(idx, Qt.UserRole + 4) || "")
                if (ic === "" || ic.indexOf("/usr/share/sddm/") >= 0) return ""
                // SDDM may provide it as a path or already as «file://»
                return ic.indexOf("file:") === 0 ? ic : "file://" + ic
            }
        }
        return ""
    }

    function resetHint() {
        hint.color = "#6E6E73"
        hint.text = qsTr("Press Enter to sign in")
    }

    function openUserList() {
        var entries = []
        var current = 0
        for (var i = 0; i < userModel.count; ++i) {
            var idx = userModel.index(i, 0)
            var name = String(userModel.data(idx, Qt.UserRole + 1) || "")
            if (name === "") continue
            var real = String(userModel.data(idx, Qt.UserRole + 2) || "")
            if (!root.otherUser && name === root.userName) current = entries.length
            entries.push({ name: name, label: real !== "" ? real : name,
                           detail: (real !== "" && real !== name) ? name : "",
                           icon: iconOf(name), other: false })
        }
        entries.push({ name: "", label: qsTr("Other user…"), detail: "", icon: "", other: true })
        if (root.otherUser) current = entries.length - 1
        root.listEntries = entries
        // below the name when there is room, otherwise above it
        var bottom = nameArea.mapToItem(root, 0, nameArea.height).y
        userList.below = bottom + 8 + userList.height <= root.height - 100
        userView.currentIndex = current
        root.listOpen = true
        userView.forceActiveFocus()
    }

    function closeUserList() {
        if (!root.listOpen) return
        root.listOpen = false
        if (root.otherUser) nameField.forceActiveFocus()
        else password.forceActiveFocus()
    }

    function chooseEntry(i) {
        var e = root.listEntries[i]
        if (!e) return
        root.listOpen = false
        password.text = ""
        root.showPassword = false
        resetHint()
        if (e.other) {
            root.otherUser = true
            nameField.text = ""
            root.userName = ""
            nameField.forceActiveFocus()
        } else {
            root.otherUser = false
            root.userName = e.name
            password.forceActiveFocus()
        }
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

    // A click anywhere outside the user list closes it
    MouseArea {
        anchors.fill: parent
        z: 5
        visible: root.listOpen
        onClicked: root.closeUserList()
    }

    // User and password
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.53
        z: 6                 // above the click catcher: the list stays usable
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

        // Name (or the field for another user's name) and "Switch user"
        Item {
            id: nameArea
            anchors.horizontalCenter: parent.horizontalCenter
            width: 316
            height: nameColumn.height
            z: 10            // the list opens over the password field

            Column {
                id: nameColumn
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 6

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: !root.otherUser
                    color: "#EDEDEA"
                    font.family: "Roboto"
                    font.weight: Font.Medium
                    font.pixelSize: 17
                    text: root.userName
                }

                // "Other user…": the name is typed here
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: root.otherUser
                    width: 264; height: 40; radius: 12
                    color: Qt.rgba(1, 1, 1, 0.06)
                    border.color: nameField.activeFocus
                                  ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.6)
                                  : Qt.rgba(1, 1, 1, 0.12)
                    TextInput {
                        id: nameField
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        verticalAlignment: TextInput.AlignVCenter
                        horizontalAlignment: TextInput.AlignHCenter
                        color: "#EDEDEA"
                        font.family: "Roboto"
                        font.weight: Font.Medium
                        font.pixelSize: 16
                        maximumLength: 64
                        inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                        // only the focused field shows its cursor (two fields now)
                        cursorDelegate: Rectangle { width: 1.5; color: root.accent; visible: nameField.activeFocus }
                        onTextChanged: if (root.otherUser) root.userName = text.trim()
                        Keys.onReturnPressed: password.forceActiveFocus()
                        Keys.onEnterPressed: password.forceActiveFocus()
                        Keys.onTabPressed: password.forceActiveFocus()
                        Keys.onEscapePressed: root.cancelOtherUser()
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: nameField.text.length === 0
                        color: "#6E6E73"
                        font.family: "Roboto"
                        font.pixelSize: 14
                        text: qsTr("User name")
                    }
                }

                // "Switch user": discreet, in the accent color
                Item {
                    id: switchLink
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: switchRow.width + 16
                    height: 24
                    activeFocusOnTab: true
                    Rectangle {
                        anchors.fill: parent
                        radius: 8
                        color: switchArea.containsMouse || switchLink.activeFocus || root.listOpen
                               ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.14)
                               : "transparent"
                    }
                    Row {
                        id: switchRow
                        anchors.centerIn: parent
                        spacing: 6
                        Image {
                            anchors.verticalCenter: parent.verticalCenter
                            source: "icons/users.svg"
                            width: 14; height: 14
                            sourceSize: Qt.size(28, 28)
                            opacity: 0.7
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.accent
                            font.family: "Roboto"
                            font.pixelSize: 12
                            text: qsTr("Switch user")
                        }
                    }
                    MouseArea {
                        id: switchArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.listOpen ? root.closeUserList() : root.openUserList()
                    }
                    Keys.onReturnPressed: root.openUserList()
                    Keys.onEnterPressed: root.openUserList()
                    Keys.onSpacePressed: root.openUserList()
                    KeyNavigation.tab: password
                    KeyNavigation.backtab: password
                }
            }

            // The list of users
            Rectangle {
                id: userList
                property bool below: true
                visible: root.listOpen
                anchors.horizontalCenter: parent.horizontalCenter
                y: below ? parent.height + 8 : -height - 8
                width: 300
                height: Math.min(root.listEntries.length, 5) * 52 + 12
                radius: 14
                color: "#141417"
                border.color: Qt.rgba(1, 1, 1, 0.1)

                ListView {
                    id: userView
                    anchors.fill: parent
                    anchors.margins: 6
                    clip: true
                    model: root.listEntries
                    keyNavigationEnabled: false
                    onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                    boundsBehavior: Flickable.StopAtBounds
                    Keys.onUpPressed: currentIndex = Math.max(0, currentIndex - 1)
                    Keys.onDownPressed: currentIndex = Math.min(count - 1, currentIndex + 1)
                    Keys.onReturnPressed: root.chooseEntry(currentIndex)
                    Keys.onEnterPressed: root.chooseEntry(currentIndex)
                    Keys.onSpacePressed: root.chooseEntry(currentIndex)
                    Keys.onEscapePressed: root.closeUserList()
                    Keys.onTabPressed: root.closeUserList()

                    delegate: Rectangle {
                        width: userView.width
                        height: 52
                        radius: 10
                        color: index === userView.currentIndex
                               ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.18)
                               : (rowArea.containsMouse ? Qt.rgba(1, 1, 1, 0.05) : "transparent")

                        Rectangle {
                            id: face
                            anchors.left: parent.left
                            anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            width: 34; height: 34; radius: 17
                            color: facePhoto.status === Image.Ready ? "transparent" : "#1F1F23"
                            border.color: facePhoto.status === Image.Ready ? "transparent" : Qt.rgba(1, 1, 1, 0.1)
                            Image {
                                id: facePhoto
                                anchors.fill: parent
                                source: modelData.icon
                                sourceSize: Qt.size(68, 68)
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                mipmap: true
                                visible: status === Image.Ready
                            }
                            Image {
                                anchors.centerIn: parent
                                source: modelData.other ? "icons/user-other.svg" : "icons/user.svg"
                                width: 16; height: 16
                                sourceSize: Qt.size(32, 32)
                                opacity: 0.65
                                visible: facePhoto.status !== Image.Ready
                            }
                        }
                        Column {
                            anchors.left: face.right
                            anchors.leftMargin: 12
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2
                            Text {
                                width: parent.width
                                elide: Text.ElideRight
                                color: "#EDEDEA"
                                font.family: "Roboto"
                                font.pixelSize: 14
                                text: modelData.label
                            }
                            Text {
                                width: parent.width
                                visible: modelData.detail !== ""
                                elide: Text.ElideRight
                                color: "#8A8A8E"
                                font.family: "Roboto"
                                font.pixelSize: 11
                                text: modelData.detail
                            }
                        }
                        MouseArea {
                            id: rowArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onEntered: userView.currentIndex = index
                            onClicked: root.chooseEntry(index)
                        }
                    }
                }
            }
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
                    cursorDelegate: Rectangle { width: 1.5; color: root.accent; visible: password.activeFocus }
                    focus: true
                    Keys.onReturnPressed: root.doLogin()
                    Keys.onEnterPressed: root.doLogin()
                    KeyNavigation.tab: switchLink
                    KeyNavigation.backtab: root.otherUser ? nameField : switchLink
                    // a click on the field while the user list is open closes it
                    onActiveFocusChanged: if (activeFocus) root.listOpen = false
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
            text: qsTr("Press Enter to sign in")
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
                { icon: "moon", label: qsTr("Suspend"), action: "suspend" },
                { icon: "restart", label: qsTr("Restart"), action: "reboot" },
                { icon: "power", label: qsTr("Shut Down"), action: "powerOff" }
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

    // Escape in the "Other user…" field: back to the usual user
    function cancelOtherUser() {
        var name = defaultUser()
        if (name === "") return          // nobody else to go back to
        root.otherUser = false
        root.userName = name
        password.text = ""
        resetHint()
        password.forceActiveFocus()
    }

    function doLogin() {
        if (root.userName === "") {
            hint.color = "#FF6B6B"
            hint.text = qsTr("Type a user name")
            if (root.otherUser) nameField.forceActiveFocus()
            return
        }
        hint.color = "#6E6E73"
        hint.text = qsTr("Signing in…")
        sddm.login(root.userName, password.text, root.sessionIndex)
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            password.text = ""
            hint.color = "#FF6B6B"
            hint.text = qsTr("Wrong password, try again")
        }
    }
}
