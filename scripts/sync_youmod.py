#!/usr/bin/env python3
"""Sync youmod.json with upstream, verifying the IPA before publishing it.

Upstream rotates release tags and deletes the old assets, so a pinned
downloadURL goes dead roughly weekly. This re-points ours at the current
release, but only after confirming the file actually downloads and matches
what the metadata claims.

Fields we deliberately do NOT copy from upstream:
  - appPermissions  upstream ships shapes AltStore cannot decode
  - sourceURL       must point at this repo
  - minOSVersion    upstream understates it; we read the binary instead
"""

import hashlib
import json
import pathlib
import plistlib
import sys
import urllib.request
import zipfile

UPSTREAM = "https://raw.githubusercontent.com/mrdrvt99/Altstore-Repository/main/youmod.json"
LOCAL = pathlib.Path(__file__).resolve().parent.parent / "youmod.json"
INFO_PLIST = "Payload/YouTube.app/Info.plist"


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def url_ok(url):
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status == 200
    except Exception:
        return False


def normalize(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def inspect_ipa(blob):
    """Return (sha256, size, bundle_id, version, min_os) read from the IPA itself."""
    path = pathlib.Path("/tmp/youmod-sync.ipa")
    path.write_bytes(blob)
    try:
        with zipfile.ZipFile(path) as z:
            info = plistlib.loads(z.read(INFO_PLIST))
            for name in (n for n in z.namelist() if n.endswith(".plist")):
                try:
                    plistlib.loads(z.read(name))
                except Exception:
                    fail(f"bundled plist does not parse: {name}")
    except zipfile.BadZipFile:
        fail("downloaded file is not a valid IPA (got HTML or a truncated file?)")
    finally:
        path.unlink(missing_ok=True)

    return (
        hashlib.sha256(blob).hexdigest(),
        len(blob),
        info["CFBundleIdentifier"],
        info["CFBundleShortVersionString"],
        info["MinimumOSVersion"],
    )


def main():
    local = json.loads(LOCAL.read_text())
    app = local["apps"][0]
    up = json.loads(fetch(UPSTREAM))["apps"][0]

    if up["downloadURL"] == app["downloadURL"]:
        if url_ok(app["downloadURL"]):
            print(f"up to date: {app['version']}")
            return
        fail(
            f"current downloadURL is dead and upstream has no replacement yet:\n"
            f"  {app['downloadURL']}"
        )

    print(f"upstream moved: {app['version']} -> {up['version']}")
    print(f"  {up['downloadURL']}")

    blob = fetch(up["downloadURL"])
    sha, size, bundle_id, version, min_os = inspect_ipa(blob)

    if bundle_id != app["bundleIdentifier"]:
        fail(f"bundle id changed: {app['bundleIdentifier']} -> {bundle_id}")
    if version != up["version"]:
        fail(f"IPA says {version}, upstream metadata says {up['version']}")
    if size != up["size"]:
        fail(f"downloaded {size} bytes, upstream declares {up['size']}")

    desc = normalize(up["versionDescription"])
    app.update(
        version=version,
        versionDate=up["versionDate"],
        versionDescription=desc,
        downloadURL=up["downloadURL"],
        size=size,
        sha256=sha,
    )
    app["versions"] = [
        {
            "version": version,
            "date": up["versionDate"],
            "localizedDescription": desc,
            "downloadURL": up["downloadURL"],
            "size": size,
            "sha256": sha,
            "minOSVersion": min_os,
        }
    ]

    LOCAL.write_text(json.dumps(local, indent=2, ensure_ascii=False) + "\n")
    print(f"updated to {version} (sha256 {sha[:12]}..., minOSVersion {min_os})")


if __name__ == "__main__":
    main()
