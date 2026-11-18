"""The photo kit's sums (quill/photo.py): what every surface works out the same way."""

from __future__ import annotations

import pytest

from cloudmorrow.quill import photo as ph

LANDSCAPE = {"width": 4000, "height": 3000}


# -- turning ----------------------------------------------------------------------------
@pytest.mark.parametrize(("said", "turn"), [(0, 0), (90, 90), ("270", 270), (450, 90), (-90, 270), ("x", 0), (100, 90)])
def test_a_turn_is_a_quarter_turn_clockwise(said, turn):
    assert ph.rotation_of({"rotate": said}) == turn


def test_a_quarter_turn_swaps_the_sides():
    assert ph.turned(4000, 3000, 90) == (3000, 4000)
    assert ph.turned(4000, 3000, 180) == (4000, 3000)
    assert ph.picture_size({**LANDSCAPE, "rotate": 270}) == (3000, 4000)
    assert ph.picture_size({"rotate": 90}) is None


# -- the crop and the size --------------------------------------------------------------
def test_a_crop_is_kept_inside_the_picture_and_never_tiny():
    assert ph.crop_of({}) == ph.WHOLE
    assert ph.crop_of({"crop": {"x": 10, "y": 10, "w": 80, "h": 80}}) == {"x": 10, "y": 10, "w": 80, "h": 80}
    assert ph.crop_of({"crop": {"x": 98, "y": -5, "w": 1, "h": 200}}) == {"x": 95, "y": 0, "w": 5, "h": 100}
    assert ph.crop_of({"crop": "junk"}) == ph.WHOLE


def test_the_cropped_size_follows_the_turn_and_the_crop():
    assert ph.cropped_size(LANDSCAPE) == (4000, 3000)
    assert ph.cropped_size({**LANDSCAPE, "rotate": 90, "crop": {"x": 0, "y": 0, "w": 50, "h": 25}}) == (1500, 1000)
    assert ph.cropped_size({}) is None


def test_the_output_is_the_cropped_size_unless_told():
    assert ph.output_size(LANDSCAPE) == (4000, 3000)
    assert ph.output_size({**LANDSCAPE, "out_width": 1000}) == (1000, 750)
    assert ph.output_size({**LANDSCAPE, "out_height": 300}) == (400, 300)
    assert ph.output_size({**LANDSCAPE, "out_width": 100, "out_height": 100}) == (100, 100)
    # Both given, nothing else known: still a size.
    assert ph.output_size({"out_width": 10, "out_height": 20}) == (10, 20)
    assert ph.output_size({"out_width": 10}) is None
    assert ph.size_said(LANDSCAPE) == "4000 × 3000" and ph.size_said({}) == ""


@pytest.mark.parametrize(
    ("typed", "fields"),
    [
        ("1920x1080", {"out_width": 1920, "out_height": 1080}),
        ("1920 × 1080", {"out_width": 1920, "out_height": 1080}),
        ("1920", {"out_width": 1920, "out_height": None}),
        ("50%", {"out_width": 2000, "out_height": 1500}),
        ("as is", {"out_width": None, "out_height": None}),
        ("", {"out_width": None, "out_height": None}),
    ],
)
def test_a_size_is_typed_as_a_pair_a_width_a_percent_or_nothing(typed, fields):
    assert ph.size_from(typed, (4000, 3000)) == fields


@pytest.mark.parametrize("typed", ["big", "0x10", "99999", "50%x", "5000%"])
def test_a_size_that_is_not_one_is_refused(typed):
    with pytest.raises(ValueError):
        ph.size_from(typed, (4000, 3000))


def test_a_percent_needs_the_picture_size():
    with pytest.raises(ValueError, match="not known"):
        ph.size_from("50%", None)


# -- texts ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("said", "hex_"), [("#fff", "#ffffff"), ("ABCDEF", "#abcdef"), ("amber", "#f0a81e"), ("", None), ("#12", None)]
)
def test_a_colour_is_hex_or_a_name(said, hex_):
    assert ph.colour_from(said) == hex_


def test_a_text_has_the_kits_defaults_and_stays_inside():
    assert ph.text_of({"text": "Hi"}) == {"text": "Hi", "x": 6.0, "y": 6.0, "size": 6.0, "colour": "#ffffff"}
    said = ph.text_of({"text": "Hi", "x": "120", "y": -3, "size": "0.1", "colour": "sky"})
    assert (said["x"], said["y"], said["size"], said["colour"]) == (100.0, 0.0, 0.5, "#5aa6e0")
    assert ph.text_said({"text": "Two\nlines", "x": 10, "y": 20}) == "'Two / lines' at 10 20, 6% tall, #ffffff"
