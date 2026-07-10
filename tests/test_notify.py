import jotd.notify as notify


def test_stdout_channel(capsys):
    used = notify.send("jotd", "hello", channel="stdout")
    assert used == "stdout"
    assert "[jotd] hello" in capsys.readouterr().out


def test_osascript_escaping(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.shutil, "which", lambda _: None)
    monkeypatch.setattr(notify.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or None)
    notify.send("jotd", 'say "hi" \\ and\nnewline', channel="macos")
    (cmd,) = calls
    assert cmd[0] == "osascript"
    script = cmd[2]
    # the message must arrive as a single escaped AppleScript string literal
    assert script.startswith("display notification ")
    assert '\\"hi\\"' in script and "\\n" in script


def test_terminal_notifier_preferred(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.shutil, "which", lambda _: "/opt/homebrew/bin/terminal-notifier")
    monkeypatch.setattr(notify.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or None)
    used = notify.send("jotd", "msg", channel="macos")
    assert used == "terminal-notifier"
    assert calls[0][0] == "terminal-notifier"
