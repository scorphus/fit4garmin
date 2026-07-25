# fit4garmin

Upload Wahoo (or any non-Garmin) rides to Garmin Connect *with* Training
Effect and training load.

Garmin Connect only calculates Training Effect, training load, and related
Firstbeat metrics for activities recorded by Garmin devices. Activities from
a Wahoo ELEMNT (or anything else) sync fine but never count toward training
load. It turns out the fix is simple: rewrite the manufacturer in the FIT
file's `file_id` and `device_info` messages and Garmin recalculates
everything from the raw heart-rate data itself.

## CLI

```sh
uv pip install -r requirements.txt

# one-time login (tokens cached in ~/.garminconnect, MFA supported)
uv run python3 convert_fit.py auth

# convert + upload in one step
uv run python3 convert_fit.py upload ride.fit [more.fit ...]

# or convert only
uv run python3 convert_fit.py convert ride.fit -o ride_garmin.fit

# show VO2max / resting HR from your Garmin profile
uv run python3 convert_fit.py stats
```

## Web app

A stateless FastAPI app (deployable on Vercel) that does the same through
the browser: sign in with Garmin, drop FIT files, done.

No server-side storage: your Garmin OAuth tokens are zlib-compressed,
Fernet-encrypted, and stored as a cookie in your own browser. The only
secret the server holds is `FIT4GARMIN_SECRET`, which seals the cookies.
Passwords are used once for the Garmin sign-in and never persisted.

```sh
# run locally
FIT4GARMIN_SECRET=dev uv run uvicorn --app-dir src fit4garmin.app:app

# deploy
vercel env add FIT4GARMIN_SECRET production  # secrets.token_urlsafe(32)
vercel deploy --prod
```

## Disclaimer

This is an unofficial tool that talks to Garmin Connect through unofficial
APIs and rewrites device metadata in FIT files. Use it for your own
activities, at your own risk.

## License

[BSD 3-Clause](LICENSE)
