# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA WATCH: the words for an event, in the user's language.

describe(event) -> (title, text, advice). Used by the notifications
(zeta-watch-notify) and by the history in Settings › ZETA WATCH, so both
say the same thing. The texts say what was seen, not more: "failed
passwords", not "an attack"; a scan warning is "worth a look", because these
tools also report harmless things.
"""
from i18n import ntr, tr

def severity_name(sev):
    return {"info": tr("Information"), "notice": tr("Notice"), "warning": tr("Warning"),
            "critical": tr("Critical")}.get(sev, sev)


def _where(p):
    return tr("from the local network") if p.get("local") else tr("from the internet")


def describe(e):
    code, p, n = e.get("code", ""), e.get("params", {}) or {}, int(e.get("count", 1) or 1)
    if code == "ssh_failed":
        return (tr("Failed SSH logins"),
                ntr("{n} failed SSH login for “{user}” from {address} ({where}).",
                    "{n} failed SSH logins for “{user}” from {address} ({where}).", n).format(
                    n=n, user=p.get("user") or "?", address=p.get("address", "?"), where=_where(p)),
                tr("If it was not you, nothing to do: addresses that keep trying are blocked for a while. "
                   "Use a strong password, or turn off remote SSH in Settings › Wi-Fi & Network."))
    if code in ("ssh_login", "ssh_login_root"):
        return (tr("SSH login as root") if code == "ssh_login_root" else tr("SSH login"),
                tr("“{user}” logged in with SSH from {address} ({where}).").format(
                    user=p.get("user", "?"), address=p.get("address", "?"), where=_where(p)),
                tr("If you do not recognize it: change that user's password at once and turn SSH off "
                   "in Settings › Wi-Fi & Network."))
    if code == "address_blocked":
        return (tr("Address blocked"),
                tr("{address} was blocked for {minutes} minutes after {attempts} failed SSH passwords.").format(
                    address=p.get("address", "?"), minutes=p.get("minutes", "?"), attempts=p.get("attempts", "?")),
                tr("Connections already open are not affected. Settings › ZETA WATCH can unblock it."))
    if code == "ssh_rejected":
        return (tr("SSH connection refused"),
                ntr("The firewall refused {n} SSH connection from {address}: SSH is off or limited to the local network.",
                    "The firewall refused {n} SSH connections from {address}: SSH is off or limited to the local network.",
                    n).format(n=n, address=p.get("address", "?")),
                tr("Nothing to do: the firewall is doing its job."))
    if code == "login_failed":
        what = {"login": tr("at the login screen"), "lock": tr("on the lock screen"), "su": tr("with su"),
                "sudo": tr("for an administrator command"), "admin": tr("in an administrator prompt")}.get(
            p.get("kind"), tr("({service})").format(service=p.get("service", "?")))
        return (tr("Wrong password"),
                ntr("{n} wrong password for “{user}” {what}.", "{n} wrong passwords for “{user}” {what}.", n).format(
                    n=n, user=p.get("user") or "?", what=what),
                tr("If it was not you, someone tried to use this computer."))
    if code == "root_login":
        return (tr("Root logged in"),
                tr("Someone logged in as root ({service}).").format(service=p.get("service", "?")),
                tr("Root has every right on the system. If it was not you, change the root password and turn "
                   "root sign-in off in Settings › Account."))
    if code == "root_su":
        return (tr("Root terminal opened"), tr("“{user}” became root with su.").format(user=p.get("by", "?")), "")
    if code in ("sudo_failed", "sudo_denied"):
        return (tr("Administrator command refused"),
                tr("“{user}” tried an administrator command and was refused.").format(user=p.get("user", "?")),
                tr("If it was not you, someone tried to get administrator rights."))
    if code == "sudo_command":
        return (tr("Administrator command"),
                tr("“{user}” ran as {target}: {command}").format(
                    user=p.get("user", "?"), target=p.get("target", "root"), command=p.get("command", "")), "")
    if code == "user_created":
        return (tr("New user account"),
                tr("The account “{user}” was created.").format(user=p.get("user", "?")),
                tr("If you did not create it, remove it in Settings › Account and check who has administrator rights."))
    if code == "user_deleted":
        return (tr("User account removed"), tr("The account “{user}” was removed.").format(user=p.get("user", "?")), "")
    if code == "admin_granted":
        return (tr("Administrator rights given"),
                tr("“{user}” was added to the group “{group}”, which gives administrator rights.").format(
                    user=p.get("user", "?"), group=p.get("group", "?")),
                tr("If you did not do it, remove the user from that group at once."))
    if code == "group_added":
        return (tr("Group membership"), tr("“{user}” was added to the group “{group}”.").format(
            user=p.get("user", "?"), group=p.get("group", "?")), "")
    if code == "password_changed":
        return (tr("Password changed"), tr("The password of “{user}” was changed.").format(user=p.get("user", "?")),
                tr("If you did not change it, change it again now."))
    if code == "file_changed":
        kind = {"accounts": tr("user accounts"), "privilege": tr("administrator rights"),
                "login": tr("how people log in"), "ssh": tr("SSH access"),
                "persistence": tr("programs that start by themselves"),
                "rootkit": tr("a file used by rootkits")}.get(p.get("kind"), p.get("kind", "?"))
        return (tr("Important file changed"),
                tr("{path} ({kind}) was changed by {program}.").format(
                    path=p.get("path", "?"), kind=kind, program=p.get("program", "?")),
                tr("Changes made by updates are not reported. If you did not make this one, check the file.")
                if p.get("kind") != "rootkit" else
                tr("This file is almost never used on a normal system: check it at once (sudo cat /etc/ld.so.preload)."))
    if code == "kernel_module":
        return (tr("Kernel module loaded by hand"),
                tr("{program} loaded a kernel module.").format(program=p.get("program", "?")), "")
    if code == "new_listener":
        return (tr("New open port"),
                tr("“{program}” is now waiting for connections on port {port} ({proto}).").format(
                    program=p.get("program", "?"), port=p.get("port", "?"), proto=p.get("proto", "")),
                tr("The firewall still decides who can reach it. If you did not start this program, close it."))
    if code == "unusual_connection":
        return (tr("Unusual connection"),
                tr("{program} connected to {address}, port {port}.").format(
                    program=p.get("program", "?"), address=p.get("address", "?"), port=p.get("port", "?")),
                tr("Often harmless (games, chat, developer tools). Worth a look if you do not know the program."))
    if code in ("process_from_temp", "process_deleted_binary"):
        return (tr("Program from an unusual place"),
                (tr("A program is running from a temporary folder: {program}") if code == "process_from_temp"
                 else tr("A program is running although its file was deleted: {program}")).format(
                    program=p.get("program", "?")),
                tr("Malware often does this. If you do not know it, end it in the System Monitor and check the folder."))
    if code == "service_enabled":
        return (tr("New service enabled"),
                tr("“{unit}” will now start by itself.").format(unit=p.get("unit", "?")),
                tr("Installing software does this. If you did not install anything, check it with "
                   "systemctl status {unit}.").format(unit=p.get("unit", "?")))
    if code == "firewall_changed":
        return (tr("Firewall rules changed"), tr("The firewall rules are different from before."),
                tr("Settings that open or close access (SSH, sharing) do this."))
    if code == "scan_warning":
        return (tr("Security check: worth a look"),
                ntr("{tool} reported {n} item.", "{tool} reported {n} items.", int(p.get("count", 0))).format(
                    tool=p.get("tool", "?"), n=p.get("count", 0)),
                tr("These tools also report harmless things: read the details in Settings › ZETA WATCH."))
    if code == "scan_done":
        return (tr("Security check finished"),
                ntr("{n} item to look at.", "{n} items to look at.", int(p.get("warnings", 0))).format(
                    n=p.get("warnings", 0)), "")
    if code == "ids_alert":
        return (tr("Network alert (Suricata)"),
                tr("{signature}: {source} → {target}").format(
                    signature=p.get("signature", "?"), source=p.get("source", "?"), target=p.get("target", "?")),
                tr("Suricata compares network traffic with known attack patterns; some alerts are harmless."))
    if code == "watch_started":
        return (tr("Monitoring started"), tr("Security monitoring is on."), "")
    if code == "watch_test":
        return (tr("Test alert"), tr("Alerts reach you. Nothing happened."), "")
    return (code, "", "")
