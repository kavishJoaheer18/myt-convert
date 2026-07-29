# Plan — document management and chat

Turning myt convert from a converter into a document store that teams can search
and ask questions of.

Decisions taken with the brief: **internal teams with separate access**, chat
**built into this app** rather than delegated to the existing `trag` stack, and a
**general document store** rather than PDFs alone.

---

## What this builds on

Four things already exist, and they change what is worth building.

**Extraction that knows where text came from.** Every cell carries page, row,
column and a confidence score. Ordinary document chat chunks raw text and can
only cite "somewhere in this file"; this can cite *that row of that table on page
three*, and link straight to it. That is the single strongest reason to build
chat here rather than pushing text into another system.

**LibreOffice is already in the worker image.** It was added to re-render
workbooks for verification, but it converts Word, Excel, PowerPoint and the
legacy `.doc`/`.xls` formats to PDF just as well. So "support every format" does
not mean a parser per format — it means one conversion step, after which the
existing pipeline handles everything and citations stay page-based.

**`bge-m3` is already on the server's Ollama.** A strong multilingual embedding
model, already pulled for another application. Retrieval needs no new model.

**Postgres is already running.** With the `pgvector` extension it becomes the
vector store too — no second datastore to run, back up or keep consistent.

---

## Phases

Each phase is independently useful. B is where it starts paying for itself; chat
without A–D would be a demo.

### Phase A — Identity and teams

Nothing else can be built correctly without knowing who is asking.

- Verify the Cloudflare Access JWT on every request. Identity arrives signed in a
  header; the app never handles a password, and SSO and an audit trail come free.
- `User`, `Team`, `Membership` tables, seeded from the JWT on first sight.
- **Adopt Alembic.** `create_all` has carried us this far because tables were
  only ever added. From here columns change on tables holding real data, and that
  needs migrations.

*Gate: two accounts in different teams see different things, proven by a test
that asserts on the API rather than the UI.*

### Phase B — Documents and folders

- `Folder`, `Document`, `DocumentVersion`. A document owns its original file, its
  extracted text, and anything generated from it.
- Ingestion: any format → LibreOffice → PDF → the existing extraction. PDFs skip
  the first step; images go through OCR as they do now.
- Permissions on folders, inherited by documents. An ACL of
  `(principal, resource, role)` with roles viewer / editor / owner.
- Postgres full-text search over extracted text.
- **Every document query is filtered by permission in SQL**, never in the UI.

*Gate: a document in another team's folder is absent from search results, absent
from the API, and 404s on direct access.*

### Phase C — The DMS surface

- Browse folders, upload, move, tag, delete with a retention window.
- Preview using the page renders the pipeline already produces.
- Sharing: grant a team or a person access to a folder.
- Audit log — who read, changed or downloaded what.

*Gate: a colleague can find a document by its contents without being told where
it is.*

### Phase D — Semantic index

- `pgvector`, embeddings from `bge-m3` via the shared Ollama.
- **Structure-aware chunking.** A table row stays whole rather than being sliced
  through the middle of a number; a paragraph stays whole. Each chunk keeps its
  document, page and cell range, which is what makes a citation precise.
- Hybrid retrieval: keyword and vector together. Pure vector search is poor at
  part numbers and codes, which is much of what these documents contain.
- Re-embed on new version, not on every read.

*Gate: searching a part number finds the quote containing it; searching a
description finds it too.*

### Phase E — Chat

- Retrieval **filtered by permission before the model sees anything**.
- Answers cite document, page and cell, each a link.
- Scope a conversation to one document, a folder, or everything you can read.
- Conversation history, so follow-up questions work.

*Gate: an answer's every claim is traceable to a citation, and a question about a
document you cannot read returns nothing rather than a summary of it.*

---

## The risks worth naming now

**Retrieval is where a permissions bug becomes a leak.** If the filter is applied
after retrieval rather than inside it, the model has already read another team's
document and will happily paraphrase it. Citations make that visible, but by then
it is in the answer. The filter belongs in the SQL that fetches candidates, and
the test for it should assert on the retrieved set, not the wording of the reply.

**Chat on CPU may be too slow to feel like chat.** `qwen2.5:32b` on this server
has no GPU behind it. Extraction can take a minute without anyone minding;
someone waiting for a chat reply minds after five seconds. Options, in order of
preference: a smaller model for chat (`qwen2.5:7b` or `14b`) with the 32B kept
for extraction, streaming so the answer appears as it is written, or a GPU. We
should measure before choosing — the `time curl` benchmark will tell us.

**Embedding a large corpus takes real time.** `bge-m3` on CPU processes a few
chunks a second. Ten thousand pages is hours, not minutes. It belongs in the
worker queue with visible progress, not in an upload request.

**Storage grows and never shrinks on its own.** Originals, page renders, extracted
text and embeddings all accumulate. Retention needs deciding in Phase B, when it
is a column, rather than in year two when it is a migration.

**The `trag` stack shares the server.** Both applications want the same Ollama
and the same RAM. Two models resident at once will not fit alongside everything
else, so they will swap. Worth watching once chat is real.

---

## Rough sizing

| Phase | Effort | Depends on |
| --- | --- | --- |
| A — Identity and teams | 2–3 days | Cloudflare Access configured |
| B — Documents and folders | 4–6 days | A |
| C — DMS surface | 4–5 days | B |
| D — Semantic index | 3–4 days | B |
| E — Chat | 4–5 days | D |

Roughly three to four weeks of focused work for all five. A and B together are
the point at which it stops being a converter and becomes a system worth putting
documents into.

---

## Open questions

1. **Cloudflare Access** — is Zero Trust already set up for a domain we can put
   this behind? If not, that is a prerequisite for Phase A.
2. **Existing documents** — is there a share or folder to import, or does the
   library start empty?
3. **Retention** — how long must documents be kept, and does anything need to be
   provably deleted?
4. **Languages** — are quotes and documents only in English, or also French?
   `bge-m3` handles both, but full-text search needs the dictionary configured
   per language.
