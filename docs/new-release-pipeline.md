# New Release Pipeline

How new bourbon releases get researched and added to `bottles.json`.

This is written for a Claude Code session — scheduled or run by hand. The whole
point of the design is that **nothing reaches the bot without a human merging a
PR.** Release data is exactly the kind of thing a model states confidently and
gets wrong, so the review gate is the feature, not overhead.

## The rule that matters

**Every bottle needs a source URL you actually opened.** Not "I recall this
exists" — a page you fetched, this run, that names the bottle. If you cannot
produce a URL, the bottle does not go in the seed. A bottle invented from
training data is worse than a missing bottle: it silently pollutes a database
five other commands read from.

When a source is ambiguous or you are not confident, put the bottle in the PR
body under "Needs a human check" and leave it out of the seed.

## Sources, best first

1. **TTB COLA public registry** (`ttbonline.gov` public COLA search) — every US
   whiskey label clears federal approval before release, so this is the earliest
   authoritative signal and it is public government data. Search recent approvals
   by class/type. Note that an approved label is not always a shipped product;
   say so in the PR when that is all you have.
2. **Distillery newsrooms and press releases** — Buffalo Trace, Heaven Hill,
   Beam, Brown-Forman, Wild Turkey, Four Roses, Michter's. Primary source, and
   usually carries proof and MSRP.
3. **Established review sites** for bottles already in the wild — Breaking
   Bourbon, Bourbon Banter, Whiskey Advocate, and similar.

Prefer official sources over retail listings. Retail pages carry scalped pricing
that is useless as MSRP, and scraping them invites rate-limiting and ToS trouble.
Respect `robots.txt`; do not hammer a site.

## Procedure

1. **See what is already known.** Do not read `bottles.json` directly — it is
   ~350KB.

   ```sh
   python3 scripts/known_bottles.py --stats
   python3 scripts/known_bottles.py --brands
   ```

2. **Research.** Look for releases announced since the last run. Annual
   allocated lineups are the highest value: BTAC, Pappy/Van Winkle, Four Roses
   and Old Forester limited editions, Parker's Heritage, Michter's
   fall releases, Booker's and Little Book batches, Jack Daniel's specials.

3. **Filter out what you already have**, including the shorthand people type:

   ```sh
   python3 scripts/known_bottles.py --check "Booker's 2026-02" "Four Roses LE 2026"
   ```

4. **Write a seed file** to `scripts/seeds/YYYY-MM-releases.json`:

   ```json
   {
     "bottles": [
       {
         "name": "Canonical Bottle Name With Year If Annual",
         "aliases": ["Shorthand", "Initialism", "Unpunctuated Spelling"]
       }
     ]
   }
   ```

   Aliases are what people type in Discord, not marketing copy: initialisms
   (`ETL`, `WSR`), unpunctuated spellings (`Michters 10`), nicknames
   (`Green Label Weller`, `Lot B`), and the year form for annual releases
   (`GTS 2026`). Aliases of three characters or fewer match as whole words only.

   Name + aliases is enough. About 92% of `bottles.json` carries no pricing, and
   the bot degrades cleanly — `/bottle` shows "Unknown", `/worth` says it lacks
   pricing data. Add `proof`, `msrp`, `style`, `profile` and the price ranges
   only when a primary source states them; never estimate them.

5. **Merge the seed.** Never hand-edit `bottles.json`.

   ```sh
   python3 scripts/import_alias_seed.py scripts/seeds/YYYY-MM-releases.json
   ```

   The script backs up to `backups/`, matches against every existing name and
   alias, adds only new aliases to a bottle that already exists, and skips
   anything matching more than one bottle. Read its output: a non-zero
   `possible_duplicate_count` means something needs a human decision — name it
   in the PR.

6. **Verify nothing regressed.**

   ```sh
   python3 scripts/known_bottles.py --stats
   python3 -c "import json; json.load(open('bottles.json')); print('valid')"
   python3 -c "import os,sys; os.environ['DISCORD_TOKEN']='t'; sys.path.insert(0,'.'); import bot; print(len(bot.BOTTLES),'bottles load')"
   ```

   Then confirm the new bottles are detectable the way people will type them:

   ```sh
   python3 -c "
   import os,sys; os.environ['DISCORD_TOKEN']='t'; sys.path.insert(0,'.')
   import bot
   for q in ['<each new bottle>', '<each alias>']:
       print(q, '->', bot.analyze_allocation_message(q))
   "
   ```

7. **Open a PR.** Never commit to `main`. One PR per run, on a branch named
   `claude/new-releases-YYYY-MM`. The body must list, per bottle, **the name and
   the source URL**, plus anything skipped and why. A reviewer has to be able to
   check your work without redoing the research.

## Scope limits

- **Cap each run at roughly 15 bottles.** A PR nobody can review is a PR that
  gets rubber-stamped, which defeats the whole design.
- Do not touch `bot.py` or any file other than `bottles.json` and the new seed.
  Detector or command changes belong in their own PR.
- If a run finds nothing new, say so and open no PR. An empty PR is noise.

## Why seeds are kept

Seed files stay in `scripts/seeds/` as a replayable record of what was added and
when. Re-running a seed is a no-op, so they are safe to keep and replay against a
restored backup.
