# FocusList MCP Interface Reference

Auto-generated from `focuslist.server.create_server()` FastMCP tool, resource, and prompt schemas.

## Registered Tools

| Tool | Description | Required Inputs |
| :--- | :--- | :--- |
| `analyse_engagement` | Analyze viewing and engagement patterns across categories, channels, and durations. | `sources` |
| `analyse_playlist` | Summarize a public or user playlist's duration distribution and topics. | `playlist_url_or_id` |
| `audit_playlist` | Audit a playlist for unavailable, duplicate, overlong, stale, live or upcoming items. | `playlist_url_or_id` |
| `auth_status` | Inspect current Google OAuth authorization status, scopes, and token age. | `*(none)*` |
| `confirm_playlist` | Execute the stored playlist action only after a separate human approval. | `proposal_id, token` |
| `estimate_quota` | Estimate the worst-case quota units and search calls for a planned tool call. | `target_tool` |
| `get_quota_status` | Inspect the local quota ledger: general units and search calls remaining today. | `*(none)*` |
| `get_video_details` | Fetch verified metadata fact sheet and public statistics for a YouTube video. | `video_url_or_id` |
| `propose_playlist` | Formulate an immutable, constraint-bounded playlist proposal for user review. | `topic, target_duration, max_item_duration` |
| `recommend_videos` | Recommend videos tailored to the learner's authorized likes, subscriptions, and playlists. | `sources` |
| `resume_playlist` | Check an interrupted creation and propose only its remaining insertions. | `proposal_id` |
| `similar_channels` | Discover channels covering similar topics to a seed channel handle or ID. | `channel_url_handle_or_id` |
| `similar_videos` | Discover and rank YouTube videos similar to a seed video using metadata similarity. | `video_url_or_id` |
| `undo_playlist` | Propose deletion of a FocusList-created playlist within the 30-day retention window. | `playlist_id` |

## Registered Resources

| URI | Name | Description |
| :--- | :--- | :--- |
| `focuslist://config/scoring` | `get_scoring_weights` | Return the active named weights for FR-1, FR-2, FR-3 and FR-5. |
| `focuslist://quota/status` | `get_quota_resource` | Plaintext quota ledger resource. |
| `focuslist://skills/playlist-audit` | `get_playlist_audit_skill` | Return the SK-6 read-only audit instructions. |

## Registered Prompts

| Prompt | Description |
| :--- | :--- |
| `playlist-audit` | Prompt template for playlist audit and health inspection. |
| `video-to-playlist` | Prompt template for end-to-end video discovery and curation workflow. |

## Tool Input Schemas (JSON)

### `analyse_engagement`

```json
{
  "properties": {
    "comparison_period": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Comparison Period"
    },
    "group_by": {
      "default": "week",
      "title": "Group By",
      "type": "string"
    },
    "period": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Period"
    },
    "period_days": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Period Days"
    },
    "sources": {
      "items": {
        "type": "string"
      },
      "title": "Sources",
      "type": "array"
    }
  },
  "required": [
    "sources"
  ],
  "title": "analyse_engagementArguments",
  "type": "object"
}
```

### `analyse_playlist`

```json
{
  "properties": {
    "item_limit": {
      "default": 500,
      "title": "Item Limit",
      "type": "integer"
    },
    "playlist_url_or_id": {
      "title": "Playlist Url Or Id",
      "type": "string"
    }
  },
  "required": [
    "playlist_url_or_id"
  ],
  "title": "analyse_playlistArguments",
  "type": "object"
}
```

### `audit_playlist`

```json
{
  "properties": {
    "item_limit": {
      "default": 500,
      "title": "Item Limit",
      "type": "integer"
    },
    "max_item_length_minutes": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Max Item Length Minutes"
    },
    "playlist_url_or_id": {
      "title": "Playlist Url Or Id",
      "type": "string"
    },
    "stale_after_years": {
      "default": 5,
      "title": "Stale After Years",
      "type": "integer"
    }
  },
  "required": [
    "playlist_url_or_id"
  ],
  "title": "audit_playlistArguments",
  "type": "object"
}
```

### `auth_status`

```json
{
  "properties": {},
  "title": "auth_statusArguments",
  "type": "object"
}
```

### `confirm_playlist`

```json
{
  "properties": {
    "proposal_id": {
      "title": "Proposal Id",
      "type": "string"
    },
    "token": {
      "title": "Token",
      "type": "string"
    }
  },
  "required": [
    "proposal_id",
    "token"
  ],
  "title": "confirm_playlistArguments",
  "type": "object"
}
```

### `estimate_quota`

```json
{
  "properties": {
    "arguments": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Arguments"
    },
    "target_tool": {
      "title": "Target Tool",
      "type": "string"
    }
  },
  "required": [
    "target_tool"
  ],
  "title": "estimate_quotaArguments",
  "type": "object"
}
```

### `get_quota_status`

```json
{
  "properties": {},
  "title": "get_quota_statusArguments",
  "type": "object"
}
```

### `get_video_details`

```json
{
  "properties": {
    "video_url_or_id": {
      "title": "Video Url Or Id",
      "type": "string"
    }
  },
  "required": [
    "video_url_or_id"
  ],
  "title": "get_video_detailsArguments",
  "type": "object"
}
```

### `propose_playlist`

```json
{
  "properties": {
    "allow_age_restricted": {
      "default": false,
      "title": "Allow Age Restricted",
      "type": "boolean"
    },
    "allow_unknown_language": {
      "default": false,
      "title": "Allow Unknown Language",
      "type": "boolean"
    },
    "item_limit": {
      "default": 30,
      "title": "Item Limit",
      "type": "integer"
    },
    "language": {
      "default": "en",
      "title": "Language",
      "type": "string"
    },
    "max_item_duration": {
      "title": "Max Item Duration",
      "type": "string"
    },
    "min_item_duration": {
      "default": "PT2M",
      "title": "Min Item Duration",
      "type": "string"
    },
    "ordering": {
      "default": "learning_path",
      "title": "Ordering",
      "type": "string"
    },
    "privacy_status": {
      "default": "private",
      "title": "Privacy Status",
      "type": "string"
    },
    "seed": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Seed"
    },
    "session_minutes": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Session Minutes"
    },
    "target_duration": {
      "title": "Target Duration",
      "type": "string"
    },
    "title": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Title"
    },
    "tolerance": {
      "default": 0.05,
      "title": "Tolerance",
      "type": "number"
    },
    "topic": {
      "title": "Topic",
      "type": "string"
    }
  },
  "required": [
    "topic",
    "target_duration",
    "max_item_duration"
  ],
  "title": "propose_playlistArguments",
  "type": "object"
}
```

### `recommend_videos`

```json
{
  "properties": {
    "limit": {
      "default": 10,
      "title": "Limit",
      "type": "integer"
    },
    "sources": {
      "items": {
        "type": "string"
      },
      "title": "Sources",
      "type": "array"
    },
    "topic": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Topic"
    }
  },
  "required": [
    "sources"
  ],
  "title": "recommend_videosArguments",
  "type": "object"
}
```

### `resume_playlist`

```json
{
  "properties": {
    "proposal_id": {
      "title": "Proposal Id",
      "type": "string"
    }
  },
  "required": [
    "proposal_id"
  ],
  "title": "resume_playlistArguments",
  "type": "object"
}
```

### `similar_channels`

```json
{
  "properties": {
    "channel_url_handle_or_id": {
      "title": "Channel Url Handle Or Id",
      "type": "string"
    },
    "limit": {
      "default": 10,
      "title": "Limit",
      "type": "integer"
    }
  },
  "required": [
    "channel_url_handle_or_id"
  ],
  "title": "similar_channelsArguments",
  "type": "object"
}
```

### `similar_videos`

```json
{
  "properties": {
    "limit": {
      "default": 10,
      "title": "Limit",
      "type": "integer"
    },
    "video_url_or_id": {
      "title": "Video Url Or Id",
      "type": "string"
    }
  },
  "required": [
    "video_url_or_id"
  ],
  "title": "similar_videosArguments",
  "type": "object"
}
```

### `undo_playlist`

```json
{
  "properties": {
    "playlist_id": {
      "title": "Playlist Id",
      "type": "string"
    }
  },
  "required": [
    "playlist_id"
  ],
  "title": "undo_playlistArguments",
  "type": "object"
}
```
