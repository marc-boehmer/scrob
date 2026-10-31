---
name: release-notes
description: Use before implementing a feature or bug fix to ask whether the user wants an in-app release note, then record approved release notes in a database migration and update the README.
---

# In-app release notes

Before changing code for a requested feature or bug fix:

1. Ask the user whether they want this change announced in the in-app release notes. Use the `ask_user` tool and wait for the answer before implementation.
2. Always update `README.md` to document the user-visible feature or bug-fix behavior, regardless of whether a release note is approved.
3. If approved, add a new database migration that inserts the announcement into `release_announcements` and creates a `release_announcement` notification for each existing user. Follow the latest migration chain and the established migration pattern; do not modify migrations already applied in deployed databases.
4. Keep release-note content user-facing and understandable without developer context. Include the version, a concise title, and the changes users need to know about.
5. If the user declines, do not add release-announcement data or notifications.

The announcement body is stored in the database and shown in the in-app notification popup. Do not substitute GitHub links, commit comparisons, or external release pages for the in-app change description.
