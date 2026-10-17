# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS release information, read from /etc/os-release.

The version is written there at build time (hook 0100, from the repository's
VERSION file): the apps never hard-code it.
"""

OS_RELEASE = "/etc/os-release"


def os_release(path: str = OS_RELEASE) -> dict:
    """The os-release fields as a dict ({} if the file cannot be read)."""
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    data[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return data


def version() -> str:
    """The release version (e.g. "2.1"), "" when unknown."""
    return os_release().get("VERSION_ID", "")


def product_token() -> str:
    """The HTTP User-Agent product token: "ZETA-RAYS/<version>"."""
    v = version()
    return "ZETA-RAYS/" + v if v else "ZETA-RAYS"
