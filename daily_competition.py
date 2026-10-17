import sqlite3

from database import (
    get_connection,
    current_date,
    current_time,
)

from config import (
    DAILY_WINNERS_COUNT,
    STARS_PER_WINNER,
)


def finalize_competition(competition_date=None):
    """
    Finalize a day's competition:
    1. Rank users by coins, then referrals.
    2. Save final ranks.
    3. Save the top 10 winners.
    4. Preserve results permanently.

    Daily counters are NOT reset here.
    """

    if competition_date is None:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        from config import TIMEZONE

        today = datetime.now(ZoneInfo(TIMEZONE)).date()
        competition_date = (today - timedelta(days=1)).isoformat()

    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        existing_run = connection.execute(
            """
            SELECT status
            FROM competition_runs
            WHERE competition_date = ?
            """,
            (competition_date,),
        ).fetchone()

        if existing_run and existing_run["status"] == "completed":
            connection.commit()
            return get_winners(competition_date)

        rows = connection.execute(
            """
            SELECT
                ds.user_id,
                ds.referrals,
                ds.coins
            FROM daily_stats AS ds
            WHERE ds.competition_date = ?
            ORDER BY
                ds.coins DESC,
                ds.referrals DESC,
                ds.user_id ASC
            """,
            (competition_date,),
        ).fetchall()

        connection.execute(
            """
            DELETE FROM daily_winners
            WHERE competition_date = ?
            """,
            (competition_date,),
        )

        winners = []

        for rank, row in enumerate(rows, start=1):
            user_id = row["user_id"]
            referrals = row["referrals"]
            coins = row["coins"]
            is_winner = rank <= DAILY_WINNERS_COUNT

            connection.execute(
                """
                UPDATE daily_stats
                SET final_rank = ?, is_winner = ?
                WHERE user_id = ? AND competition_date = ?
                """,
                (
                    rank,
                    1 if is_winner else 0,
                    user_id,
                    competition_date,
                ),
            )

            if is_winner:
                connection.execute(
                    """
                    INSERT INTO daily_winners (
                        competition_date,
                        rank,
                        user_id,
                        referrals,
                        coins,
                        reward_stars,
                        reward_status,
                        announced,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        competition_date,
                        rank,
                        user_id,
                        referrals,
                        coins,
                        STARS_PER_WINNER,
                        "pending",
                        0,
                        current_time(),
                    ),
                )

                winners.append({
                    "competition_date": competition_date,
                    "rank": rank,
                    "user_id": user_id,
                    "referrals": referrals,
                    "coins": coins,
                    "reward_stars": STARS_PER_WINNER,
                    "reward_status": "pending",
                    "announced": 0,
                })

        connection.execute(
            """
            INSERT INTO competition_runs (
                competition_date,
                status,
                started_at,
                completed_at,
                total_participants,
                total_winners
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(competition_date)
            DO UPDATE SET
                status = excluded.status,
                completed_at = excluded.completed_at,
                total_participants = excluded.total_participants,
                total_winners = excluded.total_winners
            """,
            (
                competition_date,
                "completed",
                current_time(),
                current_time(),
                len(rows),
                len(winners),
            ),
        )

        connection.commit()
        return winners

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_winners(competition_date=None):
    """Return saved winners for a competition date."""

    if competition_date is None:
        competition_date = current_date()

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                competition_date,
                rank,
                user_id,
                referrals,
                coins,
                reward_stars,
                reward_status,
                announced
            FROM daily_winners
            WHERE competition_date = ?
            ORDER BY rank ASC
            """,
            (competition_date,),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()


def mark_winners_announced(competition_date):
    """Mark saved winners as announced after the results broadcast succeeds."""

    connection = get_connection()

    try:
        connection.execute(
            """
            UPDATE daily_winners
            SET announced = 1
            WHERE competition_date = ?
            """,
            (competition_date,),
        )

        connection.commit()

    finally:
        connection.close()


def update_reward_status(
    competition_date,
    user_id,
    status,
):
    """Update reward status, for example pending, sent, or failed."""

    allowed_statuses = {"pending", "sent", "failed"}

    if status not in allowed_statuses:
        raise ValueError(
            "Invalid reward status. Use pending, sent, or failed."
        )

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE daily_winners
            SET reward_status = ?
            WHERE competition_date = ?
              AND user_id = ?
            """,
            (status, competition_date, user_id),
        )

        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()
