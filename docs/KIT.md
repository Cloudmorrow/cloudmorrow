# The kit's screens, pictured

A Quill never draws a screen. It names one of the kit's elements in its
manifest — a list, a board, a calendar — binds the element to the fields of
a datamodel, and every surface draws it: the phone, the full web app, the
terminal and the command line. A Quill with code can also return a tree of
primitives for a screen of its own. This chapter shows what each of those
looks like, so you can pick the one that fits before writing a line.
[QUILLS.md](QUILLS.md) has the full table of what each element binds;
[QUILLCODE.md](QUILLCODE.md) the primitives and their arguments.

Every screen here was taken from one cloud with the standard Quills on it,
on a phone (390 pixels wide) and in a desktop browser. The terminal draws
the same screens its own way; [MANUAL.md](MANUAL.md) shows a few.

## Lists

**A plain list** is rows titled by one field, with the pen beside the title
for a new one. Name a bool as `tick` and every row gets a circle that ticks
it, the done ones struck through. The template Quill's Items is the whole
of it:

```toml
[[screens]]
id = "items"
kit = "list"
label = "Items"
model = "example.item"
title = "name"
tick = "done"
```

![A plain list on a phone: Items, three rows with a circle before each, the first ticked and struck through, two buttons above for the Quill's actions](images/kit-list-plain-phone.webp)

![The same list in a desktop browser, the Quills down the left](images/kit-list-plain-desktop.webp)

Name a `subtitle` and each row says a second field under its title —
DevProject's Projects say their repository:

![A list with a line under each title: two projects, each with its git address under its name](images/kit-list-plain-subtitle-phone.webp)

**A list picked through** has a `group`: a row of chips across the top, one
per value — the records a link points at, an enum's values, or the values
an indexed string has, with *+ New* on the end to name another. A
`subgroup` is a second row inside the chosen group. Secrets is a vault and
an environment; a field the datamodel marks `secret` is dots until the eye
is tapped:

```toml
[[screens]]
id = "vaults"
kit = "list"
label = "Secrets"
model = "secret"
title = "key"
subtitle = "value"
group = "vault"
subgroup = "environment"
```

![Secrets on a phone: chips for the vaults, chips for the environments, then rows of keys with their values hidden behind dots and an eye on each](images/kit-list-grouped-phone.webp)

![The same on a computer, wider](images/kit-list-grouped-desktop.webp)

One level is enough for most Quills. CRM's Organisations are grouped by
book, and its Activities have a tick besides:

![Organisations on a phone: chips for the books, then four organisations with their status under each](images/kit-list-grouped-crm-phone.webp)

![Activities on a phone: chips for the books, then rows with a circle each, one ticked and struck through](images/kit-list-tick-crm-phone.webp)

**Every row has a menu** — a right-click on a computer, a finger held on it
on a phone — with Open and the actions on the record's datamodel, from
whichever Quill declares them. A Quill declares the actions, never the
menu:

![A right-click on an organisation: a small menu with Open and Plan a follow-up](images/kit-menu-row-desktop.webp)

## A board

A board is a model with an enum for its lanes, or a link to the records
that are its lanes (a pipeline's stages), and cards dragged between them.
On a phone the lanes stack; on a computer they stand side by side and a
card is dragged. With a `group` the board has chips for its boards, as a
list does.

```toml
[[screens]]
id = "board"
kit = "board"
label = "Tasks"
model = "task"
group = "board"
lane = "lane"
title = "title"
body = "body"
done = "done"
```

![Tasks on a phone: the board chip, then To Do, Doing and Done stacked, each with a plus and its cards](images/kit-board-phone.webp)

![The same board in a desktop browser: the three lanes as columns](images/kit-board-desktop.webp)

## The record sheet

Every row, card and tile opens the same sheet: every field with the widget
its kind has, editable, the actions on the record under the fields, and
delete. A `detail` or `form` screen is this sheet for one record; you never
draw it.

![An organisation's sheet on a phone: its status as a row of chips, its fields as rows, the address box, and under them New deal](images/kit-sheet-phone.webp)

![The same sheet in a desktop browser](images/kit-sheet-desktop.webp)

## A calendar

A calendar is a model with a start and an end, in spaces that are the
calendars, each with a colour. A phone shows a month with a dot per thing
and the day's list; a computer a week of hours, or the month written in.

```toml
[[screens]]
id = "month"
kit = "calendar"
label = "Calendar"
model = "event"
space = "calendar"
colour = "colour"
title = "title"
subtitle = "location"
starts = "starts_at"
ends = "ends_at"
```

![Calendar on a phone: November with dots under the days that have something, and under it the list for Monday the 16th](images/kit-calendar-phone.webp)

![Calendar in a desktop browser: a week of hours with the events as coloured blocks](images/kit-calendar-desktop.webp)

## The list beside a page: editor, sheet, document

Three elements draw files in a folder of the drive, and share one list.
An `editor` is Markdown pages (Notes), a `sheet` is spreadsheets (Cells)
and a `document` is pages of words (Docs). On a phone it is the folders,
then the list, then the page; on a computer the list stands beside the
page and folds away to give it the width.

The list is newest first, under Today, Yesterday, Last 7 Days and the
months; each row says where its file is and the first words of it; the
search looks inside the files. Every row has the menu a file has in
Files — Rename, Duplicate, Move to another folder, Open folder in Files,
Delete — and *Select* beside the pen picks several to move or delete at
once.

```toml
[[screens]]
id = "notes"
kit = "editor"
label = "Notes"
model = "file"
where = { share = "my-files", within = "Notes" }
suffix = ".md"
title = "name"
body = "text"
path = "path"
```

![Folders on a phone: the drive first, then All Notes, Notes and ideas with a count on each](images/kit-editor-folders-phone.webp)

![All Notes on a phone: Select and the pen beside the title, a search box, and under Today five notes, each with its path and first line](images/kit-editor-list-phone.webp)

![Notes in a desktop browser: the list on the left with the open note lit, the note on the right](images/kit-editor-page-desktop.webp)

![A right-click on a note in the list: Open, Rename, Duplicate, Move to, Open folder in Files, Delete](images/kit-menu-file-row-desktop.webp)

![Select pressed: a ring before every note, three filled, and a bar over the list that says 3 selected with All, Move to and Delete](images/kit-select-editor-desktop.webp)

A sheet opens as a grid with a formula bar; a document as a page with a
bar of styles. The list beside each is the same one.

![Cells in a desktop browser: the sheets on the left, Budget 2027 open as a grid with a bar of buttons and the formula line above it](images/kit-sheet-grid-desktop.webp)

![Docs in a desktop browser: the documents on the left, Lease renewal open as a page with the style bar above it](images/kit-document-page-desktop.webp)

## A grid of files

A `grid` is the file manager: the places to pick from first (My Files, the
fileshares), then a folder's folders and files as a list or as tiles,
sorted by name, date, size or type, with search, Select, drag and drop, a
Trash and the menu on every row. Files is the one grid screen, and the
other Quills' "Open folder in Files" lands in it.

![My Files on a phone: Documents, Notes and Pictures as rows, the sort buttons above](images/kit-grid-folder-phone.webp)

![Pictures in a desktop browser as tiles: six photos with their names under them](images/kit-grid-tiles-desktop.webp)

## A thread

A `thread` is things said in spaces: the spaces you can see, newest first,
with what is unread in each and the last line said, and a conversation
with a box to write in. Spaces made between two people are listed under
Direct and named for the other person. On a computer the two stand side
by side.

```toml
[[screens]]
id = "channels"
kit = "thread"
label = "Channels"
model = "message"
space = "channel"
body = "body"
```

![Channels on a phone: general and kitchen under Channels, sara under Direct, each with the last line and when](images/kit-thread-list-phone.webp)

![A conversation on a phone: a rule for Today, the lines with the name over each run, yours on the right, a box to write in at the bottom](images/kit-thread-conversation-phone.webp)

![Channels in a desktop browser: the spaces on the left, the conversation with sara on the right](images/kit-thread-list-desktop.webp)

## Data

A `data` screen is the kit's look at everything: the datamodels by domain,
the records of one, and each record on its sheet. The Data tab under Your
cloud is this screen over every datamodel your circles give you.

![Data in a desktop browser: the datamodels under Attestations, Calendars and CRM, each with a line saying what it is](images/kit-data-desktop.webp)

## A timeline

A `timeline` is the video editor: material from the drive, video and audio
tracks, pieces to move, trim and split, effects that move by keyframes,
and export. It is a chapter of its own, [TIMELINE.md](TIMELINE.md).

## Views: a screen of your own

When the kit cannot say it, a screen names a handler in the Quill's code,
which returns a tree of primitives — and every surface draws that tree.
The primitives are deliberately few, and they look like the kit, because
they are drawn with the same pieces. What follows is each of the ones
that show records; `stat`, `badge`, `text`, `markdown`, `button`, `form`,
`toggle` and the layout primitives appear in the same pictures.

**`rows`** are the app's own list rows: a title and a line under it each,
grouped under Today, Yesterday and the months when you name a date field,
with a search over them and, when you name an action, an X at each row's
end that runs it. Morrow's conversations are `rows` beside a
`conversation`, in a `split`:

```python
side = ui.rows(
    conversations,
    title="title",
    subtitle="last_at",
    go="chat",
    param="conversation",
    current=opened,
    search="Search conversations",
    group="last_at",
    close="forget",
)
return ui.split(side, main, show="main" if opened else "side")
```

![Morrow AI on a phone: a search box, then conversations under Today, Yesterday, Last 7 Days and Last 30 Days, an X at the end of each](images/kit-view-rows-morrow-phone.webp)

![Morrow AI in a desktop browser: the rows on the left with one lit, the conversation on the right, your question in a bubble and the answer under Morrow's name](images/kit-view-conversation-morrow-desktop.webp)

**`cards`** are the same records as cards, with a title, a subtitle, a line
of body and a badge. Mail's folders are a `row` of `button`s with the open
one `current`, the threads under them `cards`, and the whole a `split`
with the open thread beside:

```python
return ui.stack(
    ui.row(*folder_buttons),
    ui.text(whoami, style="small"),
    ui.cards(threads, title="subject", subtitle="who", body="preview",
             go="mail", param="thread", current=opened),
)
```

![Mail on a phone: Inbox, Sent, Archive and Trash as buttons, a line with your address, then three mails as cards, the unread ones with a dot](images/kit-view-cards-mail-phone.webp)

![Mail in a desktop browser: the folders and cards on the left, the open thread on the right with a Reply box and Archive and Delete under it](images/kit-view-split-mail-desktop.webp)

**`table`** is records in columns, with an action or two per row; on a
phone each row folds into a card with its labels. **`stat`** is a number
with a word over it. CRM's Sales screen is four stats, then two tables:

```python
ui.row(
    ui.stat("Open deals", len(open_deals)),
    ui.stat("In the pipeline", money(pipeline), note=f"weighted {money(weighted)}"),
    ui.stat("Won this month", money(won), tone="good"),
    ui.stat("Overdue", len(overdue), tone="warn" if overdue else "neutral"),
),
ui.text("Next up", style="title"),
ui.table(
    next_up,
    columns=["title", ("Kind", "kind"), ("Due", "due"), ("With", "organisation"), ("Deal", "deal")],
    actions=["complete"],
    empty="Nothing planned for the coming week.",
),
```

![Sales in a desktop browser: four stat boxes, then a table of what is next up with a Done button on each row, then the pipelines](images/kit-view-table-crm-desktop.webp)

![Sales on a phone: the stats two by two, then each table row as a card with its labels and the Done button](images/kit-view-table-crm-phone.webp)

**`gallery`** is tiles, each the record's own picture with its name under
it and stars that rate it. Media's wall:

```python
ui.gallery(tiles, title="name", subtitle="where", badge="badge", stars="stars", rate="rate")
```

![Media in a desktop browser: filter buttons across the top, then photos as tiles with their names and five stars under each](images/kit-view-gallery-media-desktop.webp)

**`lanes`** and **`month`** draw a board and a month calendar from a view,
the same as the kit's own, for records a view has worked out itself.

## Which one

| you have | name |
| --- | --- |
| records with a title, maybe a line under and a yes/no | `list`, with `tick` |
| the same, in vaults, books, boards — things to pick through | `list` with `group` (and `subgroup`) |
| records that move through stages | `board` |
| records with a start and an end | `calendar` |
| Markdown files, spreadsheets, documents in a folder | `editor`, `sheet`, `document` |
| files of any kind | `grid` |
| things said in spaces | `thread` |
| a look at every record | `data` |
| video to cut | `timeline` |
| numbers to sum up, a page that is several of the above, a list beside what is open in it | a `view`: `stat`, `table`, `rows`, `cards`, `split` |

When none of these says what your Quill needs, the kit grows — for every
Quill at once — rather than one Quill growing a screen of its own. Say so
in an issue on the core repository, with what the screen should do.
