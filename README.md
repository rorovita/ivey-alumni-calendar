# Ivey Alumni Events calendar feed

An auto-updating iCalendar feed of every event on the
[Ivey Alumni events calendar](https://www.ivey.uwo.ca/alumni/events/calendar/).

- `build_ics.py` reads Ivey's event feed and each event page (for time and location) and writes `docs/ivey-alumni-events.ics`.
- A GitHub Action runs it daily and commits the result; GitHub Pages serves `docs/`.
- Subscribe page: `https://<user>.github.io/ivey-alumni-calendar/`
- Feed: `https://<user>.github.io/ivey-alumni-calendar/ivey-alumni-events.ics`

Run the update by hand: Actions → "Update Ivey alumni calendar" → Run workflow.

Unofficial; not affiliated with Ivey Business School.
