# The document kit

`kit = "document"` is a page of words: headings, paragraphs, lists, quotes
and tables, with bold, italic, underline, strike-through and links in
them — the useful part of Word, and nothing of the rest. Cloudmorrow draws
it on the web and the phone, in the terminal and on the command line
(`cm <quill> …`); a Quill declares it in TOML. A document is a file: a
`.docs` file in a folder of your drive, holding its blocks exactly as
written — in My Files, on WebDAV, in a backup of the folder, and open to
anything that reads JSON. A Word file (`.docx`) in the same folder is a
document too: the server reads it as the same blocks and writes it back
as Word, so Word's files are edited here and nothing else, and any
document can be exported as one — or as a PDF, or as Markdown.

## The screen

```toml
[[screens]]
id = "docs"
kit = "document"
label = "Docs"
model = "file"                                        # the foundational file
where = { share = "my-files", within = "Documents" }  # whose drive, which folder
suffix = [".docs", ".docx"]                           # which files are documents; a new one is the first
title = "name"
body = "text"                                         # the file's text: the document
path = "path"
```

It is an editor's kind of screen (docs/QUILLS.md): `where` is the filters
every listing is made with — a file's `share`, and `within`, the folder
the documents are under — and `suffix` says which files are documents,
one or a list, the first being what a new one is called. The list is the
editor's: folders, newest first, with the first words of each, and a
search through names and words. The record sheet every screen has is not
used for a document: the page is its own.

A Quill that ships this screen ships a first document the way Notes ships
its welcome note: a per-owner dataset of the `file` datamodel, with the
same `where` (the suffixes by commas) and the file's `text`.

## The file

A `.docs` file is UTF-8 text: one JSON object, with `blocks` in it, in
order:

```json
{
  "blocks": [
    {"kind": "heading", "level": 1, "runs": [{"text": "A letter"}]},
    {"kind": "paragraph", "runs": [{"text": "Dear "}, {"text": "you", "bold": true}, {"text": ","}]},
    {"kind": "bullet", "runs": [{"text": "one thing"}]},
    {"kind": "bullet", "level": 1, "runs": [{"text": "under it"}]},
    {"kind": "numbered", "runs": [{"text": "first"}]},
    {"kind": "quote", "runs": [{"text": "as they say"}]},
    {"kind": "paragraph", "align": "center", "runs": [{"text": "— the end —"}]},
    {"kind": "table", "rows": [[{"runs": [{"text": "a"}]}, {"runs": [{"text": "b"}]}]]}
  ]
}
```

A block has a `kind`: `paragraph`, `heading` (with `level` 1 to 3),
`bullet` or `numbered` (a list item, with a `level` from 0 at the margin;
items in a row are one list), `quote`, or `table` (`rows` of cells, each
with `runs`). A paragraph, heading, item or quote may say how it is
aligned: `align` is `center`, `right` or `justify`; nothing means left.
Any block may say which language its spelling is checked in: `lang` is a
code like `da` or `en-gb` (see *Spelling* below); nothing means the
writer's own. A run is `text` and what is true of it: `bold`, `italic`,
`underline`, `strike` (written only when true), and a `link`. A line
break inside a block is `\n` in the text.

Nothing else is kept: not fonts, not sizes, not colours, not pictures,
not margins. That is what makes a document the same on the phone, the
web, the terminal and in Word, and what keeps the file small and plain.
The file is written with one key order, a block per line group, by the
same rules in Python (`quill/docs.py`) and the browser
(`kit_docs_rules.js`), held together by one test (`tests/test_docs.py`);
neighbouring runs alike are joined, empty runs and unknown kinds are
dropped. Reading, a file holding the blocks alone, with no `blocks`
around them, is the same document; a file that is not JSON is an empty
one. Whatever else the object comes to hold one day sits beside `blocks`
and is kept.

## Word

A `.docx` is a zip of XML; `quill/docx.py` reads `word/document.xml` for
what the kit keeps — Heading 1 to 3 (and Title, Subtitle), Quote, a
list's numbering (bullets or numbers, with its level), bold, italic,
underline and strike on a run, hyperlinks, alignment, tables, text in an
insertion — and passes over the rest: pictures, headers and footers,
fonts, sizes, colours, comments, deletions. Writing makes a small, plain
package Word opens as it is: the same blocks, with styles for the
headings and the quote, numbering for the lists (a numbered list starts
over after anything else), a grid for a table.

On the server, a `.docx` is a text file like a `.docs` one
(`server/pages.py`): reading its `text` gives the document in it, as a
`.docs` file would hold it; writing `text` writes Word's package. So a
Word file in the folder is listed, opened, edited and saved like any
document, by every surface and by an assistant, and nobody has to know
which it is. Saving a Word file this way keeps what the kit keeps and
loses the rest — a document that came from Word with pictures in it goes
back without them. A file up to 25 MB is read; bigger, it is listed and
not opened.

## On each surface

**Web and phone** (`kit_docs.js`): the editor's list — folders, the
documents in one newest first with their first words, search, each row
saying where its file is as Files says it (`My Files/Documents/Offer.docs`,
cut at the start when the line is too short) — and a document as its
title (the file's name), a bar of styles (paragraph, heading 1 to 3, bold,
italic, underline, strike, bullets, numbers, quote, link, left, centre,
right) and the page, edited in place, with where the file is, whole, under
it — a link to its folder in Files; Ctrl+B, Ctrl+I and Ctrl+U work as
everywhere; plain text pasted comes in as paragraphs. The browser's own
spellchecker is off on the page; the cloud's is on it once the person
switches it on (`spelling.js`, the gear on the screen's title; see
*Spelling* below).
It saves as you type, as blocks and runs — nothing of the browser's own
markup; changing the title renames the file, and a Word file stays a
Word file. One changed elsewhere since it was opened is not written over.
Under **Folders** the first row is the drive the screen looks at, My
Files as a rule; tapping it offers the others — the fileshares you are
in — and the screen looks at the one chosen from then on, whole, there
being no Documents folder on a fileshare, until it is pointed home
again (the editor kit's drive row, kept in this browser per screen). A
document there opens by its record, the file staying where it is, and
the line under the page says where. **Export** offers Word,
PDF and Markdown, and hands the file over to save — through the record
API's `GET /api/records/file/<id>/export?as=docx`, which makes Word's
package, a PDF (`quill/pdf.py`: Helvetica on A4, headings larger,
lists with their markers, quotes set in, tables ruled, links that open)
or Markdown from the same blocks, and hands a Word file over as itself
(`as=docs` is the file). Nothing is written beside the document. On a
computer the list and the page are side by side, and the list folds
away. Read-only, the page shows and nothing types into it; Open and
Export are still there.

**Terminal** (`tui/panes/kit_docs.py`): the editor's tree and its live
editor, the document shown and edited as Markdown — `# ` a heading, `- `
a bullet (two spaces in, a level), `1. ` a numbered item, `> ` a quote,
`| a | b |` a table with a `| --- |` line after its first row, and
`**bold**`, `*italic*`, `__underline__`, `~~strike~~`, `[text](url)` in
a line; a part checked in another language stands between
`<!-- lang: de -->` and `<!-- /lang -->` lines, which a note keeps the
same way. What is typed is kept as the document's file, never as Markdown;
how a paragraph is aligned has no Markdown and is lost on the way
through. `f6` imports a Word, `.docs` or Markdown file on this machine as
a document; `f7` exports the open one by the name given (`.docx`, `.pdf`,
`.docs` or `.md`); `f5` opens a document from anywhere on the cloud by
`share:path` (`team:Plans/Offer.docx`).

**Command line** (`cli/quillrun/docs.py`):

```
cm docs list                            # every document, folders and all; Word ones say so
cm docs show Letter                     # as Markdown; --raw the file's text; --plain the record
cm docs add Letter                      # a new document, from stdin or $EDITOR, as Markdown
cm docs add Letter "# Hi" "words"       # or from the words given
cm docs edit Letter                     # $EDITOR with the Markdown, or the new Markdown from stdin
cm docs search invoice                  # names and words
cm docs set Letter name=Offer           # renames the file; path=2026/Offer moves it to a folder that is there
cm docs export Letter                   # Letter.docx here; or a name ending .docx, .pdf, .docs or .md
cm docs import ./Offer.docx [2026/Offer]   # a Word, .docs or Markdown file, as a document
cm docs show team:Plans/Offer.docx      # a document anywhere on the cloud: share:path
cm docs delete Letter
```

**An assistant** reads and writes the file's `text` through the record
tools, like any text file's: the JSON above, for a `.docs` and a `.docx`
alike.

## Spelling

The web app checks the spelling of a document, and of a note, with the
cloud's own dictionaries rather than the browser's: the browser's checker
is off on both pages, and the person switches the cloud's on under
**Spelling** — the gear on the screen's title, or `#/spelling` — where
they also choose the language a page is checked in unless a part of it
says otherwise, and see the words they added. The setting is kept on the
person (`PUT /api/auth/spelling`), so every phone and computer they sign
in on marks the same words.

The server holds the dictionaries (`server/spelling.py`): Hunspell, the
checker every office suite uses, as a wheel with the library inside
(`chunspell`), and the dictionaries LibreOffice ships, which the catalog
pins by URL and SHA-256 under `[dictionaries]` (docs/QUILLS.md, *The
catalog*). A language is fetched the first time somebody writes in it,
kept under `<data_dir>/dictionaries/<id>/`, and loaded once; nothing is
installed on the system. The page asks `POST /api/spelling/check` for a
screenful of words at a time, the ones it has not asked about before, and
`POST /api/spelling/suggest` for one word when it is clicked or tapped;
`GET /api/spelling/languages` lists what can be chosen. Only words are
sent, never the page.

On the page (`web/spelling.js`), a word the dictionary does not know is
tinted with a bar under it — not the red wave. A click or a tap on it
brings its suggestions, **Add to dictionary** (kept on the person) and
**Ignore** (this session). Select some lines and right-click them, or hold
a finger on them, and **Check spelling in…** marks them as a part in another language:
a bar down the left of the part with the language at its top and an ×
that takes the part back to the default. In a document the part is `lang`
on its blocks; in a note it is the comment lines above, which anything
that renders Markdown leaves out. A word being typed is not marked until
the caret leaves it; a word of capitals, an address and a mail are never
words to check. The terminal does not check spelling yet.
