# The photo kit

`kit = "photo"` is a photo editor: one picture from the drive, turned,
mirrored, cropped, made another size, with words laid on it, and exported
as a new file. Cloudmorrow draws it on the web and the phone (the picture
live, the crop and the words dragged on it), in the terminal (the picture
as it will export, where the terminal can show pictures) and on the
command line (`cm <quill> …`). A Quill declares it in TOML; the pixels — a
preview of the edit, the export itself — come from the Quill's own
service, with Pillow, which the server's Python has.

## The screen

```toml
[[screens]]
id = "editor"
kit = "photo"
label = "Editor"
model = "retouch.edit"            # an edit: one record per picture worked on
title = "name"
texts = "retouch.text"            # optional: the words laid on the picture
media = { share = "my-files", within = "Photos" }   # where the photos are: file records
pictures = "pictures"             # optional: the id of an [[apis]] that draws the picture
export = "export"                 # optional: an action on the edit, the Export button
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
| `out_width`, `out_height` | int, optional | the export's size in pixels; blank is the cropped picture's; one of them given keeps the shape, both are taken as typed; at most 8192 each |
| `status` | enum, optional | said in the header beside Export (`queued`, `rendering`, `done`, `failed` are toned) |
| `message` | string, optional | said beside the status |
| `output` | string, optional | the id of the last export's file record: the header offers to open it |

What is done to the picture happens in this order: the turn, the mirror,
the words, the crop, the size. So the words are placed on the turned
picture and stay on the same part of the photo when the crop changes, and
the crop is in percent of the turned picture too.

### A text (`texts`)

| field | kind | |
| --- | --- | --- |
| *a link to the edit* | link | exactly one link to the edit's model, `on_delete = "cascade"` |
| `text` | string or text | the words; a line break starts a new line |
| `x`, `y` | decimal | the top left corner, in percent of the turned picture's width and height |
| `size` | decimal, optional | how tall a line of letters is, in percent of the turned picture's height; 6 when blank |
| `colour` | string, optional | `#rrggbb`; white when blank |

The words are drawn in the app's own letters (Barlow, semibold) with a
thin dark edge, so they read on a light photo and a dark one. The web app
draws them on the canvas in that font; a service draws them with the same
font files, from the core's web folder, so the export is what was seen.

### The pictures API (`pictures`)

An `[[apis]]` of the Quill (normally served by its service), answering:

| request | answer |
| --- | --- |
| `GET <base>/info?file=<id>` | `{"width": 4000, "height": 3000, "image": true}`: the photo's size as taken, the camera's orientation applied |
| `GET <base>/source?file=<id>&w=<px>` | `image/jpeg`: the photo as taken, `w` pixels wide |
| `GET <base>/picture?edit=<id>&w=<px>` | `image/jpeg`: the edit as it would export — turned, mirrored, written on, cropped — `w` pixels wide |

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
can still be a photo editor on the web; the export needs one.

## What each surface does

**Edits.** The screen opens on the edits, newest first, each with a small
copy of its photo and the size it comes out at. New asks which photo of
the drive to start from — the photos under `media`, by folder, from the
person's own drive or any share they have — and an edit of it opens. A
Quill's own action on a file (*Edit this photo*, on a photo's sheet in
Media or Files) does the same from the other side: it makes the edit and
answers `go("editor", edit=<id>)`, which opens it straight away. Opened with
an `edit` parameter, the screen opens that edit's editor.

**The editor.**
- *The picture*: the source turned and mirrored as the edit says, every
  text on it in its place, and the crop kept to — or, while cropping, the
  whole picture with the crop drawn over it and the rest dimmed.
- *Turn left, Turn right, Mirror*: a quarter turn each way, and a flip.
- *Crop*: a mode in which the picture shows the crop box, to drag and
  resize, or numbers to type; a shape to hold it to (square, 4 : 3, 3 : 2,
  16 : 9, tall); Keep all of it; Done.
- *Text*: Add text lays words in a corner, picked, with the panel ready to
  take them. Words on the picture are pressed to pick them, dragged to
  where they should be, and made bigger or smaller by their corner; the
  panel has the words, the size, the colour (a few swatches and any
  other), and Remove.
- *Size*: what the export will be, and the usual sizes (as it is, half, a
  quarter, 1920, 1280 or 800 wide, or another typed as width and height).
- *Export*: runs the `export` action on the edit with its form, and the
  header says the status and message as they change; when `output` is
  set, Open shows the file.

**Web and phone.** The picture is a canvas: the server's large copy of the
photo (`/thumb`, so a phone's HEIC needs no plug-in and a big photo comes
quickly) drawn turned and mirrored, the words in the app's own font, and
the crop over it. Everything is dragged with the mouse or a finger. The
gear at the right of the title opens the edit's sheet. Keys: r turns
right, R left, m mirrors, c crops, t adds words, delete takes the chosen
words off, escape lets go.

**Terminal.** The picture is the `pictures` API's `picture` of the edit,
drawn with textual-image (Kitty, Sixel, or half-cells); without the API
it is words. The texts are a list beside it. Keys: r turns right, R left,
m mirrors, c crops from four typed numbers (C keeps the whole picture), s
sets the size (`1920x1080`, a width, a percent, or `as is`), t lays words
on the picture, enter on them opens their sheet, k moves them (`x y`,
typed, with a size as a third number), x takes them off, e exports, o
opens the export.

**Command line.** `cm <quill> list` lists the edits; `add <photo> [name]`
starts one from a photo in the drive (by name, path or id); `show <edit>`
prints what is done to it and the words on it; `turn <edit> [right|left|180]`,
`mirror <edit>`, `crop <edit> <x y w h | all>`, `size <edit> <1920x1080 |
1920 | 50% | as is>`; `text <edit> "words" [--at "x y"] [--size 8] [--colour
amber]` lays words on it, `move <edit> <text> --at "x y" [--size] [--colour]`
moves them, `rm <edit> <text>` takes them off; `picture <edit> [-o out.jpg]`
saves the edit as it will export, from the pictures API; `export <edit>
[format=png]` runs the action.
