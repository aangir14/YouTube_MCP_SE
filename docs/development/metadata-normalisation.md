+# Shared Metadata Normalisation
+
+[C11 plan](../../FocusList_Commit_Plan.md#c11-normalise-identifiers-duration-and-metadata) · [Discovery and analytics contract](../adr/ADR-002-discovery-analytics-and-ranking-evaluation.md) · [Curation contract](../adr/ADR-004-playlist-action-lifecycle-and-threat-model.md) · [UT-PARSE](../testing/acceptance-cases.md#ut-parse)
+
+## Call the shared parsers before provider access
+
+~~~python
+from focuslist.metadata import (
+    parse_channel_reference,
+    parse_duration_seconds,
+    parse_playlist_id,
+    parse_utc_datetime,
+    parse_video_id,
+    same_primary_language,
+)
+
+video_id = parse_video_id("https://youtu.be/syn_vid0001")
+channel = parse_channel_reference("https://www.youtube.com/@synthetic_tech")
+playlist_id = parse_playlist_id("https://www.youtube.com/playlist?list=PLfixture_01")
+
+target_seconds = parse_duration_seconds("PT2H", allow_zero=False)
+start = parse_utc_datetime("2026-11-25", allow_date=True)
+match = same_primary_language("en-GB", "en-US")
+~~~
+
+| Caller | Contract |
+| --- | --- |
+| C14 video discovery | Parse the raw 11-character ID, watch, short link, Shorts or embed reference. Pass the resulting ID to the provider and use it for cache keys. Use `video_watch_url` for display. Invalid syntax raises `INVALID_VIDEO_ID`. A syntactically valid missing seed is a provider availability result. |
+| C17 channel discovery | Accept a canonical `UC` ID (24 characters), a bare `@handle`, or the corresponding `/channel/ID` and `/@handle` URLs. Pass `**channel.provider_arguments()` to the provider. Before resolution, `channel.cache_key` distinguishes IDs from case-insensitive handles. After resolution, key shared records by the returned channel ID. Legacy `/c/` URLs raise `INVALID_CHANNEL_ID` with a replacement hint. |
+| C12/C15 curation | Use whole seconds for min, max, target and session constraints. Use `allow_zero=False` for positive constraints and apply cross-field constraints in the solver. For a hard language constraint, inspect provenance and require `same_primary_language(...) is True` if the policy requires known language. |
+| C20/C23 recommendations and analytics | Compare primary language subtags, and parse explicit period boundaries via `parse_utc_datetime(..., allow_date=True)`. Validate window ordering at the tool layer. Use offset-aware provider timestamps. Keep missing source dates unknown until FR-4 chooses and labels a fallback. |
+| C29 playlist analysis | Accept a bare opaque ID or an HTTPS `/playlist?list=…`, `/watch?list=…` or YouTube short link containing one valid `list` value. Use `playlist_url` for canonical links. The local syntax accepts 10–128 URL-safe characters plus `LL` and `WL`. Authorisation, supported list types, and playlist existence are provider concerns. Invalid syntax raises `INVALID_ARGUMENTS`. |
+
+URL parsing allows the exact HTTPS hosts `youtube.com`, `www.youtube.com`, `m.youtube.com`, plus `youtu.be` where indicated. It rejects credentials, explicit ports, control characters, unsupported paths and duplicate identifying parameters. Pass a parser's domain errors into the existing C07 error envelope. Do this before quota charging or calling the provider.
+
+## Time and metadata representation
+
+- **Duration.** `parse_duration_seconds` supports fixed whole-second ISO-8601 units, including days and standalone weeks. Calendar months and years, fractional values, negative values, empty forms and integer overflow are rejected. `format_duration_iso` serializes a known integer value. The shared C07 `format_duration_display` renders `mm:ss` or `h:mm:ss`. A known zero yields `PT0S` and `00:00`; missing yields `None`.
+- **Datetime.** `parse_utc_datetime` returns a UTC-aware `datetime` from an explicit offset or `Z`. Fractional seconds may have up to six digits. Naive timestamps and leap seconds are unsupported. When explicitly allowed, a calendar date starts at UTC midnight. Use [RFC 3339](https://www.rfc-editor.org/rfc/rfc3339) for the timestamp form.
+- **Language.** `select_video_language` returns a normalized tag and provenance. Prefer YouTube's default audio field when usable, otherwise keep the metadata-language fallback labelled as such. `same_primary_language` returns `None` when either tag is unknown, `True` for a known primary-subtag match, and `False` for a known mismatch. The helper supports modern [BCP 47](https://www.rfc-editor.org/rfc/rfc5646) syntax without registry alias resolution. Metadata-language evidence describes title and description. [Official YouTube video resource](https://developers.google.com/youtube/data/reference/rest/v3/videos)
+- **Records.** Build a C07 `VideoRecord`, `ChannelRecord`, or `AccountActivityRecord` from provider data and pass it to `normalise_video_record`, `normalise_channel_record`, or `normalise_activity_record`. The adapters return a copy. Keep absent tags, keywords and descriptions null and preserve supplied empty lists or strings. A valid ISO duration is authoritative over a numeric copy. An independent valid numeric duration is retained when ISO duration is absent or invalid. A hidden subscriber count remains unknown even if a number was supplied. Missing visibility and live/age flags remain unknown. Display text stays untrusted and the description cap includes the ellipsis. Timestamp provenance is preserved for a usable instant. The adapter leaves missing dates and unknown provenance for C23 to handle.
+
+The fixture provider uses the same video/channel adapters. The current MCP scaffold calls the identifier helpers at its read entry points and validates both required proposal durations and language before discovery. C14, C17, C20, C23 and C29 implement the rest of their feature contracts. Run the focused offline checks with `python -m pytest tests/unit/test_metadata.py tests/integration/test_metadata_boundary.py -q`.
