# The photo kit

`kit = "photo"` is a photo editor laid out like a simple picture program:
one picture from the drive, turned, mirrored, cropped, made another size,
with layers laid on it — words, marker strokes, and pieces copied out of
the picture and pasted back — and saved over the photo or as a new file
beside it. Cloudmorrow draws it on the web and the phone (the picture
live, with tools, a selection, and the layers dragged on it), in the
terminal (the picture as it will save, where the terminal can show
pictures) and on the command line (`cm <quill> …`). A Quill declares it in
TOML; the pixels — a preview of the edit, the saved file — come from the
Quill's own service, with Pillow, which the server's Python has.

## The screen

```toml
[[screens]]
id = "editor"
kit = "photo"
label = "Editor"
model = "retouch.edit"            # an edit: one record per picture worked on
title = "name"
elements = "retouch.layer"        # optional: what is laid on the picture, each on one of the edit's layers
media = { share = "my-files", within = "Photos" }   # where the photos are: file records
pictures = "pictures"             # optional: the id of an [[apis]] that draws the picture
save = "save"                     # optional: an action on the edit — Save, over the photo or as a new file
export = "export"                 # optional: an action on the edit, with its form
```

The field names below are the kit's: an edit's datamodels have them, with
these kinds, or `cm quill check` says which is missing.

### The edit (`model`)

| field | kind | |
| --- | --- | --- |
| *title* | string | its name; the photo's, without its suffix, when started from one |
| `source` | string | the file record the picture is (a `file` id; a link cannot point at files) |
| `width`, `height` | int | the photo's size in pixels, as taken (after the camera's own orientation); blank until the pictures API, the web app or the service fills it in |
| `rotate` | int, optional | quarter turns clockwise, in degrees: 0, 90, 180 or 270 |
| `mirror` | bool, optional | flipped left to right, after the turn |
| `crop` | json, optional | the part kept, in percent of the turned picture: `{"x": 0, "y": 0, "w": 100, "h": 100}`; blank keeps all of it; never less than 5% each way |
| `out_width`, `out_height` | int, optional | the saved picture's size in pixels; blank is the cropped picture's; one of them given keeps the shape, both are taken as typed; at most 8192 each |
| `layers` | json, optional | the layers, lowest first: `[{"id": "1", "name": "Layer 1", "hidden": false}, …]`; blank is one layer. A layer is a group: everything added lands on the current one, and layers are hidden, renamed and reordered as a whole |
| `status` | enum, optional | said in the header beside Save (`queued`, `rendering`, `done`, `failed` are toned) |
| `message` | string, optional | said beside the status |
| `output` | string, optional | the id of the last saved file record: the header offers to open it |

What is done to the picture happens in this order: the turn, the mirror,
the layers (lowest first), the crop, the size. So every layer is placed on
the turned picture and stays on the same part of the photo when the crop
changes, and the crop is in percent of the turned picture too.

### An element (`elements`)

What is laid on the picture — words, a marker stroke, a piece — one record
each, on one of the edit's layers. (`layers` was the binding's first name
and is still read.)

| field | kind | |
| --- | --- | --- |
| *a link to the edit* | link | exactly one link to the edit's model, `on_delete = "cascade"` |
| `kind` | enum | `text`, `mark` or `piece` (all three values) |
| `layer` | string, optional | the id of the layer it is on; blank, or one the edit no longer has, is the first layer. Without this field and the edit's `layers`, the editor has one layer and offers no more |
| `x`, `y` | decimal | the top left corner, in percent of the turned picture's width and height; a mark's first point |
| `w`, `h` | decimal, optional | a piece: how big it is placed, in percent |
| `text` | string or text, optional | words; a line break starts a new line |
| `size` | decimal, optional | words: how tall a line of letters is, in percent of the picture's height; 6 when blank |
| `colour` | string, optional | `#rrggbb`; white when blank |
| `points` | json, optional | a mark: `[[x, y], …]` in percent, the stroke |
| `width` | decimal, optional | a mark: how wide the stroke is, in percent of the picture's height; 1.5 when blank |
| `opacity` | decimal, optional | a mark: 1 is solid (a pen), 0.4 see-through (a highlighter) |
| `source` | json, optional | a piece: the part of the turned picture it is copied from, `{x, y, w, h}` in percent |
| `hidden` | bool, optional | kept, but not drawn |
| `order` | int, optional | stacking within its layer, lowest first; two the same go by when they were made. Layers come first: everything on a lower layer is under everything on a higher one |

Words are drawn in the app's own letters (Barlow, semibold) with a thin
dark edge, so they read on a light photo and a dark one; a mark is a round
stroke; a piece is the source's pixels, turned and mirrored as the edit
is, scaled into its box. The web app draws all three on the canvas; a
service draws them with Pillow and the same font files, from the core's
web folder, so what is saved is what was seen.

### The pictures API (`pictures`)

An `[[apis]]` of the Quill (normally served by its service), answering:

| request | answer |
| --- | --- |
| `GET <base>/info?file=<id>` | `{"width": 4000, "height": 3000, "image": true}`: the photo's size as taken, the camera's orientation applied |
| `GET <base>/source?file=<id>&w=<px>` | `image/jpeg`: the photo as taken, `w` pixels wide |
| `GET <base>/picture?edit=<id>&w=<px>` | `image/jpeg`: the edit as it would save — turned, mirrored, its layers on it, cropped — `w` pixels wide |

`<base>` is `/api/q/<quill>/<prefix>`, the api's `prefix`:

```toml
[[apis]]
id = "pictures"
service = "draw"
prefix = "pictures"
```

Without `pictures`, the web app still edits (it draws the picture itself,
from the server's large copy of the photo, and reads the photo's size from
the file once); the terminal says in words what the edit does; and `cm
<quill> picture` says there is none. A Quill with no service of its own
can still be a photo editor on the web; saving needs one.

### Save (`save`) and Export (`export`)

`save` names an action on the edit with two fields, `overwrite` (bool) and
`name` (string). The kit draws Save and asks, in a sheet of its own, whether
to write over the photo or save as a new file by a name; then it presses
the action with both fields answered, so no form opens. What the Quill does
with them is its own: the Retouch Quill's service writes the result over the
photo (the one before goes to the Trash) or beside it, and when it wrote
over the photo it resets the edit — the turn, the crop, the size and the
layers are in the picture now — so the editor shows the saved photo, ready
for more. `export` names an action drawn with its own form, as the timeline's
is; a screen may have either, or both.

## What each surface does

**Edits.** The screen opens on the edits, newest first, each with a small
copy of its photo and the size it comes out at. New asks which photo of
the drive to start from — the photos under `media`, by folder, from the
person's own drive or any share they have — and an edit of it opens. A
Quill's own action on a file (*Edit this photo*, on a photo's sheet in
Media or Files) does the same from the other side: it makes the edit and
answers `go("editor", edit=<id>)`, which opens it straight away. Opened with
an `edit` parameter, the screen opens that edit's editor.

**The editor.** A bar across the top — Resize, Export, Save, and how the
last save went — tools down the left, the picture in the middle, panels
on the right: the tool's options, the layers.
- *Select* (V), the first tool and the one everything comes back to: press
  a layer to pick it, drag it, pull a piece's corners or a text's corner to
  size it. The panel has the layer's own numbers — words, size and colour;
  a mark's colour, width and how solid; a piece's place — with Duplicate,
  Hide and Remove.
- *Move* (G): the chosen layer follows the hand wherever the picture is
  pressed, for a stroke or a small piece that is hard to take hold of.
- *Marquee* (M): drag a box on the picture. Copy takes what is in it; Paste
  (also ctrl+V, and the Paste tool) lays it on the picture as a piece, a
  little to the side; Crop to it crops the picture to the box.
- *Crop* (C): the picture shows the crop box, to drag and resize, or to
  draw anew; a shape to hold it to (square, 4 : 3, 3 : 2, 16 : 9, tall);
  numbers; Keep all of it; Done.
- *Text* (T): press on the picture to put words there, picked, with the
  panel ready to take them; the tool is Select again at once, so the next
  press moves or sizes the words, or picks something else.
- *Marker* (B): draw on the picture. The colour, the width (fine, medium,
  thick) and the style (a pen, or a see-through highlighter) are the
  panel's; each stroke is a layer.
- *Turn left, Turn right, Mirror, Paste*: under the tools. Under the
  picture, the photo's size, the saved picture's when it differs, and the
  turn.
- *Resize*: on the bar; a sheet with what the saved picture will be and
  the usual sizes (as it is, half, a quarter, 1920, 1280 or 800 wide, or
  another typed as width and height). Each choice is written as it is
  made; the picture itself changes when it is saved.
- *Layers*: pinned to the foot of the right-hand column, as tall as the
  picture, so they stay put while the tool's options above them change.
  Every layer, the top one first, with its eye and how many things are on
  it; the current one lit. New words, strokes and pieces land on the
  current layer; a press on a layer makes it current (and lets go of an
  element on another), a second press renames it; the eye hides it with
  everything on it (H); New layer (N) makes an empty one on top; the
  current one has Bring forward, Send back and Remove, which asks when
  there is something on it. The last layer stays. Picking an element on
  the picture makes its layer current. Duplicate (ctrl+D) copies the
  chosen element onto the current layer; Copy (ctrl+C) with an element
  chosen and nothing selected copies it for Paste.
- *Save*: on the bar; asks whether to write over the photo or save as a
  new file by name, and the bar says the status and message as they
  change; done, Open shows the file. Export, when the screen has one, is
  there too. Delete takes the chosen layer off; Escape goes back to Select,
  then lets go — it never leaves the editor. A screen without `layers` offers no Text, Marker or Paste.

**Web and phone.** The picture is a canvas: the server's large copy of the
photo (`/thumb`, so a phone's HEIC needs no plug-in and a big photo comes
quickly) drawn turned and mirrored, every layer on it, and the crop over
it. Everything is dragged with the mouse or a finger; on a phone the tools
are a strip under the picture and the panels follow. The gear at the right
of the title opens the edit's sheet.

**Terminal.** The picture is the `pictures` API's `picture` of the edit,
drawn with textual-image (Kitty, Sixel, or half-cells); without the API
it is words. Beside it, the layers, the top one first, each with what is
on it under it. Keys: r
turns right, R left, m mirrors, c crops from four typed numbers (C keeps
the whole picture), s sets the size (`1920x1080`, a width, a percent, or
`as is`), t lays words on the picture (on the top layer), enter on an
element opens its sheet, k moves it (`x y`, typed, with a size as a third
number for words), shift+↑/↓ brings it forward or sends it back, x takes
it off; l makes a new layer on top, enter on a layer names it, h hides or
shows it with everything on it, shift+↑/↓ moves it, x takes an empty one away,
w saves (the photo's name writes over it; another name is a new file), e
exports, o opens what was saved.

**Command line.** `cm <quill> list` lists the edits; `add <photo> [name]`
starts one from a photo in the drive (by name, path or id); `show <edit>`
(or `layers <edit>`) prints what is done to it and the layers on it, top
first; `turn <edit> [right|left|180]`, `mirror <edit>`, `crop <edit> <x y w
h | all>`, `size <edit> <1920x1080 | 1920 | 50% | as is>`; `text <edit>
"words" [--at "x y"] [--size 8] [--colour amber]` lays words on it, `move
<edit> <layer> --at "x y" [--size] [--colour]` moves a layer, `rm <edit>
<element>` takes it off; `layers <edit>` lists the layers and what is on
each; `layer <edit> add [name]` makes one on top (new words and marks land
on the top layer), `layer <edit> hide|show|rm <layer>` and `layer <edit>
rename <layer> <name>` do as they say; `picture <edit> [-o out.jpg]` saves the edit as it
will save, from the pictures API; `save <edit>` writes over the photo and
`save <edit> <name>` saves as a new file; `export <edit> [format=png]` runs
the export action.
