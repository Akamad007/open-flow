# Content Safety

OpenFlow generates images, video, and speech from user-supplied prompts and
reference media. **It ships without automated content moderation** — prompts and
reference images are not screened, and outputs are not classified or watermarked.

This is acceptable for a single-operator/research tool. **It is not sufficient
for a multi-user service.**

## Current posture (alpha)

- No prompt moderation, no output classification, no NSFW filter, no watermark.
- The underlying model licenses independently prohibit illegal content; you are
  bound by them (see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)).
- Identity synthesis has additional rules — see [ETHICAL_USE.md](ETHICAL_USE.md).

## If you operate OpenFlow as a service

You are responsible for adding controls appropriate to your users and
jurisdiction. Recommended:

- **Input moderation** — screen prompts and reference images before generation
  (a moderation API or a local classifier) at the provider boundary in
  `backend/app/providers/`.
- **Output review / classification** — gate or flag generated media.
- **Provenance** — apply C2PA / a visible "AI-generated" watermark.
- **Consent + audit** — enforce `REQUIRE_CONSENT_ACKNOWLEDGMENT=true` and log
  every identity-synthesis request.
- **Rate limiting + authentication** — set `API_KEY` and a proxy-level limiter.

Contributions that add an optional moderation hook are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).
