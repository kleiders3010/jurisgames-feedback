# Jurisgames feedback

The "Send feedback" button in the free Jurisgames apps ([Juntos](https://github.com/kleiders3010/juntos), Ronda,
Sumate, Tasks) sends here. A Cloudflare Worker checks the report (app, kind, message up to 4,000 characters,
optional reply email, optional technical details up to 32 KB) and emails it to hello@jurisgames.com.

- Nothing is stored: no database, no log of reports.
- Limits: 8 reports per network per day (counted under a one-way hash of the address, deleted the next day) and
  150 a day in total.
- Only the apps' own sites may post from a browser; the native apps post without an origin.

Run locally: `cd worker && npx wrangler dev --port 8798 --var TEST_SINK:1` (TEST_SINK answers with the email it would
send instead of sending it). Test: `python worker/feedback_test.py`.

License: Apache-2.0.
