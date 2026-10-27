"""Lichess: every rated standard game started on lichess.org from Friday 1 June to Sunday
3 June 2018 (UTC), taken from the Lichess open database (CC0) as published on Hugging Face,
plus each player's side of every game, the players, the openings, the time controls, and
the moves (with clocks, and engine evaluations where the game was analysed) of a fixed
1-in-32 sample of the games.

The download is nine fixed parquet files, pinned to one dataset revision and checked by
sha256. Variants keep or drop a game together with its two player rows and its moves; the
players table is a summary of the games, so it is rebuilt inside each variant from the games
that variant keeps.
"""

from __future__ import annotations

import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import build_variants, sha256_file, write_manifest  # noqa: E402  # pylint: disable=wrong-import-position

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
MAIN = HERE / "lichess.duckdb"

REPO = "https://huggingface.co/datasets/Lichess/standard-chess-games/resolve"
REVISION = "de4e636eddf568a9394cc01fb0b9e1da04a6babf"
PARTITION = "data/year=2018/month=06"
# The first nine of the 79 files of the June 2018 export, in game start order. Together they
# hold every game started from 2018-05-31 22:00 to 2018-06-04 09:05 UTC (the export follows
# Paris time, so it starts two hours before June in UTC). The sha256 is the Git LFS object id.
FILES = {
    "train-00000-of-00079.parquet": "dab31c9cad7e1a80af274aa5316b96d125a429068820093604172220b9cafa16",
    "train-00001-of-00079.parquet": "2b1e60e826256a56771ac70eacaf68a03a88c4f3b9a953eb2c990d07cad4c8e5",
    "train-00002-of-00079.parquet": "c2643b0cd5b38106356ae521f3a82667b719b1dc0b7e5d34a84b0cfac59b53b8",
    "train-00003-of-00079.parquet": "b666c8f64eefc7cdd4fbd6d226366fd85714726e6ed83db939db933b2ddd3cfc",
    "train-00004-of-00079.parquet": "281c95ec916fb31a800e56d0aa4d1aff663e352301c4703c8af5bfaea8a3cdbe",
    "train-00005-of-00079.parquet": "7f3d7eae3d7baa2a4f098743d31e5a67831af8854ab098e94e3833e4d27ddf21",
    "train-00006-of-00079.parquet": "1560049a8ca0971f3fefcd5e0b3e1521e03f8e14209d1d0504861b6a21433d1e",
    "train-00007-of-00079.parquet": "eb97f562ef91ff1495b6fe2c90fac0ec6c783d6625d11c5f6f5a7056cf48cae7",
    "train-00008-of-00079.parquet": "7967b66a2d1c20093023623dcc49615a59ef1ee0ed239804544d177f6668ce4f",
}
# Whole UTC days only: Friday 1 June to Sunday 3 June 2018.
WINDOW_START = "2018-06-01 00:00:00"
WINDOW_END = "2018-06-04 00:00:00"
# Moves are kept for the games whose md5(game_id || salt) falls in the lowest 1/32 of the hash
# range, the same scheme the variants use with their own salts.
MOVE_SAMPLE_SALT = "lichess-moves"
MOVE_SAMPLE_THRESHOLD = 2**32 // 32

# A game and the rows derived from it share its game_id.
FACT_KEYS = {"games": "game_id", "player_games": "game_id", "moves": "game_id"}

# One PGN movetext token: a {comment}, a move number ("12." or "12..."), a result, or a move.
TOKEN = r"\{[^}]*\}|\d+\.(?:\.\.)?|1-0|0-1|1/2-1/2|\*|[^\s{}]+"
SAN = r"(O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h](x[a-h])?[1-8](=[QRBN])?)[+#]?"
GLYPH = r"(\?\?|\?!|\?)$"  # Lichess analysis marks: ?! inaccuracy, ? mistake, ?? blunder


def download() -> list[Path]:
    RAW.mkdir(exist_ok=True)
    paths = []
    for name, sha256 in FILES.items():
        path = RAW / name
        if not (path.exists() and sha256_file(path) == sha256):
            fetch(name, sha256, path)
        paths.append(path)
    return paths


def fetch(name: str, sha256: str, path: Path) -> None:
    """Downloads from the pinned revision, falling back to main; only the recorded sha256 is accepted."""
    part = path.with_suffix(".part")
    for revision in (REVISION, "main"):
        url = f"{REPO}/{revision}/{PARTITION}/{name}"
        print(f"downloading {url}")
        try:
            with urllib.request.urlopen(url, timeout=120) as response, part.open("wb") as out:
                shutil.copyfileobj(response, out, 1 << 20)
        except (urllib.error.URLError, OSError) as error:
            print(f"  failed: {error}")
            continue
        if sha256_file(part) == sha256:
            part.rename(path)
            return
        print("  sha256 mismatch")
    part.unlink(missing_ok=True)
    raise SystemExit(f"could not download {name} with sha256 {sha256}")


def split_opening(name: str) -> tuple[str | None, str | None, str | None]:
    """Family, variation and sub-variation of a Lichess opening name.

    "Sicilian Defense: Najdorf Variation, English Attack" gives ("Sicilian Defense", "Najdorf
    Variation", "English Attack"). Older names put a comma where newer ones put the colon
    ("King's Gambit Accepted, Bishop's Gambit"), a few use a second colon instead of a comma,
    and a trailing " #2" only tells apart two positions with the same name. "?" (no moves were
    played) has no family.
    """
    if name == "?":
        return None, None, None
    base = re.sub(r" #\d+$", "", name).strip()
    cut = re.search(r"[:,]", base)
    if not cut:
        return base, None, None
    family, rest = base[: cut.start()].strip(), base[cut.end() :].strip()
    cut = re.search(r"[:,]", rest)
    if not cut:
        return family, rest or None, None
    return family, rest[: cut.start()].strip() or None, rest[cut.end() :].strip() or None


def build_main(paths: list[Path]) -> None:
    MAIN.unlink(missing_ok=True)
    con = duckdb.connect(str(MAIN))
    con.execute("SET enable_progress_bar = false")
    files = ", ".join(f"'{p}'" for p in paths)
    con.execute(
        f"""CREATE TEMP VIEW source_games AS
        SELECT *, substr(Site, 21) AS game_id, UTCDate + UTCTime::TIME AS started_at
        FROM read_parquet([{files}])
        WHERE UTCDate + UTCTime::TIME >= TIMESTAMP '{WINDOW_START}'
          AND UTCDate + UTCTime::TIME < TIMESTAMP '{WINDOW_END}'"""
    )

    names = con.execute("SELECT DISTINCT ECO, Opening FROM source_games").fetchall()
    names.sort(key=lambda r: (r[0] or "", r[1]))
    con.execute(
        """CREATE TABLE openings (opening_id INTEGER, eco VARCHAR, opening VARCHAR,
        family VARCHAR, variation VARCHAR, sub_variation VARCHAR)"""
    )
    con.executemany(
        "INSERT INTO openings VALUES (?, ?, ?, ?, ?, ?)",
        [(i, eco, name, *split_opening(name)) for i, (eco, name) in enumerate(names, start=1)],
    )

    plies = (
        "len(regexp_extract_all(regexp_replace(regexp_replace(s.movetext, '\\{[^}]*\\}', ' ', 'g'),"
        " '\\d+\\.(\\.\\.)?', ' ', 'g'), '[KQRBNOa-h]\\S*'))"
    )
    sampled = f"('0x' || substr(md5(s.game_id || '{MOVE_SAMPLE_SALT}'), 1, 8))::UBIGINT < {MOVE_SAMPLE_THRESHOLD}"
    con.execute(
        f"""CREATE TABLE games AS
        SELECT
          s.game_id,
          s.Event AS event,
          lower(regexp_extract(s.Event, '^Rated (\\S+) ', 1)) AS speed,
          nullif(regexp_extract(s.Event, 'lichess\\.org/tournament/(\\w+)$', 1), '') AS tournament_id,
          s.White AS white,
          s.Black AS black,
          s.WhiteTitle AS white_title,
          s.BlackTitle AS black_title,
          s.WhiteElo::INTEGER AS white_elo,
          s.BlackElo::INTEGER AS black_elo,
          s.WhiteRatingDiff::INTEGER AS white_rating_diff,
          s.BlackRatingDiff::INTEGER AS black_rating_diff,
          s.Result AS result,
          s.Termination AS termination,
          s.ECO AS eco,
          s.Opening AS opening,
          o.opening_id,
          s.TimeControl AS time_control,
          s.started_at,
          {plies}::INTEGER AS ply_count,
          s.movetext LIKE '%[%eval %' AS has_eval,
          {sampled} AS moves_sampled
        FROM source_games s
        JOIN openings o ON o.opening = s.Opening AND o.eco IS NOT DISTINCT FROM s.ECO
        ORDER BY s.started_at, s.game_id"""
    )

    con.execute(
        """CREATE TABLE time_controls AS
        WITH parsed AS (
          SELECT time_control,
                 CASE WHEN time_control <> '-' THEN split_part(time_control, '+', 1)::INTEGER END AS base_seconds,
                 CASE WHEN time_control <> '-' THEN split_part(time_control, '+', 2)::INTEGER END AS increment_seconds
          FROM (SELECT DISTINCT time_control FROM games)
        )
        SELECT time_control, base_seconds, increment_seconds,
               base_seconds + 40 * increment_seconds AS estimated_seconds,
               CASE WHEN base_seconds IS NULL THEN 'correspondence'
                    WHEN base_seconds + 40 * increment_seconds < 30 THEN 'ultrabullet'
                    WHEN base_seconds + 40 * increment_seconds < 180 THEN 'bullet'
                    WHEN base_seconds + 40 * increment_seconds < 480 THEN 'blitz'
                    WHEN base_seconds + 40 * increment_seconds < 1500 THEN 'rapid'
                    ELSE 'classical' END AS speed
        FROM parsed
        ORDER BY estimated_seconds NULLS LAST, base_seconds, time_control"""
    )

    con.execute(
        """CREATE TABLE player_games AS
        SELECT row_number() OVER (ORDER BY game_id, color DESC)::INTEGER AS player_game_id,
               game_id, color, player, elo, rating_diff, opponent, opponent_elo, outcome
        FROM (
          SELECT game_id, 'white' AS color, white AS player, white_elo AS elo, white_rating_diff AS rating_diff,
                 black AS opponent, black_elo AS opponent_elo,
                 CASE result WHEN '1-0' THEN 'win' WHEN '0-1' THEN 'loss' WHEN '1/2-1/2' THEN 'draw' END AS outcome
          FROM games
          UNION ALL
          SELECT game_id, 'black', black, black_elo, black_rating_diff, white, white_elo,
                 CASE result WHEN '0-1' THEN 'win' WHEN '1-0' THEN 'loss' WHEN '1/2-1/2' THEN 'draw' END
          FROM games
        )
        ORDER BY game_id, color DESC"""
    )

    build_moves(con, files)
    rebuild_players(con)
    check_main(con)
    con.execute("CHECKPOINT")
    con.close()


def build_moves(con: duckdb.DuckDBPyConnection, files: str) -> None:
    """One row per move of the sampled games, read from the PGN movetext of each game."""
    con.execute(
        f"""CREATE TEMP TABLE move_tokens AS
        WITH sampled AS (
          SELECT s.game_id, s.movetext
          FROM source_games s JOIN games g ON g.game_id = s.game_id AND g.moves_sampled
        ),
        tokens AS (
          SELECT game_id, unnest(t) AS token, unnest(range(1, len(t) + 1)) AS position
          FROM (SELECT game_id, regexp_extract_all(movetext, '{TOKEN}') AS t FROM sampled)
        )
        SELECT game_id, position, token,
               CASE WHEN starts_with(token, '{{') THEN 'comment'
                    WHEN regexp_full_match(token, '\\d+\\.(\\.\\.)?') THEN 'number'
                    WHEN token IN ('1-0', '0-1', '1/2-1/2', '*') THEN 'result'
                    ELSE 'move' END AS kind
        FROM tokens"""
    )
    con.execute(
        f"""CREATE TABLE moves AS
        WITH paired AS (
          SELECT game_id, position, token, kind,
                 lead(kind) OVER w AS next_kind, lead(token) OVER w AS next_token
          FROM move_tokens
          WINDOW w AS (PARTITION BY game_id ORDER BY position)
        ),
        played AS (
          SELECT game_id, token,
                 row_number() OVER (PARTITION BY game_id ORDER BY position) AS ply,
                 CASE WHEN next_kind = 'comment' THEN next_token END AS comment
          FROM paired
          WHERE kind = 'move'
        ),
        parsed AS (
          SELECT game_id, ply, token,
                 nullif(regexp_extract(comment, '\\[%clk ([0-9:]+)\\]', 1), '') AS clock,
                 nullif(regexp_extract(comment, '\\[%eval ([^\\]\\s]+)\\]', 1), '') AS evaluation
          FROM played
        )
        SELECT
          row_number() OVER (ORDER BY game_id, ply)::INTEGER AS move_id,
          game_id,
          ply::INTEGER AS ply,
          ((ply + 1) // 2)::INTEGER AS move_number,
          CASE WHEN ply % 2 = 1 THEN 'white' ELSE 'black' END AS color,
          regexp_replace(token, '{GLYPH}', '') AS san,
          nullif(regexp_extract(token, '{GLYPH}', 1), '') AS annotation,
          (split_part(clock, ':', 1)::INTEGER * 3600 + split_part(clock, ':', 2)::INTEGER * 60
            + split_part(clock, ':', 3)::INTEGER) AS clock_seconds,
          CASE WHEN NOT starts_with(evaluation, '#') THEN round(evaluation::DECIMAL(10, 2) * 100)::INTEGER END AS eval_cp,
          CASE WHEN starts_with(evaluation, '#') THEN substr(evaluation, 2)::INTEGER END AS eval_mate
        FROM parsed
        ORDER BY game_id, ply"""
    )
    unattached = con.execute(
        """SELECT count(*) FROM (
             SELECT kind, lag(kind) OVER (PARTITION BY game_id ORDER BY position) AS previous FROM move_tokens
           ) WHERE kind = 'comment' AND previous IS DISTINCT FROM 'move'"""
    ).fetchone()[0]
    assert unattached == 0, f"{unattached} comments do not follow a move"
    con.execute("DROP TABLE move_tokens")


def rebuild_players(con: duckdb.DuckDBPyConnection) -> None:
    """One row per player in the database's games: how many they played, when they played their
    first and last, and the speed and pre-game rating of the last (ties broken by game_id)."""
    con.execute(
        """CREATE OR REPLACE TABLE players AS
        WITH sides AS (
          SELECT p.player, p.elo, g.started_at, g.game_id, g.speed,
                 CASE p.color WHEN 'white' THEN g.white_title ELSE g.black_title END AS title
          FROM player_games p JOIN games g ON g.game_id = p.game_id
        ),
        ranked AS (
          SELECT *,
                 row_number() OVER (PARTITION BY player ORDER BY started_at DESC, game_id DESC) AS recency,
                 count(*) OVER (PARTITION BY player) AS games_played,
                 min(started_at) OVER (PARTITION BY player) AS first_game_at
          FROM sides
        )
        SELECT player, title, games_played::INTEGER AS games_played, first_game_at,
               started_at AS last_game_at, speed AS last_speed, elo AS last_elo
        FROM ranked
        WHERE recency = 1
        ORDER BY player"""
    )


def check_main(con: duckdb.DuckDBPyConnection) -> None:
    def one(sql: str):
        return con.execute(sql).fetchone()

    source, games, ids = one("SELECT (SELECT count(*) FROM source_games), count(*), count(DISTINCT game_id) FROM games")
    assert source == games == ids, (source, games, ids)
    assert one("SELECT count(*) FROM player_games")[0] == 2 * games
    bad = one(
        """SELECT count(*) FROM games g
           LEFT JOIN (SELECT game_id, count(*) AS n FROM moves GROUP BY 1) m USING (game_id)
           WHERE g.moves_sampled AND coalesce(m.n, 0) <> g.ply_count"""
    )[0]
    assert bad == 0, f"{bad} sampled games whose moves disagree with ply_count"
    orphan = one("SELECT count(*) FROM moves WHERE game_id NOT IN (SELECT game_id FROM games WHERE moves_sampled)")[0]
    assert orphan == 0
    not_san = one(f"SELECT count(*) FROM moves WHERE NOT regexp_full_match(san, '{SAN}')")[0]
    assert not_san == 0, f"{not_san} moves are not SAN"
    clocks = one(
        """SELECT count(*) FROM moves m JOIN games g USING (game_id)
           WHERE (m.clock_seconds IS NULL) <> (g.time_control = '-')"""
    )[0]
    assert clocks == 0, f"{clocks} moves with a missing or unexpected clock"
    speeds = one("SELECT count(*) FROM games g JOIN time_controls t USING (time_control) WHERE g.speed <> t.speed")[0]
    assert speeds == 0, f"{speeds} games whose event speed differs from their time control's"
    assert one("SELECT sum(games_played) FROM players")[0] == 2 * games


def main() -> None:
    paths = download()
    build_main(paths)
    variants = build_variants(MAIN, FACT_KEYS)
    for path in variants.values():
        con = duckdb.connect(str(path))
        rebuild_players(con)
        con.execute("CHECKPOINT")
        con.close()
    write_manifest(
        HERE,
        {
            "name": "lichess",
            "source": (
                "Lichess open database (database.lichess.org), June 2018 export, via the Hugging Face dataset "
                f"Lichess/standard-chess-games at revision {REVISION}: games started 2018-06-01 to 2018-06-03 UTC"
            ),
            "license": "CC0 1.0 (Lichess open database)",
            "files": {f"{PARTITION}/{name}": sha256 for name, sha256 in FILES.items()},
        },
        {"main": MAIN, **variants},
    )


if __name__ == "__main__":
    main()
