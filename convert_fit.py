#!/usr/bin/env python3
"""
Convert non-Garmin FIT files and upload them to Garmin Connect with
Training Effect / training load support.

Garmin Connect only calculates Training Effect for activities from Garmin
devices. This tool spoofs the manufacturer field so Garmin recalculates
TE from the HR data itself.

Usage:
    # One-time authentication (saves tokens to ~/.fit4garmin)
    fit4garmin auth

    # Convert and upload in one step
    fit4garmin upload ride.fit

    # Convert only (no Garmin account needed)
    fit4garmin convert ride.fit -o ride_garmin.fit

    # Show your Garmin stats (VO2max, RHR, etc.)
    fit4garmin stats
"""
import argparse
import os
import sys
import tempfile
from datetime import date
from getpass import getpass
from pathlib import Path

from garminconnect import Garmin, GarminConnectAuthenticationError

sys.path.insert(0, str(Path(__file__).parent / "src"))
from fit4garmin.convert import convert_fit  # noqa: E402

TOKENSTORE = Path.home() / ".garminconnect"


def garmin_login(tokenstore: str | None = None) -> Garmin:
    store = tokenstore or str(TOKENSTORE)
    garmin = Garmin()
    garmin.login(store)
    return garmin


def cmd_auth(args):
    store = str(TOKENSTORE)

    # Try existing tokens first
    try:
        garmin = garmin_login(store)
        name = garmin.get_full_name()
        print(f"Already authenticated as {name}")
        if not args.force:
            return
        print("Re-authenticating (--force)...")
    except Exception:
        pass

    email = args.email or input("Garmin email: ")
    password = args.password or getpass("Garmin password: ")

    garmin = Garmin(email=email, password=password, return_on_mfa=True)
    result = garmin.login()

    if result and result[0] == "needs_mfa":
        mfa_code = input("MFA code: ")
        garmin.resume_login(result[1], mfa_code)

    TOKENSTORE.mkdir(mode=0o700, exist_ok=True)
    garmin.client.dump(store)

    # Lock down token files
    for f in TOKENSTORE.iterdir():
        f.chmod(0o600)

    name = garmin.get_full_name()
    print(f"Authenticated as {name}")
    print(f"Tokens saved to {TOKENSTORE}")


def cmd_convert(args):
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_stem(input_path.stem + "_garmin")

    print(f"Converting {input_path}...")
    stats = convert_fit(str(input_path), str(output_path))
    print(f"Output: {output_path} ({stats['output_size']} bytes)")


def cmd_upload(args):
    try:
        garmin = garmin_login()
    except GarminConnectAuthenticationError:
        print("Not authenticated. Run 'fit4garmin auth' first.", file=sys.stderr)
        sys.exit(1)

    for input_file in args.inputs:
        input_path = Path(input_file)
        if not input_path.exists():
            print(f"Error: {input_path} not found", file=sys.stderr)
            continue

        with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            print(f"Converting {input_path}...")
            convert_fit(str(input_path), tmp_path)

            print(f"Uploading to Garmin Connect...")
            result = garmin.upload_activity(tmp_path)
            print(f"Uploaded: {input_path.name} -> {result}")
        finally:
            os.unlink(tmp_path)


def cmd_stats(args):
    try:
        garmin = garmin_login()
    except GarminConnectAuthenticationError:
        print("Not authenticated. Run 'fit4garmin auth' first.", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()
    name = garmin.get_full_name()
    print(f"User: {name}")

    try:
        training = garmin.get_training_status(today)
        vo2max_data = training.get("mostRecentVO2Max", {})
        cycling = vo2max_data.get("cycling", {})
        generic = vo2max_data.get("generic", {})
        vo2_precise = cycling.get("vo2MaxPreciseValue") or generic.get("vo2MaxPreciseValue")
        print(f"VO2max: {vo2_precise}")
    except Exception as e:
        print(f"VO2max: unavailable ({e})")

    try:
        rhr = garmin.get_rhr_day(today)
        rhr_values = rhr.get("allMetrics", {}).get("metricsMap", {}).get("WELLNESS_RESTING_HEART_RATE", [])
        if rhr_values:
            latest = rhr_values[-1].get("value")
            print(f"Resting HR: {latest}")
        else:
            print("Resting HR: no data today")
    except Exception as e:
        print(f"Resting HR: unavailable ({e})")

    try:
        stats = garmin.get_user_summary(today)
        print(f"Today's max HR: {stats.get('maxHeartRate', 'N/A')}")
    except Exception as e:
        print(f"Today's max HR: unavailable ({e})")


def main():
    parser = argparse.ArgumentParser(
        prog="fit4garmin",
        description="Convert non-Garmin FIT files for Garmin Connect training load",
    )
    sub = parser.add_subparsers(dest="command")

    # auth
    p_auth = sub.add_parser("auth", help="Authenticate with Garmin Connect")
    p_auth.add_argument("--email", help="Garmin email (or prompt)")
    p_auth.add_argument("--password", help="Garmin password (or prompt)")
    p_auth.add_argument("--force", action="store_true", help="Force re-authentication")

    # convert
    p_convert = sub.add_parser("convert", help="Convert FIT file (no upload)")
    p_convert.add_argument("input", help="Input FIT file")
    p_convert.add_argument("-o", "--output", help="Output path (default: input_garmin.fit)")

    # upload
    p_upload = sub.add_parser("upload", help="Convert and upload to Garmin Connect")
    p_upload.add_argument("inputs", nargs="+", help="FIT file(s) to convert and upload")

    # stats
    sub.add_parser("stats", help="Show Garmin stats (VO2max, RHR, etc.)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    try:
        {"auth": cmd_auth, "convert": cmd_convert, "upload": cmd_upload, "stats": cmd_stats}[
            args.command
        ](args)
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
