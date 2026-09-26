"""The desktop app: the web app in a window of its own, with the machine behind it.

The web app is the interface, on a phone and in a browser alike, and the
desktop app does not draw a second one. What it adds is the part a browser
tab is not allowed to do: mount a share on this computer, open the folder it
landed in, say whether this machine's agent is running. The window is the
operating system's own web view (pywebview: WebView2 on Windows, WKWebView on
a Mac, Qt WebEngine on Linux), and the page talks to the client code running
beside it through one object, `bridge.Bridge`, which is the same code the
command line runs — `client.mounts`, `client.rclone`, `agent.setup`.

    app.py       opens the window, and hands the sign-in across
    bridge.py    what the page may ask of this machine
    system.py    the few things that differ per operating system
    launcher.py  the entry in the applications menu

Nothing here is imported by the rest of the client, and pywebview is only
imported when a window is actually opened, so a machine without the
`desktop` extra is a perfectly good terminal client.
"""
