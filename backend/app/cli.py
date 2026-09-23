"""Operator CLI: python -m app.cli create-district|create-station|create-user|oversee|reset-mfa|unlock ...

Needed because there is deliberately no public sign-up: the first admin/auditor accounts, and every senior-officer
(station_head/superintendent), forensic and judge account, are created by whoever operates the deployment - a
station admin can only self-service plain officer accounts through the API."""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from . import audit
from .config import Settings
from .db import Base, make_engine, make_session_factory
from .models import ROLES, StationOversight, User
from .seed import create_user, get_or_create_district, get_or_create_station
from .security import password_problem

OFFICER_RANKS = ("officer", "station_head", "superintendent")
JUDGE_RANKS = ("officer", "district_court", "high_court")  # "officer" here = no automatic court-wide reach


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("create-district", help="groups stations; gives a forensic lab or district court a home")
    d.add_argument("--code", required=True)
    d.add_argument("--name", required=True)
    s = sub.add_parser("create-station")
    s.add_argument("--code", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--district-code", help="optional; groups the station under a district")
    u = sub.add_parser("create-user")
    u.add_argument("--username", required=True)
    u.add_argument("--full-name", required=True)
    u.add_argument("--role", required=True, choices=list(ROLES))
    u.add_argument("--rank", default="officer", choices=sorted(set(OFFICER_RANKS) | set(JUDGE_RANKS)),
                   help="officer: officer|station_head|superintendent. judge: officer|district_court|high_court")
    u.add_argument("--station-code", help="required for admin, and for officer unless --rank superintendent")
    u.add_argument("--district-code", help="forensic (its lab's district) or judge --rank district_court (required)")
    o = sub.add_parser("oversee", help="grant a rank=superintendent officer content access to an extra station")
    o.add_argument("--username", required=True)
    o.add_argument("--station-code", required=True)
    for name, help_ in (("reset-mfa", "clear a user's authenticator so they enrol a new one at next sign-in (lost phone)"),
                        ("unlock", "clear a lockout after failed sign-ins")):
        r = sub.add_parser(name, help=help_)
        r.add_argument("--username", required=True)
    args = p.parse_args(argv)

    settings = Settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as db:
        if args.cmd == "create-district":
            get_or_create_district(db, args.code.upper(), args.name)
            db.commit()
            print(f"District {args.code.upper()} ready.")
            return 0

        if args.cmd == "create-station":
            district = get_or_create_district(db, args.district_code.upper(), args.district_code.upper()) if args.district_code else None
            get_or_create_station(db, args.code.upper(), args.name, district)
            db.commit()
            print(f"Station {args.code.upper()} ready" + (f" (district {district.code})." if district else "."))
            return 0

        if args.cmd == "oversee":
            target = db.execute(select(User).where(User.username == args.username)).scalar_one_or_none()
            if target is None or target.role != "officer" or target.rank != "superintendent":
                print(f"{args.username} is not a role=officer, rank=superintendent account", file=sys.stderr)
                return 1
            station = get_or_create_station(db, args.station_code.upper(), args.station_code.upper())
            exists = db.execute(select(StationOversight.id).where(
                StationOversight.user_id == target.id, StationOversight.station_id == station.id)).first()
            if exists:
                print(f"{args.username} already oversees {station.code}.")
                return 0
            db.add(StationOversight(user_id=target.id, station_id=station.id, granted_by=target.id))
            audit.append(db, action="STATION_OVERSIGHT_GRANTED", actor_username="cli", resource_type="user",
                         resource_id=target.id, detail={"username": target.username, "station": station.code})
            db.commit()
            print(f"{args.username} now oversees {station.code}.")
            return 0

        if args.cmd in ("reset-mfa", "unlock"):
            # Break-glass for accounts no station admin can manage (auditors, admins). Whoever can run this already
            # has database access, so it is written to the audit chain rather than pretending to authenticate.
            target = db.execute(select(User).where(User.username == args.username)).scalar_one_or_none()
            if target is None:
                print(f"No such user: {args.username}", file=sys.stderr)
                return 1
            if args.cmd == "reset-mfa":
                target.totp_enabled, target.totp_secret_enc, target.totp_last_step = False, None, 0
                target.token_version += 1   # signs out every session of that user
            target.failed_attempts, target.locked_until = 0, None
            audit.append(db, action="MFA_RESET" if args.cmd == "reset-mfa" else "ACCOUNT_UNLOCKED", actor_username="cli",
                         resource_type="user", resource_id=target.id, detail={"username": target.username, "via": "cli"})
            db.commit()
            print(f"{args.username}: {'authenticator cleared - they enrol a new one at next sign-in' if args.cmd == 'reset-mfa' else 'unlocked'}.")
            return 0

        if args.role == "officer" and args.rank not in OFFICER_RANKS:
            print(f"--rank {args.rank} is a judge rank; --role officer takes {OFFICER_RANKS}", file=sys.stderr)
            return 2
        if args.role == "judge" and args.rank not in JUDGE_RANKS:
            print(f"--rank {args.rank} is an officer rank; --role judge takes {JUDGE_RANKS}", file=sys.stderr)
            return 2
        if args.rank != "officer" and args.role not in ("officer", "judge"):
            print("--rank only applies to --role officer or --role judge", file=sys.stderr)
            return 2
        if args.role == "judge" and args.rank == "district_court" and not args.district_code:
            print("--district-code is required for --role judge --rank district_court", file=sys.stderr)
            return 2
        if args.role == "forensic" and not args.district_code:
            print("--district-code is required for --role forensic (each forensic lab belongs to one district)", file=sys.stderr)
            return 2

        station_needed = args.role == "admin" or (args.role == "officer" and args.rank != "superintendent")
        station = None
        if station_needed:
            if not args.station_code:
                print("--station-code is required for admin, and for officer unless --rank superintendent", file=sys.stderr)
                return 2
            station = get_or_create_station(db, args.station_code.upper(), args.station_code.upper())
        elif args.station_code:
            station = get_or_create_station(db, args.station_code.upper(), args.station_code.upper())  # optional "home" station

        district = get_or_create_district(db, args.district_code.upper(), args.district_code.upper()) if args.district_code else None
        # Interactive: hidden prompt. Piped (provisioning scripts): first line of stdin, so the
        # password never appears in the process list or shell history.
        password = getpass.getpass("Initial password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\r\n")
        problem = password_problem(password, args.username)
        if problem:
            print(problem, file=sys.stderr)
            return 2
        create_user(db, username=args.username, full_name=args.full_name, password=password, role=args.role,
                    rank=args.rank, station=station, district=district, must_change_password=True)
        db.commit()
        print(f"User {args.username} created. They must change the password and enrol MFA at first login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
