# FIH Rules API: integration guide

This guide is for front-end developers who build a chat interface on top of the FIH Rules API,
such as the rules assistant on the club website. It explains how to call the API and how to show
its answers.

- **Base URL**: provided separately, together with the API key
- **Interactive docs**: `<base URL>/docs`
- **Machine-readable contract (OpenAPI 3)**: [`docs/openapi.json`](openapi.json)
  ([raw](https://raw.githubusercontent.com/bavobbr/fih-rules-engine/main/docs/openapi.json))
- **API version**: 1.1.0

## Authentication

`POST /chat` needs the header `x-api-key: <key>`. The key is provided separately. Store it in an
environment variable, not in the source code. All other endpoints a chat interface needs are public.

| Missing header | Wrong key |
|---|---|
| `422` | `403 {"detail": "Invalid API Key"}` |

## Endpoints a chat interface needs

### `GET /jurisdictions`: fill the country picker

```json
[
  {"code": "BEL", "name": "Belgium"},
  {"code": "ENG", "name": "England"},
  {"code": "NED", "name": "Netherlands"}
]
```

The list contains only countries whose national rules are loaded, sorted by name. Add
**"International"** as the first option yourself and make it the default. It means "official FIH
rules only" and is sent as no `country`.

### `POST /chat`: ask a question

Request:

```json
{
  "query": "And a yellow card?",
  "history": [
    {"role": "user", "content": "How long is a green card suspension?"},
    {"role": "assistant", "content": "**Direct Answer**\nA green card suspension lasts 2 minutes of playing time.\n\n..."}
  ],
  "country": "BEL"
}
```

| Field | Required | Meaning |
|---|---|---|
| `query` | yes | The user's new question. |
| `history` | no | Earlier turns, oldest first, without the current question. Roles are `user` and `assistant`. For assistant turns, send back the `answer` you received unchanged. Only the last 4 messages are used. Send `[]` (or leave it out) for a new conversation. |
| `country` | no | A `code` from `/jurisdictions`. Leave it out (or send `null`) for International. |

There is no field for the hockey variant (outdoor, indoor or Hockey5s). The API detects it from the
question and the history. Users can steer it by mentioning it ("In indoor hockey, ...").

Response:

```json
{
  "answer": "**Direct Answer**\nA green card suspension lasts 2 minutes of playing time.\n\n**Key Rules**\n- **Rule 14.1**: A green card is a warning with a 2-minute suspension. *(fih-rules-of-hockey-2026-final.pdf, p. 45)*\n\n**Reasoning**\nThe user asks for the duration of a green card suspension. ...",
  "standalone_query": "How long is a green card suspension?",
  "variant": "outdoor",
  "source_docs": [
    {
      "page_content": "14.1 ... green card: temporary suspension for 2 minutes of playing time ...",
      "metadata": {
        "source_file": "fih-rules-of-hockey-2026-final.pdf",
        "type": "official",
        "variant": "outdoor",
        "page": 45,
        "rule": "14.1",
        "chapter": "PLAYING THE GAME",
        "section": "14 Personal penalties"
      }
    }
  ]
}
```

| Field | How to use it |
|---|---|
| `answer` | **Render as Markdown.** See [Showing the answer](#showing-the-answer). |
| `variant` | `outdoor`, `indoor` or `hockey5s`. Showing it as a small badge ("Outdoor") helps users notice when the wrong variant was assumed. |
| `source_docs` | The rule snippets the answer is based on, most relevant first, at most 10. Optional to show, for example as a collapsed "Sources" list. Can be empty. |
| `standalone_query` | The question rewritten to stand on its own. For debugging only; no need to show it. |

`source_docs[].metadata` keys depend on the source. Treat every key as optional:

| Key | Present for | Meaning |
|---|---|---|
| `source_file` | all | Document file name. |
| `type` | all | `official` (FIH rulebook) or `local` (national rules). |
| `country` | local | Country code. |
| `variant` | all | `outdoor`, `indoor` or `hockey5s`. |
| `page` | official | Page number (integer). |
| `rule`, `chapter`, `section` | official | Position in the rulebook. Values like `N/A` or `General` mean unknown; hide them. |
| `summary` | official | Short human-readable label. |

Other keys are internal and may change.

### `GET /health`: optional status check

Returns `200 {"status": "ok"}` when ready, and `503 {"detail": "Engine not ready"}` while starting.

## Showing the answer

A normal answer has three sections, each label in bold on its own line. In this shortened example,
the last Key Rules bullet is made up to show how a national rule appears:

```markdown
**Direct Answer**
If a defender intentionally plays the ball with the foot inside the circle, a penalty corner is
awarded, or a penalty stroke if it prevented a probable goal.

**Key Rules**
- **Rule 12.3**: A penalty corner is awarded for an intentional offence by a defender in the circle. *(fih-rules-of-hockey-2026-final.pdf, p. 33)*
- **Rule 12.4**: A penalty stroke is awarded when the offence prevents the probable scoring of a goal. *(fih-rules-of-hockey-2026-final.pdf, p. 33)*
- In national youth competitions, the penalty stroke is taken by ... *(spelregels-bel.docx)* (local rule)

**Reasoning**
The user asks what happens when ...
```

- A standard Markdown renderer (e.g. `react-markdown`) displays it correctly. Do not parse the
  sections out of the text. The format is meant for display, and small wording changes can happen.
- **Key Rules** may be missing when no specific rule applies.
- `(local rule)` marks a national rule that overrides or adds to the official rules for the
  selected country.
- **Off-topic questions, greetings and questions the rules don't cover** return one plain sentence
  with no section labels, e.g. *"I can only answer questions related to the Rules of Hockey."*
- The answer is in the language of the question.
- **Reasoning** can be long. Collapsing it behind a "Show reasoning" toggle keeps the chat compact.

## Timing and errors

- A typical answer takes **3 to 6 seconds**. After a quiet period, the first request can take up to
  about **30 seconds** longer (the server is starting). Show a loading indicator and use a request
  timeout of at least **60 seconds**.
- Errors return `{"detail": "..."}`:

| Status | Meaning | Suggested handling |
|---|---|---|
| `403` | Wrong API key | Configuration problem; log it. |
| `422` | Invalid request (e.g. missing `query` or header) | Bug in the client; log it. |
| `503` | Server still starting | Retry once after a few seconds. |
| `500` | Internal error | Show "Something went wrong, please try again." |

## Changes in 1.1.0 (November 2026)

What a client built against 1.0 should check:

1. **Answer layout is now fixed.** Earlier answers varied between runs (e.g. `- **Direct Answer**:`
   as a bullet). Now each section label is bold on its own line, as shown above. Anything that
   parsed or styled the old layout should simply render the Markdown.
2. **Off-topic replies** are a single sentence without headers.
3. **`standalone_query` no longer starts with a `[VARIANT: ...]` tag.** Remove any code that strips it.
4. **`GET /health`** now returns `{"status": "ok"}` instead of `null`, and `503` while the server
   is starting.
5. **Answers are faster**: about 5 seconds instead of about 9.

The request format is unchanged, so existing calls keep working.
