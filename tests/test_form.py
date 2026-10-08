"""The form the installer asks where things go with."""

from __future__ import annotations

from cloudmorrow.form import Field, Form, fill, main
from tests.test_checklist import ANSI, on_a_terminal

PLACES = [
    ("code", "Code", "/opt/cloudmorrow", "the checkout and the virtualenv"),
    ("config", "Settings", "/etc/cloudmorrow", "server.toml and the sealing key"),
    ("data", "Data", "/var/lib/cloudmorrow", "the database, keys and quills"),
    ("notes", "Notes", "/srv/cloudmorrow/notes", "every note and file"),
]


def places() -> Form:
    return Form(
        "Where should it go?",
        [Field(*place) for place in PLACES],
        pattern=r"/\S*",
        problem="an absolute path, please",
        colour=False,
    )


def test_enter_takes_the_defaults():
    values, drawn = on_a_terminal(b"\r", lambda t: fill(places(), t))
    assert values == {key: default for key, _, default, _ in PLACES}
    # Every label, default and detail is on the screen.
    for _, label, default, detail in PLACES:
        assert label in drawn and default in drawn and detail in drawn


def test_backspace_edits_the_end_of_the_default():
    typed = b"\x7f" * len("cloudmorrow") + b"cm\x1b[B\x1b[B\x1b[B" + b"\x7f" * 5 + b"pages\r"
    values, _ = on_a_terminal(typed, lambda t: fill(places(), t))
    assert values["code"] == "/opt/cm"
    assert values["notes"] == "/srv/cloudmorrow/pages"
    assert values["data"] == "/var/lib/cloudmorrow"


def test_ctrl_u_puts_the_default_back():
    values, _ = on_a_terminal(b"\x7f\x7f\x7fnope\x15\r", lambda t: fill(places(), t))
    assert values["code"] == "/opt/cloudmorrow"


def test_a_relative_path_is_refused_on_its_row():
    typed = b"\x1b[B" + b"\x7f" * len("/etc/cloudmorrow") + b"etc\r" + b"\x15\r"
    values, drawn = on_a_terminal(typed, lambda t: fill(places(), t))
    assert "Settings: an absolute path, please" in drawn
    assert values["config"] == "/etc/cloudmorrow"


def test_two_fields_at_the_same_place_are_refused():
    typed = b"\x1b[B" + b"\x7f" * len("/etc/cloudmorrow") + b"/opt/cloudmorrow/\r" + b"\x15\r"
    values, drawn = on_a_terminal(typed, lambda t: fill(places(), t))
    assert "Settings and Code are the same place" in drawn
    assert values["config"] == "/etc/cloudmorrow"


def test_no_line_is_wider_than_a_narrow_terminal():
    fields = [Field(str(n), f"Place {n}", f"/a/long/path/that/goes/on/{n}", "and a detail " * 3) for n in range(20)]
    form = Form("Where should it go?", fields, colour=False)
    _, drawn = on_a_terminal(b"\x1b[B" * 15 + b"\r", lambda t: fill(form, t), columns=32, rows=12)
    for line in ANSI.sub("", drawn).replace("\r", "\n").split("\n"):
        assert len(line) < 32, line
    assert "↑ more" in drawn


def test_the_command_prints_one_key_and_value_a_line(capsys):
    def run(terminal):
        args = ["--title", "Where?", "--terminal", terminal, "--pattern", r"/\S*"]
        for place in PLACES[:2]:
            args += ["--field", *place]
        return main(args)

    code, _ = on_a_terminal(b"\x7f\x7f\x7fx\r", run)
    assert code == 0
    assert capsys.readouterr().out == "code=/opt/cloudmorx\nconfig=/etc/cloudmorrow\n"
