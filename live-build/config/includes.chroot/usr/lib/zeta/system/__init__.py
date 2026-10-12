# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — system access (audio, network, Bluetooth, power) for the ZETA RAYS apps.

Simple, stateless functions that call the standard tools
(wpctl, nmcli, busctl, systemctl, loginctl). They never raise:
if something is missing they return empty values and the UI adapts.
"""
import os
import signal
import subprocess


def run(cmd, timeout=6, check=False):
    """Run a command; return its stdout ("" on error, None with check).

    When the timeout expires the whole process group is killed: no command
    is left hanging in the background.

    The stdout is read by apps, not people: system tools answer in English
    (LC_ALL=C.UTF-8) whatever language is selected (e.g. "nmcli radio wifi"
    prints "enabled", not its localized equivalent). ZETA programs (zeta-*)
    keep the user's language: they may show notifications.
    """
    env = None
    if not os.path.basename(str(cmd[0] if cmd else "")).startswith("zeta-"):
        env = dict(os.environ, LC_ALL="C.UTF-8", LANGUAGE="C")
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, text=True, start_new_session=True,
                             env=env)
    except OSError:
        return None if check else ""
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.communicate()
        return None if check else ""
    if check and p.returncode != 0:
        return None
    return out


def spawn(cmd):
    """Start a program detached from the app (does not wait)."""
    try:
        subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
