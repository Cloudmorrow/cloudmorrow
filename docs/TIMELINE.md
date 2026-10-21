# The timeline kit

`kit = "timeline"` is a video editor: material from the drive laid on video
and audio tracks, cut, trimmed and moved, with effects that change over time
by keyframes, a crop of the whole picture, and an export. Cloudmorrow draws
it on the web and the phone (live video with sound), in the terminal (real
frames where the terminal can show pictures, played a few a second, no
sound) and on the command line (`cm <quill> …`). A Quill declares it in TOML;
the pictures that need ffmpeg — a frame of the cut, the export — come from
the Quill's own service.

## The screen

```toml
[[screens]]
id = "editor"
kit = "timeline"
label = "Editor"
model = "vidmorrow.project"       # a timeline: one record per edit
title = "name"
pieces = "vidmorrow.piece"        # what lies on the tracks
effects = "vidmorrow.effect"      # optional: what is done to a piece, by keyframes
media = { share = "my-files", within = "Videos" }   # where the material is: file records
frames = "frames"                 # optional: the id of an [[apis]] that draws frames
export = "export"                 # optional: an action on the project, the Export button
```

The field names below are the kit's: a timeline's datamodels have them, with
these kinds, or `cm quill check` says which is missing.

### The project (`model`)

| field | kind | |
| --- | --- | --- |
| *title* | string | its name |
| `width`, `height` | int | the picture's size in pixels; blank until the first piece sets it |
| `fps` | decimal | frames per second; blank until the first piece sets it |
| `tracks` | json | the tracks, top to bottom: `[{"id": "V1", "kind": "video", "name": "Video 1"}, …, {"id": "A1", "kind": "audio", "name": "Audio 1"}]`; blank means V2, V1, A1, A2 |
| `crop` | json, optional | the part of the picture kept, in percent: `{"x": 0, "y": 0, "w": 100, "h": 100}`; blank is all of it |
| `status` | enum, optional | said in the header beside Export (`queued`, `rendering`, `done`, `failed` are toned) |
| `message` | string, optional | said beside the status |
| `output` | string, optional | the id of the last export's file record: the header offers to open it |

A piece's picture is fitted into the project's frame (`width` × `height`)
whole and centred, with black bars where the shapes differ; a higher video
track covers a lower one where both have a piece, bars included, and where
no piece is there the frame is black. Effect boxes and the crop are in
percent of that frame. Every
piece's sound plays, mixed, unless it is muted.

### A piece (`pieces`)

| field | kind | |
| --- | --- | --- |
| *a link to the project* | link | exactly one link to the project's model, `on_delete = "cascade"` |
| `track` | string | a track id of the project |
| `source` | string | the file record it is cut from (a `file` id; a link cannot point at files) |
| `name` | string | what the timeline calls it: the file's name when added |
| `start` | decimal | where it begins on the timeline, in seconds |
| `offset` | decimal | where in the source it begins, in seconds |
| `length` | decimal | how long it lasts, in seconds |
| `volume` | decimal, optional | 0 to 2, 1 as recorded |
| `muted` | bool, optional | its sound is not heard |

A piece on a video track shows its picture and plays its sound; a piece on
an audio track only plays its sound (a video file there gives its sound).

### An effect (`effects`)

| field | kind | |
| --- | --- | --- |
| *a link to a piece* | link | exactly one link to the pieces' model, `on_delete = "cascade"` |
| `kind` | enum | the kit draws `blur`; other values are kept and listed by label |
| `label` | string | what it hides: a face, a number plate |
| `strength` | int, optional | 1 to 100, 20 when blank |
| `keyframes` | json | `[{"t": 0.0, "x": 35, "y": 25, "w": 30, "h": 40}, …]`: `t` in seconds from the piece's start, the box in percent of the project's frame (before the crop), sorted by `t` |

Between two keyframes the box moves and resizes in a straight line; before
the first and after the last it stays where that one says. An effect is on
from its first keyframe's `t` to its last, and through the whole piece when
it has one keyframe. Because `t` counts from the piece, moving a piece
takes its blurs with it, and trimming its start shifts nothing on screen
(the kit rewrites every `t` by the change in `offset`).

### The frames API (`frames`)

An `[[apis]]` of the Quill (normally served by its service), answering:

| request | answer |
| --- | --- |
| `GET <base>/info?file=<id>` | `{"duration": 12.4, "width": 1920, "height": 1080, "fps": 29.97, "audio": true, "video": true}` |
| `GET <base>/source?file=<id>&t=<s>&w=<px>` | `image/jpeg`: the source's frame at `t`, `w` pixels wide |
| `GET <base>/frame?project=<id>&t=<s>&w=<px>` | `image/jpeg`: the cut at `t` — tracks covered, effects drawn, cropped — `w` pixels wide |

`<base>` is `/api/q/<quill>/<prefix>`, the api's `prefix` (`/api/q/<quill>` without one):

```toml
[[apis]]
id = "frames"
service = "render"
prefix = "frames"
```

 Without `frames`, the web app still plays and
edits (it reads sizes from the video itself and draws effects itself); the
terminal shows the timeline without pictures, and adding material asks for
its length.

### Media

A browser's `<video>` cannot send the app's token, so the kit asks the server
for a link first: `POST /api/records/<model>/<id>/media` answers
`{"url": "/api/media/<token>", "expires": "…"}`, a link that serves the
record's bytes, with ranges, to whoever holds it, for six hours. It works
only for records the asker can read, and only for the bytes.

## What each surface does

**Projects.** The screen opens on the projects, newest first, with New. A
project opens the editor; Back returns to the list. Opened with a `project`
parameter (`go("editor", project=<id>)` from an action or a view), it opens
that project's editor straight away.

**The editor.**
- *Material*: the videos and sounds under `media`, by folder, with their
  length; Add puts the chosen one on the chosen track at the playhead (the
  first video track for a video, the first audio track for a sound), as one
  piece of its whole length, and gives the project its size and fps if it has
  none.
- *Viewer*: the picture at the playhead with effects and crop drawn; play and
  pause, step a frame, jump to start and end, the time and the total.
- *Tracks*: one row per track, pieces drawn to scale, a playhead, zoom. A
  piece is selected by choosing it; selected, it can be moved (to a time, to
  another track of the same kind), trimmed at either end, split at the
  playhead, muted, its volume set, or deleted. Moves snap to other pieces'
  edges and to the playhead.
- *Effects*: the selected piece's effects; Add blur puts one at the playhead
  with a box in the middle. On the viewer the box is dragged and resized;
  every change sets the keyframe at the playhead (made when there is none
  within half a frame), and keyframes are listed with their times, to jump
  to or remove.
- *Crop*: a mode in which the viewer shows the crop box, to drag and resize,
  or numbers to type; Reset keeps the whole picture.
- *Export*: runs the `export` action on the project with its form, and the
  header says the status and message as they change; when `output` is set,
  Open shows the file.

**Web and phone.** Live playback in the browser: the top piece's picture in
a `<video>` at the playhead, every audible piece's sound beside it, kept in
step; effects drawn over the picture on a canvas (a blurred copy of the box);
pieces dragged and trimmed with the mouse or finger. On a phone the material
is a sheet and the tracks scroll sideways.

**Terminal.** The viewer is the `frames` API's `frame` at the playhead,
drawn with textual-image (Kitty, Sixel, or half-cells); play steps the
playhead and fetches frames a few times a second, without sound. Tracks are
rows of text blocks. Keys: space play/pause, ←/→ a frame (with shift a
second), [ and ] trim the selected piece's start or end to the playhead, s
split, m move to the playhead, ↑/↓ another track, x delete, b add a blur,
k set a keyframe from typed numbers, c crop, e export, tab between
material, tracks and effects.

**Command line.** `cm <quill> list` lists the projects; `show <project>`
prints the tracks and pieces with times; `add <project> <file> [--track V1]
[--at 0]`, `cut <project> <piece> <at>`, `trim <project> <piece> --start/--end <s>`,
`move <project> <piece> --at <s> [--track]`, `rm <project> <piece>`;
`frame <project> --at <s> [-o frame.jpg]`; `export <project>` runs the
action.
